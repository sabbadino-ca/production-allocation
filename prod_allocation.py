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

from typing import Dict, List, Tuple, TypedDict, Literal
from domain_types import Plant, Order, Item
from ortools.sat.python import cp_model
from datetime import datetime

class AllocationRow(TypedDict):
  """One non-zero allocation row in the result."""
  plantid: int
  order: str
  model: str
  submodel: str
  allocated_qty: int


class SkippedRow(TypedDict):
  """One item that was skipped during modeling and the reason why."""
  order: str
  order_index: int
  model: str
  submodel: str
  quantity: int
  reason: Literal["no_compatible_plant"]


class Summary(TypedDict):
  """Aggregated statistics about the modeled instance and solve status."""
  plants_count: int
  orders_count: int
  unique_models_count: int
  total_capacity: int
  total_demand: int
  capacity_minus_demand: int
  skipped_count: int
  skipped_demand: int
  status: str


class AllocateResult(TypedDict):
  """Result container for allocate()."""
  summary: Summary
  allocations: List[AllocationRow]
  skipped: List[SkippedRow]
  unallocated: List["UnallocatedRow"]


class UnallocatedRow(TypedDict):
  """One item that could not be placed due to capacity or packing limits."""
  order: str
  order_index: int
  model: str
  submodel: str
  requested_qty: int
  reason: Literal["insufficient_capacity"]


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

  # Precompute compatible plants per item
  compatible_plants: List[List[int]] = []
  for _k_idx, (_oi, it) in enumerate(items):
    cands = [p_idx for p_idx, p in enumerate(plants) if plant_can_make(p, it)]
    compatible_plants.append(cands)

  # Create variables only for compatible (plant, item)
  for k_idx, (_oi, it) in enumerate(items):
    qty = int(it.get("quantity", 0))
    cands = compatible_plants[k_idx]
    if not cands and qty > 0:
      skipped.append({
        "order": orders[_oi]["order"],
        "order_index": _oi,
        "model": it["model"],
        "submodel": it["submodel"],
        "quantity": qty,
        "reason": "no_compatible_plant",
      })
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
    cands = compatible_plants[k_idx]
    if not cands or qty == 0:
      # Skipped or zero-quantity: no assignment constraints
      continue
    assign_vars = [assign[p_idx, k_idx] for p_idx in cands]
    # placed[k] exists because we created it above for items with cands
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
      due_date_str = it.get("dueDate", "")
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

  def status_to_str(s: object) -> Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "MODEL_INVALID", "UNKNOWN"]:
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
      cands = compatible_plants[k_idx]
      if not cands or qty == 0:
        continue
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
