# --------------------------- Utilities ---------------------------
from typing import Sequence, List, Dict, Any, Callable, Tuple
from collections import defaultdict
from ortools.sat.python import cp_model

def _fractional_knapsack_ub(values: Sequence[int], quantities: Sequence[int], capacity: int) -> float: # type: ignore
    """
    Capacity-aware UB used to normalize additive objectives.
    Supports zero-quantity items:
      - Items with quantity==0 contribute their full value "for free".
      - Positive-quantity items use a fractional-knapsack bound.

    Returns a float upper bound on the maximum achievable sum of 'values'
    subject to 'quantities' and total capacity.
    """
    if capacity < 0 or not values:
        return 0.0

    # Free contribution: quantity == 0
    free = sum(v for v, q in zip(values, quantities) if q == 0 and v > 0)

    # Fractional part: quantity > 0
    pos = [(v, q) for v, q in zip(values, quantities) if q > 0 and v > 0]
    if not pos:
        return float(free)

    # Sort by value/quantity ratio descending
    pos.sort(key=lambda vq: vq[0] / vq[1], reverse=True)

    cap = float(capacity)
    ub = 0.0
    for v, q in pos:
        if cap <= 0:
            break
        take = min(cap, q)
        ub += v * (take / q)
        cap -= take

    return float(free) + ub


def _group_names_by_model_name(indices: List[int], model_names: List[str], names: List[str]) -> Dict[str, List[str]]:
    """Helper for reporting: group item names by their model_name."""
    out = defaultdict(list)
    for i in indices: # type: ignore
        out[model_names[i]].append(names[i])
    return dict(out)


def decode_solution(
    *,
    solver: cp_model.CpSolver,
    status: Any,
    # Dimensions and mappings
    num_items: int,
    num_plants: int,
    kept_items: List[int],
    local_to_orig: Dict[int, int],
    name_to_index: Dict[str, int],
    unique_model_names: List[str],
    model_name_index: Dict[str, int],
    items_of_name: Dict[str, List[int]],
    # Labels and data
    item_names: List[str],
    model_names: List[str],
    item_quantities: List[int],
    plant_names: List[str],
    plants_quantity_capacities: List[int],
    unsupported_set: set,
    unsupported_idx: List[int],
    # Decision variables / expressions
    x: List[List[cp_model.IntVar]],
    z: List[List[cp_model.IntVar]],
    extra_plants_expr: Any,
    soft_shortfall_vars: List[cp_model.IntVar],
    soft_shortfall_pairs: List[Tuple[str, str, cp_model.IntVar]],
    # For additive achievements
    additive_objectives: List[Any],
) -> Dict[str, Any]:
    """
    Decode the CP-SAT solution into human-readable structures and diagnostics.

    Parameters
    ----------
    solver : cp_model.CpSolver
        The CP-SAT solver instance used to solve the model.
    status : int
        The solution status returned by solver.Solve(model).
    num_items : int
        Total number of items (original indexing).
    num_plants : int
        Total number of plants.
    kept_items : List[int]
        Indices of items that were eligible (not globally unsupported).
    local_to_orig : Dict[int, int]
        Map from local kept-item index to original item index.
    name_to_index : Dict[str,int]
        Map from item name to original item index.
    unique_model_names : List[str]
        Unique model names among kept items.
    model_name_index : Dict[str,int]
        Map from model name to compact index.
    items_of_name : Dict[str,List[int]]
        Original indices of items per model name.
    item_names, model_names, item_quantities, plant_names, plants_quantity_capacities :
        Input data arrays.
    unsupported_set : set
        Set of original item indices that are unsupported by any plant.
    unsupported_idx : List[int]
        List of original indices of unsupported items.
    x, z : decision variables
        Assignment variables (x[local_i][p]) and model presence variables (z[ci][p]).
    extra_plants_expr : Any
        Linear expression for extra plants used (sum(z)-sum(u)).
    soft_shortfall_vars, soft_shortfall_pairs :
        Soft shortfall variables and annotated pairs for reporting.
    additive_objectives : List[Any]
        Objective specs (with .name and .values) for achievement reporting.

    Returns
    -------
    Dict[str, Any]
        A dictionary with decoded items, plant summaries, diagnostics, and markdown tables.

    Raises
    ------
    ValueError
        If dimensions are inconsistent.
    """

    def plant_label(p: int) -> str:
        return plant_names[p]

    n = num_items
    P = num_plants

    # assignment_idx[i] = plant index or -1 if not allocated (for kept items only)
    assignment_idx = [-1] * n
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for li in range(len(kept_items)):
            for p in range(P):
                if solver.Value(x[li][p]):
                    assignment_idx[local_to_orig[li]] = p
                    break

    # Human-readable per-item records
    items_by_name: Dict[str, Dict[str, Any]] = {}
    for i in range(n):
        name = item_names[i]
        if i in unsupported_set:
            items_by_name[name] = {"status": "unsupported model_name", "plant": None, "model_name": model_names[i]}
        else:
            p = assignment_idx[i]
            if p >= 0:
                items_by_name[name] = {"status": "allocated", "plant": plant_label(p), "model_name": model_names[i]}
            else:
                items_by_name[name] = {"status": "unallocated", "plant": None, "model_name": model_names[i]}

    # Plants → items (labels)
    plants_to_items: Dict[str, List[str]] = defaultdict(list)
    for i in range(n):
        rec = items_by_name[item_names[i]]
        if rec["status"] == "allocated":
            plants_to_items[rec["plant"]].append(item_names[i])
    plants_to_items = dict(plants_to_items)

    # Plants → model_names (labels), and inverse
    plants_to_model_names: Dict[str, List[str]] = {}
    model_name_to_plants: Dict[str, List[str]] = {fam: [] for fam in unique_model_names}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p in range(P):
            present = []
            for fam in unique_model_names:
                ci = model_name_index[fam]
                if solver.Value(z[ci][p]):
                    present.append(fam)
                    model_name_to_plants[fam].append(plant_label(p))
            if present:
                plants_to_model_names[plant_label(p)] = sorted(present)
    else:
        plants_to_model_names = {}
        model_name_to_plants = {fam: [] for fam in unique_model_names}

    # Tallies
    items_placed = sum(1 for v in items_by_name.values() if v["status"] == "allocated")
    total_quantity_placed = sum(item_quantities[name_to_index[name]]
                                for name, rec in items_by_name.items() if rec["status"] == "allocated")
    used_plants_list = [label for label in plant_names if label in plants_to_items]
    plants_used_val = len(used_plants_list)

    # Diagnostics per model name and soft shortfall totals
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model_names_plants_used: Dict[str, int] = {}
        placed_per_model_name: Dict[str, int] = {}
        for fam in unique_model_names:
            ci = model_name_index[fam]
            model_names_plants_used[fam] = sum(int(solver.Value(z[ci][p])) for p in range(P))
            placed_per_model_name[fam] = sum(1 for i in items_of_name[fam] if items_by_name[item_names[i]]["status"] == "allocated")

        # Evaluate linear expressions directly (supported by OR-Tools)
        extra_plants_val = solver.Value(extra_plants_expr)
        soft_shortfall_total = solver.Value(sum(soft_shortfall_vars)) if soft_shortfall_vars else 0

        # Optional: per-pair shortfalls for inspection/tuning
        soft_shortfall_by_pair = {
            (fam, plant): int(solver.Value(sf)) for (fam, plant, sf) in soft_shortfall_pairs
        }
    else:
        model_names_plants_used = {fam: 0 for fam in unique_model_names}
        placed_per_model_name = {fam: 0 for fam in unique_model_names}
        extra_plants_val = 0
        soft_shortfall_total = 0
        soft_shortfall_by_pair = {}

    # Achieved raw sums for additive objectives (pre-normalization)
    achieved: Dict[str, int] = {}
    for spec in additive_objectives:
        v = spec.values
        achieved[spec.name] = sum(v[name_to_index[name]]
                                  for name, rec in items_by_name.items() if rec["status"] == "allocated")

    # Per-plant tables (Item | Model name | Quantity)
    md_by_plant: Dict[str, str] = {}
    for label in plant_names:
        assigned_names = plants_to_items.get(label, [])
        num_assigned = len(assigned_names)
        total_qty = sum(item_quantities[name_to_index[name]] for name in assigned_names)
        cap = plants_quantity_capacities[plant_names.index(label)]
        header = (
            f"### Plant {label} — allocated items: {num_assigned} | allocated quantity: {total_qty} | "
            f"plant max quantity capacity: {cap} | unused capacity: {cap - total_qty}\n\n| Item | Model name | Quantity |\n|---|---|---|\n"
        )
        rows: List[str] = []
        for name in assigned_names:
            i = name_to_index[name]
            rows.append(f"| {name} | {model_names[i]} | {item_quantities[i]} |")
        if not rows:
            rows.append("| *(none)* | — | — |")
        md_by_plant[label] = header + "\n".join(rows) + "\n"

    # Unallocated (eligible but not assigned) items
    unallocated_items = [name for name, rec in items_by_name.items() if rec["status"] == "unallocated"]
    unalloc_header = "### Unallocated items\n\n| Item | Model name | Quantity |\n|---|---|---|\n"
    unalloc_rows = []
    for name in unallocated_items:
        i = name_to_index[name]
        unalloc_rows.append(f"| {name} | {model_names[i]} | {item_quantities[i]} |")
    if not unalloc_rows:
        unalloc_rows.append("| *(none)* | — | — |")
    unallocated_md = unalloc_header + "\n".join(unalloc_rows) + "\n"

    # Unsupported-model_name items (filtered upfront)
    unsupported_names = [item_names[i] for i in unsupported_idx]
    unsup_header = "### Unsupported model_name items\n\n| Item | Model name |\n|---|---|\n"
    unsup_rows = [f"| {name} | {model_names[name_to_index[name]]} |" for name in unsupported_names]
    if not unsup_rows:
        unsup_rows.append("| *(none)* | — |")
    unsupported_md = unsup_header + "\n".join(unsup_rows) + "\n"

    md_plants_concat = "\n".join(md_by_plant[label] for label in plant_names)
    md_all = md_plants_concat + "\n" + unallocated_md + "\n" + unsupported_md

    return {
        "items_by_name": items_by_name,
        "plants_to_items": plants_to_items,
        "plants_to_model_names": plants_to_model_names,
        "model_name_to_plants": model_name_to_plants,
        "items_placed": items_placed,
        "total_quantity_placed": total_quantity_placed,
        "used_plants_list": used_plants_list,
        "plants_used_val": plants_used_val,
        "extra_plants_val": extra_plants_val,
        "model_names_plants_used": model_names_plants_used,
        "placed_per_model_name": placed_per_model_name,
        "unsupported_names": unsupported_names,
        "unallocated_items": unallocated_items,
        "md_by_plant": md_by_plant,
        "md_plants_concat": md_plants_concat,
        "unallocated_md": unallocated_md,
        "unsupported_md": unsupported_md,
        "md_all": md_all,
        "achieved": achieved,
        "soft_shortfall_total": soft_shortfall_total,
        "soft_shortfall_by_pair": soft_shortfall_by_pair,
    }
