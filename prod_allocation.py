"""Production allocation optimization (unsplittable items) using Google OR-Tools CP-SAT.

Overview
========
We allocate whole (unsplittable) item demands to a *single* plant each (0/1
placement per item). If an item cannot fit on any single compatible plant, we
either skip it (classification reason) or let it remain unallocated, depending
on feasibility logic described below.

Hard Constraints
----------------
1. Compatibility: An item may only be produced at plants whose
   ``allowedModels`` set contains its model.
2. Plant capacity: Sum of allocated quantities at a plant cannot exceed its
   capacity.
3. Unsplittable items: Each item is an atomic chunk; partial allocation across
   multiple plants is **not** allowed (design choice). This reduces model size
   but can lead to unallocated items that would otherwise fit if splitting
   were permitted.

Objective (current weighted sum)
--------------------------------
Maximize: (w_quantity * normalized_quantity_component) +
          (w_due * normalized_due_date_urgency_component)

Due-date urgency favors (a) overdue items first, (b) items closer to their due
date within a configurable future horizon. Overdue items are mapped into a
range higher than any future item before normalization.

Result Classification Semantics
--------------------------------
* ``allocations``: Items placed on a plant (full quantity).
* ``skipped``: Items **not modeled** at all (no decision vars) for structural
  reasons that make them impossible to allocate under current rules:
    - ``no_compatible_plant``: No plant can produce the model.
    - ``too_large_for_any_plant``: Quantity exceeds each compatible plant's
      individual capacity, while *aggregate* compatible capacity would have
      sufficed only if splitting were allowed.
  Skipped demand is *not* considered in the solver objective because those
  items are absent from the model.
* ``unallocated``: Items that *were* modeled (had at least one compatible
  plant and fit in at least one plant individually) but ultimately were not
  placed due to competition for limited capacity (currently reason:
  ``insufficient_capacity``). They appear in the objective (via their potential
  placement variable) but ended up with value 0.

Weights & Scaling Guidelines
----------------------------
The code requires explicit positive weights: ``w_quantity`` and ``w_due``. The
previous doc wording implying defaults is superseded—if a weight is missing or
non-positive a ``ValueError`` is raised. Typical starting values: ``w_quantity
= 5.0``, ``w_due = 1.0``.

Key configuration fields:
* ``w_quantity`` (float > 0): Relative emphasis on quantity component.
* ``w_due`` (float > 0): Relative emphasis on urgency component.
* ``horizon_days`` (int >= 1, default 30): Future decay window. Items further
  than this horizon contribute zero future urgency (pre-normalization).
* ``scale`` (int, default 1000): Multiplies normalized components before
  converting to integers. Larger improves resolution but increases objective
  coefficients.
* ``weight_precision`` (int, default 1): Multiplies raw weights before integer
  rounding (use to preserve fractional weight distinctions).

Coefficient Safety: Keep the product
``int_w * scale * max(normalized_component_sum)`` comfortably below ~1e7–1e8 to
avoid very large integers that can slow propagation or cause memory bloat in
CP-SAT (general guidance: prefer *moderate* magnitudes). This module clamps
individual per-item component contributions at 10,000,000 as a guardrail.

Relevant OR-Tools API References
--------------------------------
* Bool / Int var creation: https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.NewBoolVar
* Add linear constraints: https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
* Conditional enforcement (reification): https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
* Objective definition (maximize): https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Maximize

Future Extensions (not yet implemented)
---------------------------------------
* Optional splittable mode (introducing integer quantity vars per plant/item)
* Lexicographic optimization (optimize urgency, then quantity)
* Secondary fairness or model-diversity objectives.
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from domain_types import Plant, Order, Item
from allocation_types import AllocationRow, SkippedRow, Summary, AllocateResult, UnallocatedRow, WeightsConfig
from ortools.sat.python import cp_model
from datetime import datetime
from input_Validations import validate_input_data

def compute_item_urgencies(
  items: List[Tuple[int, Item]],
  orders: List[Order],
  current_date: datetime,
  horizon_days: int,
) -> Tuple[List[int], List[float], float, int]:
  """Compute per-item due-date related urgency scores.

  This pure helper isolates the transformation from raw due dates to
  normalized urgency components so it can be unit-tested independently
  (no dependency on the CP-SAT model).  It replicates the existing
  behavior inside ``allocate`` without changing semantics.

  Logic (mirrors in-line code it replaces):
  - For each item, parse the parent order's ``dueDate`` (ISO format).
  - Compute days until due: (due_date - current_date).days.  Missing or
    invalid dates are treated as far future (``horizon_days``) matching
    previous implementation.
  - Raw urgency heuristic:
      * Future items: linear decay from 1.0 (due now) down to 0.0 at
        horizon boundary: raw = 1 - min(d, horizon)/horizon.
      * Overdue items: scale into (1, 2] range relative to the maximum
        overdue magnitude in the dataset; fallback 1.5 if all share
        identical current/overdue day (max_overdue == 0).
  - ``raw_max`` captures the maximum raw urgency for normalization.

  Returns:
    item_days: List[int] days until due (negative if overdue).
    raw_urgencies: List[float] raw (unnormalized) urgency scores.
    raw_max: float max(raw_urgencies) or 1.0 safety baseline.
    max_overdue: int maximum absolute overdue days encountered.

  Notes:
    Keeping this deterministic ensures that objective coefficient
    scaling in ``allocate`` remains unchanged.
  """
  if horizon_days < 1:
    raise ValueError("horizon_days must be >= 1 (use at least a 1-day horizon)")

  item_days: List[int] = []
  raw_urgencies: List[float] = []
  max_overdue = 0

  # First pass: compute day offsets & track max overdue magnitude
  for order_idx, item in items:
    due_str = orders[order_idx].get("dueDate", "")
    try:
      due_date = datetime.fromisoformat(due_str) if due_str else None
    except Exception:  # pragma: no cover - defensive
      due_date = None
    if due_date is None:
      d = horizon_days  # treat missing/invalid as far future
    else:
      d = (due_date - current_date).days
    item_days.append(d)
    if d < 0:
      if abs(d) > max_overdue:
        max_overdue = abs(d)

  # Second pass: map to raw urgency values
  for d in item_days:
    if d < 0:  # overdue
      if max_overdue > 0:
        raw = 1.0 + (abs(d) / max_overdue)  # in (1,2]
      else:
        raw = 1.5  # fallback consistent with original logic
    else:
      future_fraction = min(d, horizon_days) / horizon_days if horizon_days > 0 else 1.0
      raw = max(0.0, 1.0 - future_fraction)  # in [0,1]
    raw_urgencies.append(raw)

  raw_max = max(raw_urgencies) if raw_urgencies else 1.0
  return item_days, raw_urgencies, raw_max, max_overdue


DEFAULT_HORIZON_DAYS: int = 30  # Single source of truth for horizon default


def allocate(
  plants: List[Plant],
  orders: List[Order],
  current_date: datetime,
  weights: WeightsConfig,
) -> AllocateResult:
  """
  Build and solve a CP-SAT model for unsplittable item allocation.

  The model is *always feasible* because items that cannot be placed within
  capacity limits simply remain unallocated (their decision variable resolves
  to 0). Only structural data errors (caught by validation) or an invalid
  model definition could cause solver statuses other than FEASIBLE/OPTIMAL.

  Core Mechanics
  --------------
  * Variable creation only for (plant, item) pairs where the plant can make
    the item's model.
  * Each item has a binary ``placed`` variable; compatible (plant,item) pairs
    have binary assignment variables. Channeling ensures at most one plant is
    chosen if an item is placed.
  * Plant capacity constraints sum full item quantities of assigned items.
  * Unsplittable assumption: An item's quantity cannot be divided across
    multiple plants.

  Skip vs Unallocated Criteria
  ----------------------------
  * Skip (no modeling): No compatible plant OR quantity exceeds every single
    compatible plant while aggregate capacity across those plants is large
    enough only if splitting were allowed (``too_large_for_any_plant``).
  * Unallocated (modeled but value 0): Had at least one compatible plant and
    fits in at least one plant individually, but not chosen due to capacity
    competition (``insufficient_capacity``).

  Weight Configuration (explicitly required)
  ------------------------------------------
  weights["w_quantity"] > 0 and weights["w_due"] > 0 must be supplied.
  Recommended starting values: w_quantity=5.0, w_due=1.0.
  Other fields (optional with defaults):
    - horizon_days (int >=1, default DEFAULT_HORIZON_DAYS)
    - scale (int, default 1000)
    - weight_precision (int, default 1)

  Coefficient Formula
  -------------------
  Per item components:
    c_qty_k = round(scale * (qty_k / max_qty))
    c_due_k = round(scale * normalized_urgency_k)
  Objective: Maximize int(w_quantity * weight_precision)*Σ c_qty_k*placed_k
                       + int(w_due * weight_precision)*Σ c_due_k*placed_k
  Guardrails: Individual component contributions clamped at 10,000,000.

  Args:
    plants: List of Plant dicts containing at least 'plantid', 'capacity', 'allowedModels'.
    orders: List of Order dicts; each has an 'items' list of item dicts with
            'model', 'submodel', 'modelFamily', 'quantity'.
    current_date: Datetime used as reference for due-date urgency.
    weights: Mapping providing required positive weights and optional scaling parameters.

  Returns:
    AllocateResult dict with keys:
      summary: Aggregate counts + objective diagnostics (components + bound metrics).
      allocations: Successful (plant,item) placements.
      skipped: Items omitted from the model (see reasons above).
      unallocated: Modeled items left unassigned for lack of capacity.

  Objective Bound Metrics
  -----------------------
  Provided when FEASIBLE/OPTIMAL: solver objective value, best bound, absolute
  and relative gaps. For maximization: true optimum <= best_objective_bound.

  Notes
  -----
  * Capacity infeasibility does not produce an INFEASIBLE status; it results in
    unallocated items.
  * For OR-Tools reference see: CpModel.Add, CpModel.Maximize, CpSolver.Solve.
  """
  # Validate structural input data and provided weights/settings mapping.
  # validate_input_data now accepts either raw settings dict or WeightsConfig.
  validate_input_data(plants, orders, weights)

  # Extract weights with defaults (0.0 forces explicit user specification)
  w_quantity = float(weights.get("w_quantity", 0.0))
  w_due = float(weights.get("w_due", 0.0))
  
  horizon_days = int(weights.get("horizon_days", DEFAULT_HORIZON_DAYS))
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
  # assigned, the full quantity is placed.
  # --- HARD CONSTRAINT (Reified channeling): ---
  #  placed[k] == 1  => exactly one assign var is 1 (sum == 1)
  #  placed[k] == 0  => all assign vars are 0 (sum == 0)
  # We encode with two conditional constraints plus an unconditional
  # AddAtMostOne(assign_vars) to improve propagation before placed[k] is fixed.
  # This is logically equivalent to: sum(assign_vars) == placed[k], but can
  # strengthen early pruning in the search. (See cp_model.Add / OnlyEnforceIf docs)
  for k_idx, (_oi, it) in enumerate(items):
    qty = int(it.get("quantity", 0))
    if k_idx in skipped_indices or qty == 0:
      # Skipped or zero-quantity: no assignment constraints
      continue
    cands = compatible_plants[k_idx]
    assign_vars = [assign[p_idx, k_idx] for p_idx in cands]
    if len(assign_vars) == 1:
      # Single candidate plant: direct channeling
      model.Add(assign_vars[0] == placed[k_idx])
    else:
      model.AddAtMostOne(assign_vars)
      sum_expr = sum(assign_vars)
      model.Add(sum_expr == 1).OnlyEnforceIf(placed[k_idx])
      model.Add(sum_expr == 0).OnlyEnforceIf(placed[k_idx].Not())

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

  # Precompute due-date based urgency metrics (factored helper for testability)
  item_days, raw_urgencies, raw_max, max_overdue = compute_item_urgencies(
    items=items,
    orders=orders,
    current_date=current_date,
    horizon_days=horizon_days,
  )

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

  allocations: List[AllocationRow] = []
  unallocated: List[UnallocatedRow] = []
  # Track per-plant used capacity as we extract allocations (same order as plants list)
  plant_used_capacity: List[int] = [0 for _ in plants]
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
          plant_used_capacity[assigned_p] += qty
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

  # Objective bound / gap metrics (only meaningful if a feasible solution and objective present)
  objective_value = None
  best_objective_bound = None
  gap_abs = None
  gap_rel = None
  if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    try:
      objective_value = solver.ObjectiveValue()
      best_objective_bound = solver.BestObjectiveBound()
      if objective_value is not None and best_objective_bound is not None:
        # Maximization model: bound >= objective_value
        gap_abs_calc = max(0.0, best_objective_bound - objective_value)
        gap_abs = gap_abs_calc
        denom = max(1.0, abs(objective_value))
        gap_rel = gap_abs_calc / denom
    except Exception:
      pass

  result: AllocateResult = {
    "summary": {
      "plants_count": len(plants),
      "orders_count": orders_count,
      "unique_models_count": len(unique_models),
      "total_capacity": total_capacity,
      "total_demand": total_demand,
      "capacity_minus_demand": total_capacity - total_demand,
      "skipped_count": len(skipped),
      "skipped_demand": sum(int(s.get("quantity", 0)) for s in skipped),
  "status": solver.StatusName(),
      # Allocation outcome KPIs
      "total_allocated_quantity": sum(a["allocated_qty"] for a in allocations),
      "allocated_ratio": (sum(a["allocated_qty"] for a in allocations) / total_demand) if total_demand > 0 else 0.0,
      # Per-plant utilization diagnostics
      "plant_utilization": [
        {
          "plantid": plants[i]["plantid"],
          "capacity": int(plants[i].get("capacity", 0)),
          "used_capacity": plant_used_capacity[i],
          "utilization_pct": (plant_used_capacity[i] / int(plants[i].get("capacity", 1))) * 100.0 if int(plants[i].get("capacity", 0)) > 0 else 0.0,
        }
        for i in range(len(plants))
      ],
      "objective_components": {
        "quantity_component": component_qty_value,
        "due_component": component_due_value,
        "int_w_quantity": int_w_quantity,
        "int_w_due": int_w_due,
        "scale": scale,
        "weight_precision": weight_precision,
      },
      "objective_bound_metrics": {
        "objective_value": objective_value,
        "best_objective_bound": best_objective_bound,
        "gap_abs": gap_abs,
        "gap_rel": gap_rel,
      },
      # Urgency diagnostics (raw per-item data for transparency)
      "diagnostics": {
        "item_days": item_days,
        "normalized_urgencies": [(raw_urgencies[i] / raw_max) if raw_max > 0 else 0.0 for i in range(len(raw_urgencies))],
        "max_overdue_days": max_overdue,
        "horizon_days": horizon_days,
      },
    },
    "allocations": allocations,
    "skipped": skipped,
    "unallocated": unallocated,
  }
  return result
