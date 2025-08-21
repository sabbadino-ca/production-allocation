"""
Production allocation optimization module using Google OR-Tools CP-SAT.

Implements the first hard constraint: items can only be produced on plants that
are allowed to produce their model (allowedModels).

Docs: CpModel.NewIntVar, CpModel.Add
- https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.NewIntVar
- https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
"""
from __future__ import annotations

from typing import Dict, List, Tuple, TypedDict, Literal
from domain_types import Plant, Order, Item
from ortools.sat.python import cp_model

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


def allocate(plants: List[Plant], orders: List[Order]) -> AllocateResult:
  """
  Build a feasibility CP-SAT model that enforces the allowedModels constraint.

  Behavior
  - Creates integer decision variables only for (plant, item) pairs where the
    plant supports the item's model (allowedModels).
  - For each item that has at least one compatible plant, adds a demand
    satisfaction constraint: sum over compatible plants equals requested
    quantity.
  - For items with no compatible plant, skips them (does not add variables nor
    constraints) and records them under the returned "skipped" property.

  Args:
    plants: List of Plant dictionaries (must include 'plantid', 'capacity',
      and 'allowedModels').
    orders: List of Order dictionaries (each containing an 'items' list of
      Item dictionaries with 'model', 'submodel', and 'quantity').

  Returns:
    AllocateResult: Typed mapping containing
      - summary: Aggregated stats and solver status.
      - allocations: Non-zero allocation rows (by plant and item fields).
      - skipped: Items not modeled due to no compatible plant with reason.

  Notes:
    - This model is feasibility-only (no objective). See CpModel.Add and
      CpSolver.Solve in OR-Tools docs for details:
      https://developers.google.com/optimization/reference/python/sat/python/cp_model#CpModel.Add
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

  # Decision variables x[p,k] only for allowed (plant p, item k)
  x: Dict[Tuple[int, int], cp_model.IntVar] = {}

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
    for p_idx in cands:
      upper = qty
      x[p_idx, k_idx] = model.NewIntVar(0, upper, f"x_p{plants[p_idx]['plantid']}_k{k_idx}")

  # Demand satisfaction for each item using only allowed vars
  for k_idx, (_oi, it) in enumerate(items):
    qty = int(it["quantity"])
    cands = compatible_plants[k_idx]
    if not cands:
      # Skipped (or zero-quantity), do not add constraints
      continue
    terms = [x[p_idx, k_idx] for p_idx in cands]
    model.Add(sum(terms) == qty)

  # Solve (no objective: feasibility only)
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
  if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for (p_idx, k_idx), var in x.items():
      val = solver.Value(var)
      if val > 0:
        order_idx, item = items[k_idx]
        allocations.append({
          "plantid": plants[p_idx]["plantid"],
          "order": orders[order_idx]["order"],
          "model": item["model"],
          "submodel": item["submodel"],
          "allocated_qty": int(val),
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
  }
