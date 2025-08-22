"""
Production allocation optimization module using Google OR-Tools CP-SAT.

Hard constraints currently enforced:
- Compatibility: items can only be produced on plants that are allowed to
  produce their model (allowedModels).
- Plant capacity: the total quantity assigned to each plant cannot exceed the
  plant's capacity.

Objective (multi-criteria):
- Maximize total allocated quantity weighted by due date priority.
- Past due items get highest priority (10000+ weight).
- Future items prioritized by proximity to due date.

Docs: CpModel.NewIntVar, CpModel.Add
- https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.NewIntVar
- https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from domain_types import Plant, Order, Item
from allocation_types import AllocationRow, SkippedRow, Summary, AllocateResult, UnallocatedRow, WeightsConfig
from ortools.sat.python import cp_model
from datetime import datetime
from input_Validations import validate_input_data




def allocate(
  plants: List[Plant],
  orders: List[Order],
  current_date: datetime,
  weights: WeightsConfig,
) -> AllocateResult:
  """
  Build an optimization CP-SAT model (always feasible) with:
  - Compatibility and plant capacity constraints.
  - All-or-nothing item placement (no splitting across plants).
  - Objective: maximize total allocated quantity weighted by due date priority,
    allowing items to remain unallocated when capacity is insufficient.

  Behavior
  - Creates integer decision variables only for (plant, item) pairs where the
    plant supports the item's model (allowedModels).
  - For each compatible item, adds a binary assignment to at most one plant
    (no split). If assigned, the full item quantity is placed at that plant.
  - Adds a plant capacity constraint: for each plant, the sum of assigned
    quantities cannot exceed its capacity.
  - For items with no compatible plant, skips them (does not add variables nor
    constraints) and records them under the returned "skipped" property.

  Args:
    plants: List of Plant dictionaries (must include 'plantid', 'capacity',
      and 'allowedModels').
    orders: List of Order dictionaries (each containing an 'items' list of
      Item dictionaries with 'model', 'submodel', 'modelFamily', and 'quantity').
    current_date: Current date for due date priority calculations.

  Weight configuration (weights dict):
    w_quantity: Weight applied to normalized quantity component (default 5 if missing).
    w_due: Weight applied to normalized due-date urgency component (default 1 if missing).
    horizon_days: Positive horizon for future due-date decay (default 30).
    scale: Integer scaling factor for normalized components (default 1000).
    weight_precision: Multiplier converting floating weights into integers (default 1).
      Effective per-item coefficient = (int(w_quantity * weight_precision) * (scale * norm_qty_k))
        + (int(w_due * weight_precision) * (scale * norm_urg_k)).
      Keep resulting product (weight * scale) *<= ~1e7 to avoid very large coefficients.

  Returns:
    AllocateResult: Typed mapping containing
      - summary: Aggregated stats and solver status.
      - allocations: Non-zero allocation rows (by plant and item fields).
      - skipped: Items not modeled due to no compatible plant with reason.

  Notes:
    - This model includes an objective (maximize allocated quantity), so it will
      not return INFEASIBLE due to capacity: items that don't fit simply remain
      unallocated. See CpModel.Add and CpModel.Maximize/CpSolver.Solve:
      https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
      https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Maximize
      https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpSolver.Solve
  """
  # Validate structural input data and provided weights/settings mapping.
  # validate_input_data now accepts either raw settings dict or WeightsConfig.
  validate_input_data(plants, orders, weights)

  # Extract weights with defaults (0.0 forces explicit user specification)
  w_quantity = float(weights.get("w_quantity", 0.0))
  w_due = float(weights.get("w_due", 0.0))
  
  horizon_days = int(weights.get("horizon_days", 30))
  scale = int(weights.get("scale", 1000))
  weight_precision = int(weights.get("weight_precision", 1))

  # Enforce required weights must be strictly positive
  if w_quantity <= 0 or w_due <= 0:
    raise ValueError("w_quantity and w_due must be > 0 (provide positive weights in settings)")
  
  # Aggregate quick stats
  total_capacity = sum(int(p.get("capacity", 0)) for p in plants)
  total_demand = 0
  unique_models: set[str] = set()
  orders_count = len(orders)

  # Flatten items: list of (order_index, item)
  items: List[Tuple[int, Item]] = []
  for oi, o in enumerate(orders):
    for it in o.get("items", []):
      qty = int(it.get("quantity", 0))
      total_demand += qty
      m_name = it.get("model")
      if isinstance(m_name, str):
        unique_models.add(m_name)
      items.append((oi, it))

  # CP-SAT model
  model = cp_model.CpModel()

  # Binary assignment variables assign[p,k] only for allowed (plant p, item k)
  assign: Dict[Tuple[int, int], cp_model.IntVar] = {}
  # placed[k] indicates whether item k is fully placed on exactly one plant
  placed: Dict[int, cp_model.IntVar] = {}

  def plant_can_make(plant: Plant, item: Item) -> bool:
    return item["model"] in plant["allowedModels"]

  # Track items that cannot be produced by any plant
  skipped: List[SkippedRow] = []
  # Indices of items skipped (no compatible plant or too large for any single plant)
  skipped_indices: set[int] = set()

  # Precompute compatible plants per item
  compatible_plants: List[List[int]] = []
  for _k_idx, (_oi, it) in enumerate(items):
    cands = [p_idx for p_idx, p in enumerate(plants) if plant_can_make(p, it)]
    compatible_plants.append(cands)

  # Create variables only for compatible (plant, item)
  for k_idx, (_oi, it) in enumerate(items):
    qty = int(it.get("quantity", 0))
    cands = compatible_plants[k_idx]
  # --- HARD feasibility preprocessing (Compatibility) ---
  # Skip any item (even zero quantity) with no compatible plant.
  # This enforces the compatibility hard constraint by construction: we simply never
  # create decision variables for incompatible (plant,item) pairs.
    if not cands:
      skipped.append({
        "order": orders[_oi]["order"],
        "order_index": _oi,
        "model": it["model"],
        "submodel": it["submodel"],
        "quantity": qty,
        "reason": "no_compatible_plant",
      })
      skipped_indices.add(k_idx)
      continue
  # --- HARD feasibility preprocessing (Unsplittable size) ---
  # Skip if item is unsplittable and:
    #  - Its quantity exceeds every single compatible plant's capacity (cannot fit on any one)
    #  - BUT its quantity is still less than or equal to the aggregate capacity across those plants
    #    (i.e., it could fit only if splitting were allowed).
    # In this case, classify as too_large_for_any_plant to distinguish from pure capacity shortage.
    # If quantity also exceeds the aggregate capacity, we KEEP the item so it becomes 'unallocated'
    # (reason: insufficient_capacity) rather than skipped.
    if qty > 0:
      indiv_exceeds = all(qty > int(plants[p_idx].get("capacity", 0)) for p_idx in cands)
      total_compat_cap = sum(int(plants[p_idx].get("capacity", 0)) for p_idx in cands)
      if indiv_exceeds and qty <= total_compat_cap:
        skipped.append({
          "order": orders[_oi]["order"],
          "order_index": _oi,
          "model": it["model"],
          "submodel": it["submodel"],
          "quantity": qty,
          "reason": "too_large_for_any_plant",
        })
        skipped_indices.add(k_idx)
        continue
    # placed var per item
    placed[k_idx] = model.NewBoolVar(f"placed_k{k_idx}")
    # assignment boolean per compatible plant
    for p_idx in cands:
      assign[p_idx, k_idx] = model.NewBoolVar(f"assign_p{plants[p_idx]['plantid']}_k{k_idx}")

  # All-or-nothing assignment: each item assigned to at most one plant; if
  # assigned, the full quantity is placed. Sum of assigns equals placed.
  # --- HARD CONSTRAINT: Each modeled item may be assigned to AT MOST one plant (no splitting). ---
  # Implemented via: sum_p assign[p,k] == placed[k].
  # placed[k] is a helper Bool ensuring we can refer to selection in the objective.
  for k_idx, (_oi, it) in enumerate(items):
    qty = int(it.get("quantity", 0))
    if k_idx in skipped_indices or qty == 0:
      # Skipped or zero-quantity: no assignment constraints
      continue
    cands = compatible_plants[k_idx]
    assign_vars = [assign[p_idx, k_idx] for p_idx in cands]
    model.Add(sum(assign_vars) == placed[k_idx])

  # Plant capacity constraints: sum of item quantities assigned to the plant
  # cannot exceed plant capacity
  # --- HARD CONSTRAINT: Capacity of each plant not exceeded. ---
  # For each plant p: sum_k qty_k * assign[p,k] <= capacity_p.
  for p_idx, p in enumerate(plants):
    cap = int(p.get("capacity", 0))
    # For each item assigned to this plant, it contributes its full quantity
    terms = []
    for k_idx, (_oi, it) in enumerate(items):
      qty = int(it.get("quantity", 0))
      if qty <= 0:
        continue
      if (p_idx, k_idx) in assign:
        # Linearize weight: qty * assign[p,k]
        terms.append(qty * assign[p_idx, k_idx])
    if terms:
      model.Add(sum(terms) <= cap)


  # --- SOFT OBJECTIVE (Separated additive components) ---
  # We build TWO independent linear component sums (quantity component, due-date urgency component)
  # and apply integer weights afterward. This structurally prepares for potential
  # lexicographic optimization (future: optimize urgency first, then quantity) by
  # giving direct access to each component. Current objective:
  #   Maximize  int_w_quantity * (Σ_k c_qty_k * placed_k) + int_w_due * (Σ_k c_due_k * placed_k)
  # where c_qty_k  = round(scale * norm_qty_k)
  #       c_due_k  = round(scale * norm_urg_k)
  #       int_w_*  = round(weight_precision * w_*)
  # This is algebraically equivalent to previous per-item blended coefficient (up to rounding),
  # but the components remain inspectable and reusable.
  # Reference: cp_model.Maximize linear expression [Docs]
  # https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Maximize

  # Precompute per-item days_until_due and raw urgency values for items that could be placed.
  item_days: List[int] = []
  raw_urgencies: List[float] = []
  max_overdue = 0
  for k_idx, (order_idx, it) in enumerate(items):
    due_str = orders[order_idx].get("dueDate", "")
    try:
      due_date = datetime.fromisoformat(due_str) if due_str else None
    except Exception:
      due_date = None
    if due_date is None:
      d = horizon_days  # treat as far future
    else:
      d = (due_date - current_date).days
    item_days.append(d)
    if d < 0:
      max_overdue = max(max_overdue, abs(d))
  # Compute raw urgencies
  for d in item_days:
    if d < 0:
      # Overdue: >1 range depends on max_overdue
      if max_overdue > 0:
        raw = 1.0 + (abs(d) / max_overdue)  # in (1,2]
      else:
        raw = 1.5  # fallback
    else:
      # Future: linear decay within horizon_days
      future_fraction = min(d, horizon_days) / horizon_days if horizon_days > 0 else 1.0
      raw = max(0.0, 1.0 - future_fraction)  # in [0,1]
    raw_urgencies.append(raw)
  raw_max = max(raw_urgencies) if raw_urgencies else 1.0

  # Quantity normalization baseline
  max_qty = 0
  for _oi, it in items:
    qv = int(it.get("quantity", 0))
    if qv > max_qty:
      max_qty = qv

  qty_component_terms: List[cp_model.LinearExpr] = []  # c_qty_k * placed_k
  due_component_terms: List[cp_model.LinearExpr] = []  # c_due_k * placed_k
  for k_idx, (_oi, it) in enumerate(items):
    if k_idx not in placed:
      continue
    qty = int(it.get("quantity", 0))
    if qty <= 0:
      continue
    norm_qty = (qty / max_qty) if max_qty > 0 else 0.0
    norm_urg = (raw_urgencies[k_idx] / raw_max) if raw_max > 0 else 0.0
    c_qty = int(round(scale * norm_qty))
    c_due = int(round(scale * norm_urg))
    # Clamp each component separately (safeguard)
    if c_qty > 10_000_000:
      c_qty = 10_000_000
    if c_due > 10_000_000:
      c_due = 10_000_000
    qty_component_terms.append(c_qty * placed[k_idx])
    due_component_terms.append(c_due * placed[k_idx])

  # Convert weights to integers with desired precision.
  # NOTE: Keep (weight_precision * scale * max_component_value) within a safe bound.
  int_w_quantity = int(round(w_quantity * weight_precision))
  int_w_due = int(round(w_due * weight_precision))
  if int_w_quantity <= 0 or int_w_due <= 0:
    raise ValueError("Integer-converted weights must be > 0; check w_quantity / w_due and weight_precision")

  # Build component sums (LinearExpr). If empty, skip objective.
  sum_qty_expr = sum(qty_component_terms) if qty_component_terms else None
  sum_due_expr = sum(due_component_terms) if due_component_terms else None
  if sum_qty_expr is not None or sum_due_expr is not None:
    # Treat missing component as 0.
    expr = 0
    if sum_qty_expr is not None and int_w_quantity > 0:
      expr += int_w_quantity * sum_qty_expr
    if sum_due_expr is not None and int_w_due > 0:
      expr += int_w_due * sum_due_expr
    model.Maximize(expr)

  # Solve
  solver = cp_model.CpSolver()
  status = solver.Solve(model)

  def status_to_str(s: object) -> str:
    if s == cp_model.OPTIMAL:
      return "OPTIMAL"
    if s == cp_model.FEASIBLE:
      return "FEASIBLE"
    if s == cp_model.INFEASIBLE:
      return "INFEASIBLE"
    if s == cp_model.MODEL_INVALID:
      return "MODEL_INVALID"
    return "UNKNOWN"

  allocations: List[AllocationRow] = []
  unallocated: List[UnallocatedRow] = []
  # Default component values (evaluated post-solve)
  component_qty_value = 0
  component_due_value = 0
  if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    # Extract placements
    for k_idx, (order_idx, item) in enumerate(items):
      qty = int(item.get("quantity", 0))
      if k_idx in skipped_indices or qty == 0:
        continue
      cands = compatible_plants[k_idx]
      if k_idx in placed and solver.Value(placed[k_idx]) == 1:
        # Find the plant assigned
        assigned_p = None
        for p_idx in cands:
          if solver.Value(assign[p_idx, k_idx]) == 1:
            assigned_p = p_idx
            break
        if assigned_p is not None:
          allocations.append({
            "plantid": plants[assigned_p]["plantid"],
            "order": orders[order_idx]["order"],
            "model": item["model"],
            "submodel": item["submodel"],
            "allocated_qty": qty,
          })
      else:
        # Not placed due to capacity/packing
        unallocated.append({
          "order": orders[order_idx]["order"],
          "order_index": order_idx,
          "model": item["model"],
          "submodel": item["submodel"],
          "requested_qty": qty,
          "reason": "insufficient_capacity",
        })

    # Evaluate component objective contributions for transparency
    try:
      if 'sum_qty_expr' in locals() and sum_qty_expr is not None:
        component_qty_value = solver.Value(sum_qty_expr)
      if 'sum_due_expr' in locals() and sum_due_expr is not None:
        component_due_value = solver.Value(sum_due_expr)
    except Exception:
      pass

  return {
    "summary": {
      "plants_count": len(plants),
      "orders_count": orders_count,
      "unique_models_count": len(unique_models),
      "total_capacity": total_capacity,
      "total_demand": total_demand,
      "capacity_minus_demand": total_capacity - total_demand,
      "skipped_count": len(skipped),
      "skipped_demand": sum(int(s.get("quantity", 0)) for s in skipped),
      "status": status_to_str(status),
      "objective_components": {
        "quantity_component": component_qty_value,
        "due_component": component_due_value,
        "int_w_quantity": int_w_quantity,
        "int_w_due": int_w_due,
        "scale": scale,
        "weight_precision": weight_precision,
      },
    },
    "allocations": allocations,
    "skipped": skipped,
  "unallocated": unallocated,
  }
