from ortools.sat.python import cp_model
from collections import defaultdict
from typing import List, Dict, Any
from solver_utils import group_by_model_names

def optimize(
    items,
    num_plants,
    plant_item_quantity_capacity,
    allowed_models_per_plant,
    w_fill: float = 1.0,
    w_group: float = 1.0,
    time_limit_s: float = 10.0,
    log: bool = False,
):
    """Solve a model-grouped plant allocation problem with per-plant allowed model sets.

    Returns dict enriched with assignment, status mapping, and solver status fields.
    """
    models = []
    item_quantities = []
    names = []
    for i, it in enumerate(items):
        if 'model' not in it or 'item_quantity' not in it:
            raise ValueError(f"Item {i} missing required 'model' or 'item_quantity'")
        models.append(it['model'])
        item_quantities.append(it['item_quantity'])
        names.append(it.get('name', f"item_{i}"))
    n = len(models)
    if n == 0:
        return {
            "assignment_by_name": {},
            "assignment_status_by_name": {},
            "plants_to_items": {},
            "items_placed": 0,
            "total_weight_placed": 0,
            "model_plants_used": {},
            "placed_per_model": {},
            "extra_plants": 0,
            "skipped_item_names": [],
            "skipped_items_by_model": {},
            "item_names": [],
            "solver_status_code": None,
            "solver_status": "NOT_SOLVED",
            "optimal": False,
            "feasible": False,
        }
    if num_plants <= 0 or plant_item_quantity_capacity <= 0:
        raise ValueError("num_plants and plant_item_quantity_capacity must be >= 1")
    if any(q <= 0 for q in item_quantities):
        raise ValueError("All item quantities must be strictly positive integers")
    if not isinstance(allowed_models_per_plant, (list, tuple)) or len(allowed_models_per_plant) != num_plants:
        raise ValueError("allowed_models_per_plant must be a list (len=num_plants) of iterables of model labels")

    allowed_sets = [set(s) for s in allowed_models_per_plant]
    allowed_any = set().union(*allowed_sets) if allowed_sets else set()

    skipped_items = [i for i, m in enumerate(models) if m not in allowed_any]
    kept_items = [i for i in range(n) if i not in set(skipped_items)]

    items_of_model = defaultdict(list)
    unique_models = []
    seen = set()
    for i in kept_items:
        m = models[i]
        items_of_model[m].append(i)
        if m not in seen:
            unique_models.append(m)
            seen.add(m)

    if not kept_items:
        assignment_by_name = {names[i]: (-2 if i in set(skipped_items) else -1) for i in range(n)}
        skipped_names = [names[i] for i in skipped_items]
        skipped_by_model_names = group_by_model_names(skipped_items, models, names)
        return {
            "assignment_by_name": assignment_by_name,
            "assignment_status_by_name": {n: ("not_allowed_model" if v == -2 else ("no_place" if v == -1 else "assigned")) for n, v in assignment_by_name.items()},
            "plants_to_items": {},
            "items_placed": 0,
            "total_weight_placed": 0,
            "model_plants_used": {},
            "placed_per_model": {},
            "extra_plants": 0,
            "skipped_item_names": skipped_names,
            "skipped_items_by_model": skipped_by_model_names,
            "item_names": names,
            "solver_status_code": None,
            "solver_status": "NOT_SOLVED",
            "optimal": False,
            "feasible": False,
        }


    orig_to_local = {i: li for li, i in enumerate(kept_items)}
    local_to_orig = {li: i for i, li in orig_to_local.items()}
    P = num_plants
    M = len(unique_models)
    allowed_plants_per_model = {
        m: sum(1 for p in range(P) if m in allowed_sets[p]) for m in unique_models
    }
    q_min_kept = min(item_quantities[i] for i in kept_items)
    A_max = min(len(kept_items), (P * plant_item_quantity_capacity) // q_min_kept)
    A_max = max(1, A_max)
    extra_plants_max = 0
    for m in unique_models:
        mm = min(allowed_plants_per_model[m], len(items_of_model[m]))
        extra_plants_max += max(0, mm - 1)
    extra_plants_max = max(1, extra_plants_max)

    model = cp_model.CpModel()
    x = [[model.NewBoolVar(f"x_i{li}_p{p}") for p in range(P)] for li in range(len(kept_items))]
    z = [[model.NewBoolVar(f"z_m{mi}_p{p}") for p in range(P)] for mi in range(M)]
    u = [model.NewBoolVar(f"u_m{mi}") for mi in range(M)]

    for li, _ in enumerate(kept_items):
        model.Add(sum(x[li][p] for p in range(P)) <= 1)
    for p in range(P):
        model.Add(sum(item_quantities[local_to_orig[li]] * x[li][p] for li in range(len(kept_items))) <= plant_item_quantity_capacity)

    model_index = {m: mi for mi, m in enumerate(unique_models)}
    for m in unique_models:
        mi = model_index[m]
        idxs_local = [orig_to_local[i] for i in items_of_model[m]]
        for p in range(P):
            if m not in allowed_sets[p]:
                model.Add(z[mi][p] == 0)
                for li in idxs_local:
                    model.Add(x[li][p] == 0)
            else:
                for li in idxs_local:
                    model.Add(x[li][p] <= z[mi][p])
                model.Add(sum(x[li][p] for li in idxs_local) >= z[mi][p])
                model.Add(z[mi][p] <= u[mi])
        model.Add(sum(z[mi][p] for p in range(P)) >= u[mi])

    total_assigned = sum(x[li][p] for li in range(len(kept_items)) for p in range(P))
    extra_plants = sum(z[mi][p] for mi in range(M) for p in range(P)) - sum(u[mi] for mi in range(M))
    K = 10_000
    coef_fill = int(round(K * float(w_fill) / A_max)) if w_fill > 0 else 0
    coef_group = int(round(K * float(w_group) / extra_plants_max)) if w_group > 0 else 0
    if w_fill > 0 and coef_fill == 0:
        coef_fill = 1
    if w_group > 0 and coef_group == 0:
        coef_group = 1
    model.Maximize(coef_fill * total_assigned - coef_group * extra_plants)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.log_search_progress = bool(log)
    status = solver.Solve(model)
    if status == cp_model.OPTIMAL:
        status_str = "OPTIMAL"
    elif status == cp_model.FEASIBLE:
        status_str = "FEASIBLE"
    elif status == cp_model.INFEASIBLE:
        status_str = "INFEASIBLE"
    elif status == cp_model.MODEL_INVALID:
        status_str = "MODEL_INVALID"
    else:
        status_str = "UNKNOWN"

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignment_by_name = {names[i]: (-2 if i in set(skipped_items) else -1) for i in range(n)}
        skipped_names = [names[i] for i in skipped_items]
        skipped_by_model_names = group_by_model_names(skipped_items, models, names)
        return {
            "assignment_by_name": assignment_by_name,
            "assignment_status_by_name": {nm: ("not_allowed_model" if v == -2 else ("no_place" if v == -1 else "assigned")) for nm, v in assignment_by_name.items()},
            "plants_to_items": {},
            "items_placed": 0,
            "total_weight_placed": 0,
            "model_plants_used": {},
            "placed_per_model": {},
            "extra_plants": 0,
            "skipped_item_names": skipped_names,
            "skipped_items_by_model": skipped_by_model_names,
            "item_names": names,
            "solver_status_code": status,
            "solver_status": status_str,
            "optimal": status == cp_model.OPTIMAL,
            "feasible": status in (cp_model.OPTIMAL, cp_model.FEASIBLE),
        }

    assignment = [-1] * n
    for i in skipped_items:
        assignment[i] = -2
    for li in range(len(kept_items)):
        for p in range(P):
            if solver.Value(x[li][p]):
                assignment[local_to_orig[li]] = p
                break
    plants_to_items_names = defaultdict(list)
    for idx, p in enumerate(assignment):
        if p >= 0:
            plants_to_items_names[p].append(names[idx])
    plants_to_items_names = dict(plants_to_items_names)

    items_placed = sum(1 for a in assignment if a >= 0)
    total_item_quantity_placed = sum(item_quantities[i] for i in range(n) if assignment[i] >= 0)

    model_plants_used = {}
    placed_per_model = {}
    for m in unique_models:
        mi = model_index[m]
        model_plants_used[m] = sum(int(solver.Value(z[mi][p])) for p in range(P))
        placed_per_model[m] = sum(1 for i in items_of_model[m] if assignment[i] >= 0)

    assignment_by_name = {names[i]: assignment[i] for i in range(n)}
    skipped_names = [names[i] for i in skipped_items]
    skipped_by_model_names = group_by_model_names(skipped_items, models, names)

    return {
        "assignment_by_name": assignment_by_name,
        "assignment_status_by_name": {nm: ("not_allowed_model" if v == -2 else ("no_place" if v == -1 else "assigned")) for nm, v in assignment_by_name.items()},
        "plants_to_items": plants_to_items_names,
        "items_placed": items_placed,
        "total_item_quantity_placed": total_item_quantity_placed,
        "model_plants_used": model_plants_used,
        "placed_per_model": placed_per_model,
        "extra_plants": int(solver.Value(extra_plants)),
        "skipped_item_names": skipped_names,
        "skipped_items_by_model": skipped_by_model_names,
        "item_names": names,
        "solver_status_code": status,
        "solver_status": status_str,
        "optimal": status == cp_model.OPTIMAL,
        "feasible": status in (cp_model.OPTIMAL, cp_model.FEASIBLE),
    }




__all__ = ["optimize"]
