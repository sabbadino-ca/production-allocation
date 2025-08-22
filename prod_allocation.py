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
from allocation_types import AllocationRow, SkippedRow, Summary, AllocateResult, UnallocatedRow
from ortools.sat.python import cp_model
from datetime import datetime
from input_Validations import validate_input_data




def allocate(plants: List[Plant], orders: List[Order], current_date: datetime) -> AllocateResult:
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
  # Validate input data first
  validate_input_data(plants, orders)
  
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
    # Skip any item (even zero quantity) with no compatible plant
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


  # Multi-objective: maximize quantity + prioritize earlier due dates
  obj_terms = []
  for k_idx, (order_idx, it) in enumerate(items):
    qty = int(it.get("quantity", 0))
    if k_idx in placed and qty > 0:
      # Base quantity term
      base_weight = qty
      
      # Due date priority weight (earlier dates get higher priority)
      # Use order-level dueDate since items no longer have individual due dates
      due_date_str = orders[order_idx].get("dueDate", "")
      if due_date_str:
        try:
          due_date = datetime.fromisoformat(due_date_str)
          days_until_due = (due_date - current_date).days
          
          if days_until_due < 0:
            # Past due: highest priority (exponentially increasing with overdue days)
            due_date_weight = 10000 + abs(days_until_due) * 100
          else:
            # Future due: higher weight for items due sooner
            due_date_weight = max(1, 1000 - days_until_due)
        except:
          due_date_weight = 1
      else:
        due_date_weight = 1
        
      # Combined objective coefficient
      total_weight = base_weight * due_date_weight
      obj_terms.append(total_weight * placed[k_idx])


  if obj_terms:
    model.Maximize(sum(obj_terms))

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
    },
    "allocations": allocations,
    "skipped": skipped,
  "unallocated": unallocated,
  }
