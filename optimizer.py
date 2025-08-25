"""
CP-SAT plant assignment with:
  • Per-plant capacity (by quantity)
  • Model-name compatibility per plant
  • Items can be skipped (optional)
  • Zero-quantity items allowed
  • Weighted + normalized multi-objective scoring:
      - Additive per-item terms (e.g., fill, due_date_boost, quantity)
      - Grouping penalty: discourage splitting a model_name across many plants
      - Plants-used penalty: discourage opening many plants
  • SOFT shortfall-only minimum total quantity per (model_name, plant)
      - Penalty if below threshold; zero penalty once threshold is met
  • HARD minimum total quantity per (model_name, plant) (optional)

    Updates vs prior version
------------------------
1) Output naming: replaced output keys "skipped_items" → **"unsupported_items"** and
   "skipped_items_by_model_name" → **"unsupported_items_by_model_name"**.
   Also return **"unallocated_items"** for items that were eligible but not assigned.
2) Diagnostics: use CpSolver.Value() on linear expressions (supported by OR-Tools) for
   totals like extra_plants and the soft shortfall sum. Keep per-pair shortfalls for tuning.
3) Added 'denom_soft' to objective_breakdown for the soft shortfall term.
"""

from ortools.sat.python import cp_model
from collections import defaultdict
from datatypes import ObjectiveSpec
from utilities import _fractional_knapsack_ub, _group_names_by_model_name
from typing import List, Dict, Iterable, Tuple, Optional, Sequence
from inputvalidations import ObjectiveSpecValidation, validate_input




# --------------------------- Main solver ---------------------------

def optimize_plants_assignment(
    *,
    # --- Items ---
    item_names: List[str],
    model_names: List[str],
    item_quantities: List[int],                     # >= 0 (zero allowed)
    # --- Plants ---
    plant_names: List[str],
    plant_quantity_capacities: List[int],           # > 0 per plant
    allowed_model_names_per_plant: Sequence[Iterable[str]],
    # --- Additive objectives (per-item sums) ---
    additive_objectives: List[ObjectiveSpec],
    # --- Structural weights (linear counts) ---
    w_group: float = 1.0,                           # minimize model_names splitting: Σ z - Σ u
    w_plants: float = 0.0,                          # minimize plants used: Σ y
    # --- HARD minimum total quantity per (name, plant) ---
    min_allowed_qty_of_items_same_model_name_in_a_plant: int = 0,  # 0 disables hard min
    # --- SOFT shortfall-only minimum total quantity per (name, plant) ---
    soft_min_qty_of_items_same_model_name_in_a_plant: int = 0,     # 0 disables soft min
    w_soft_min_qty_of_items_same_model_name_in_a_plant: float = 0.0,  # penalty weight; 0 disables
    # --- Solver controls ---
    time_limit_s: float = 10.0,
    log: bool = False,
) -> Dict:
    """
    Solve a single CP-SAT model that assigns items to plants.

    Hard Constraints
    ----------------
    - Each item assigned to at most one plant.
    - For each plant p: Σ (quantity_i * x[i,p]) ≤ plant_capacity[p].
    - item i can go to plant p only if item's model_name ∈ allowed_model_names[p].
    - Items with model_names unsupported by all plants are filtered "up front".

    Optional Hard Minimum (global)
    ------------------------------
    If min_allowed_qty_of_items_same_model_name_in_a_plant > 0:
      Σ_{i in model name f} quantity_i * x[i,p] ≥ min_allowed * z[f,p]
    This *forbids* running a model_name at a plant in tiny lots.

    Optional Soft Minimum (global, shortfall-only)
    ----------------------------------------------
    If soft_min_qty_of_items_same_model_name_in_a_plant > 0 and its weight > 0:
      shortfall[f,p] ≥ soft_min * z[f,p] - Σ_{i in f} quantity_i * x[i,p]
      shortfall[f,p] ≥ 0
      Objective adds a penalty term: - coef_soft * Σ shortfall[f,p]
    Penalty applies only when *below* the threshold; no reward above it.

    Objective (single scalarized maximize)
    --------------------------------------
    Maximize:
      + Σ_k  sgn_k * (K * w_k / UB_k) * Σ_i v_k[i] * x[i,·]
      - (K * w_group  / extra_plants_max) * (Σ z - Σ u)
      - (K * w_plants / plants_used_max) * (Σ y)
      - (K * w_soft   / denom_soft)      * Σ shortfall[f,p]      (if enabled)

        Returns
    -------
    A dict with:
            - item-level assignments and statuses ("allocated" | "unallocated" | "unsupported model_name")
      - per-plant and per-model_name summaries
      - Markdown tables for quick display
      - diagnostics: achieved additive sums, coefficients, normalizers, solver status
      - **naming note**: 'unsupported_items' = items with model_names unsupported by all plants.
                         'unallocated_items' = eligible items not assigned to any plant.
    """
   
    # ---------- validations start  ----------
    validate_input(
        item_names=item_names,
        model_names=model_names,
        item_quantities=item_quantities,
        plant_names=plant_names,
        plant_quantity_capacities=plant_quantity_capacities,
        allowed_model_names_per_plant=allowed_model_names_per_plant,
        additive_objectives=additive_objectives,
        min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed_qty_of_items_same_model_name_in_a_plant,
        soft_min_qty_of_items_same_model_name_in_a_plant=soft_min_qty_of_items_same_model_name_in_a_plant,
    )
    # ---------- validations end  ----------

    n = len(model_names)
    P = len(plant_quantity_capacities)
    
    # Handy mappers for human-readable output
    def plant_label(p: int) -> str: return plant_names[p]
    name_to_index = {name: i for i, name in enumerate(item_names)}

    # ---------- Allowed model_names per plant ----------
    allowed_sets = [set(s) for s in allowed_model_names_per_plant]
    allowed_any = set().union(*allowed_sets) if allowed_sets else set()

    # ---------- Upfront filter: items whose model_name is unsupported everywhere ----------
    unsupported_idx = [i for i, model_name in enumerate(model_names) if model_name not in allowed_any]
    unsupported_set = set(unsupported_idx)
    kept_items = [i for i in range(n) if i not in unsupported_set]

    # If nothing is eligible, return a consistent empty plan + tables
    if not kept_items:
        items_by_name = {
            item_names[i]: {"status": "unsupported model_name", "plant": None, "model_name": model_names[i]}
            for i in range(n)
        }
        md_by_plant = {}
        for p in range(P):
            label = plant_label(p)
            num_assigned = 0
            total_qty = 0
            cap = plant_quantity_capacities[p]
            md_by_plant[label] = (
                f"### Plant {label} — allocated items: {num_assigned} | allocated quantity: {total_qty} | plant max quantity capacity: {cap} | unused capacity: {cap - total_qty}\n\n| Item | Model name | Quantity |\n|---|---|---|\n| *(none)* | — | — |\n"
            )
        header_uns = "### Unsupported model_names items\n\n| Item | Model name |\n|---|---|\n"
        rows_uns = [f"| {item_names[i]} | {model_names[i]} |" for i in unsupported_idx] or ["| *(none)* | — |"]
        unsupported_md = header_uns + "\n".join(rows_uns) + "\n"
        unalloc_md = "### Unallocated items\n\n| Item | Model name | Quantity |\n|---|---|---|\n| *(none)* | — | — |\n"
        md_concat = "\n".join(md_by_plant[label] for label in plant_names) + "\n" + unalloc_md + "\n" + unsupported_md
        return {
            "items": items_by_name,
            "plants_to_items": {},
            "plants_to_model_names": {},
            "model_name_to_plants": {},
            "items_placed": 0,
            "total_quantity_placed": 0,
            "used_plants": [],
            "plants_used": 0,
            "extra_plants": 0,
            "model_name_plants_used": {},
            "placed_per_model_name": {},
            # naming clarified:
            "unsupported_items": [item_names[i] for i in unsupported_idx],
            "unsupported_items_by_model_name": _group_names_by_model_name(unsupported_idx, model_names, item_names),
            "unallocated_items": [],  # none; all were unsupported
            # Markdown
            "plant_markdown_tables_by_plant": md_by_plant,
            "plant_markdown_tables": "\n".join(md_by_plant[label] for label in plant_names),
            "unallocated_markdown_table": unalloc_md,
            "unsupported_model_name_markdown_table": unsupported_md,
            "markdown_all_tables": md_concat,
            "objective_breakdown": {},
        }

    # ---------- Model-name bookkeeping (kept items only) ----------
    items_of_name: Dict[str, List[int]] = defaultdict(list)
    unique_names, seen = [], set()
    for i in kept_items:
        fam = model_names[i]
        items_of_name[fam].append(i)
        if fam not in seen:
            unique_names.append(fam); seen.add(fam)
    C = len(unique_names)
    model_name_index = {fam: ci for ci, fam in enumerate(unique_names)}

    # Maps between original indices and compact local indices
    orig_to_local = {i: li for li, i in enumerate(kept_items)}
    local_to_orig = {li: i for i, li in orig_to_local.items()}

    # For normalization UBs
    quantities_kept = [item_quantities[i] for i in kept_items]
    total_capacity = sum(plant_quantity_capacities)

    # ---------- Structural normalizers (closed-form) ----------
    # For grouping: extra plants a model name may touch beyond its first
    allowed_plants_per_model_name = {fam: sum(1 for p in range(P) if fam in allowed_sets[p]) for fam in unique_names}
    extra_plants_max = 0
    for fam in unique_names:
        m_ = min(allowed_plants_per_model_name[fam], len(items_of_name[fam]))
        extra_plants_max += max(0, m_ - 1)
    extra_plants_max = max(1, extra_plants_max)  # avoid divide-by-zero

    # For plants used: at most #plants or #items
    plants_used_max = min(P, len(kept_items))

    # ---------- Additive objectives → integer coefficients ----------
    K = 10_000  # global integer scaling for objective coefficients
    additive_terms: List[Tuple[int, List[int]]] = []   # (signed_coef, v_kept[i])
    additive_specs_info = {}

    for spec in additive_objectives:
        if spec.weight <= 0:
            additive_specs_info[spec.name] = {"ub": 0, "weight": spec.weight, "coef": 0, "sense": spec.sense, "used": False}
            continue
        if spec.sense not in ("maximize", "minimize"):
            raise ValueError(f"sense for '{spec.name}' must be 'maximize' or 'minimize'")
        if len(spec.values) != n:
            raise ValueError(f"values length for '{spec.name}' must equal #items")

        # Restrict to kept items
        v_kept = [int(spec.values[i]) for i in kept_items]
        if any(v < 0 for v in v_kept):
            raise ValueError(f"Objective '{spec.name}' has negative values; keep additive values nonnegative.")

        # Capacity-aware UB (fast)
        ub = _fractional_knapsack_ub(v_kept, quantities_kept, total_capacity)
        if ub <= 1e-9:
            additive_specs_info[spec.name] = {"ub": ub, "weight": spec.weight, "coef": 0, "sense": spec.sense, "used": False}
            continue

        # Convert normalized weight to an integer coefficient
        coef = int(round(K * float(spec.weight) / ub)) or 1
        signed_coef = coef if spec.sense == "maximize" else -coef

        additive_terms.append((signed_coef, v_kept))
        additive_specs_info[spec.name] = {"ub": ub, "weight": spec.weight, "coef": signed_coef, "sense": spec.sense, "used": True}

    # --------------------------- Build CP-SAT model ---------------------------

    m = cp_model.CpModel()

    # Decision variables
    x = [[m.NewBoolVar(f"x_i{li}_p{p}") for p in range(P)] for li in range(len(kept_items))]  # item i (local) -> plant p
    z = [[m.NewBoolVar(f"z_f{ci}_p{p}") for p in range(P)] for ci in range(C)]                # model f present at plant p
    u = [m.NewBoolVar(f"u_f{ci}") for ci in range(C)]                                         # model f present anywhere
    y = [m.NewBoolVar(f"y_p{p}") for p in range(P)]                                           # plant p used

    # Each kept item assigned to at most one plant
    for li in range(len(kept_items)):
        m.Add(sum(x[li][p] for p in range(P)) <= 1)

    # Per-plant capacity (sum of item quantities)
    for p in range(P):
        m.Add(sum(item_quantities[local_to_orig[li]] * x[li][p] for li in range(len(kept_items)))
              <= plant_quantity_capacities[p])

    # Link plant usage y[p] <-> assignments x
    for p in range(P):
        for li in range(len(kept_items)):
            m.Add(x[li][p] <= y[p])                         # if an item goes to p, p is used
        m.Add(sum(x[li][p] for li in range(len(kept_items))) >= y[p])  # if p is used, some item must be there

    # Compatibility & presence links (plus optional hard minimum)
    for fam in unique_names:
        ci = model_name_index[fam]
        idxs_local = [orig_to_local[i] for i in items_of_name[fam]]

        for p in range(P):
            if fam not in allowed_sets[p]:
                # Not allowed: kill presence and assignments
                m.Add(z[ci][p] == 0)
                for li in idxs_local:
                    m.Add(x[li][p] == 0)
            else:
                # Assigning any item of model ⇒ presence at plant
                for li in idxs_local:
                    m.Add(x[li][p] <= z[ci][p])

                # Presence ⇒ at least one item (kept for clarity; redundant if hard min > 0)
                m.Add(sum(x[li][p] for li in idxs_local) >= z[ci][p])

                # HARD minimum total quantity per (model, plant)
                if min_allowed_qty_of_items_same_model_name_in_a_plant > 0:
                    m.Add(
                        sum(item_quantities[local_to_orig[li]] * x[li][p] for li in idxs_local)
                        >= min_allowed_qty_of_items_same_model_name_in_a_plant * z[ci][p]
                    )

                # Presence implies global model name-usage switch
                m.Add(z[ci][p] <= u[ci])

        # If model\ used globally, it must appear in at least one plant
        m.Add(sum(z[ci][p] for p in range(P)) >= u[ci])

    # --------------------------- Objective assembly ---------------------------

    # Additive model name: Σ (signed_coef * Σ v[i] * x[i,·])
    additive_expr = 0
    for signed_coef, v_kept in additive_terms:
        additive_expr += signed_coef * sum(
            v_kept[li] * x[li][p] for li in range(len(kept_items)) for p in range(P)
        )

    # Structural terms:
    # - Grouping: extra plants per model = Σ z - Σ u  (minimize)
    # - Plants used: Σ y                                (minimize)
    extra_plants_expr = sum(z[ci][p] for ci in range(C) for p in range(P)) - sum(u[ci] for ci in range(C))
    plants_used_expr  = sum(y[p] for p in range(P))

    # Normalize structural terms to the same K scale
    def _coef(weight: float, denom_posint: int) -> int:
        if weight <= 0: return 0
        c = int(round(K * weight / max(1, denom_posint)))
        return max(1, c)

    c_group  = _coef(w_group,  extra_plants_max)
    c_plants = _coef(w_plants, plants_used_max)

    # SOFT shortfall-only penalty (per allowed (model name , plant))
    soft_shortfall_vars: List[cp_model.IntVar] = []
    soft_shortfall_pairs: List[Tuple[str, str, cp_model.IntVar]] = []  # (model_label, plant_label, var)
    c_soft = 0
    denom_soft: Optional[int] = None

    if soft_min_qty_of_items_same_model_name_in_a_plant > 0 and w_soft_min_qty_of_items_same_model_name_in_a_plant > 0:
        allowed_pairs = [(model_name_index[fam], p)
                         for fam in unique_names for p in range(P)
                         if fam in allowed_sets[p]]
        denom_soft = max(1, soft_min_qty_of_items_same_model_name_in_a_plant * len(allowed_pairs))
        c_soft = _coef(w_soft_min_qty_of_items_same_model_name_in_a_plant, denom_soft)

        for (ci, p) in allowed_pairs:
            fam = unique_names[ci]
            idxs_local = [orig_to_local[i] for i in items_of_name[fam]]

            # shortfall ∈ [0, soft_min] is sufficient (worst case: z=1, achieved=0)
            sf = m.NewIntVar(0, soft_min_qty_of_items_same_model_name_in_a_plant, f"sf_f{ci}_p{p}")

            # shortfall ≥ soft_min * z - Σ qty*x
            m.Add(
                sf >= soft_min_qty_of_items_same_model_name_in_a_plant * z[ci][p]
                     - sum(item_quantities[local_to_orig[li]] * x[li][p] for li in idxs_local)
            )

            soft_shortfall_vars.append(sf)
            soft_shortfall_pairs.append((fam, plant_label(p), sf))

    # Final objective: maximize additive_expr - penalties
    obj = additive_expr - c_group * extra_plants_expr - c_plants * plants_used_expr
    if soft_shortfall_vars and c_soft > 0:
        obj = obj - c_soft * sum(soft_shortfall_vars)
    m.Maximize(obj)

    # --------------------------- Solve ---------------------------

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(time_limit_s)
    s.parameters.log_search_progress = bool(log)
    status = s.Solve(m)

    # --------------------------- Decode solution ---------------------------

    # assignment_idx[i] = plant index or -1 if not allocated (for kept items only)
    assignment_idx = [-1] * n
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for li in range(len(kept_items)):
            for p in range(P):
                if s.Value(x[li][p]):
                    assignment_idx[local_to_orig[li]] = p
                    break

    # Human-readable per-item records
    items_by_name: Dict[str, Dict] = {}
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
    model_name_to_plants: Dict[str, List[str]] = {fam: [] for fam in unique_names}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p in range(P):
            present = []
            for fam in unique_names:
                ci = model_name_index[fam]
                if s.Value(z[ci][p]):
                    present.append(fam)
                    model_name_to_plants[fam].append(plant_label(p))
            if present:
                plants_to_model_names[plant_label(p)] = sorted(present)
    else:
        plants_to_model_names = {}
        model_name_to_plants = {fam: [] for fam in unique_names}

    # Tallies
    items_placed = sum(1 for v in items_by_name.values() if v["status"] == "allocated")
    total_quantity_placed = sum(item_quantities[name_to_index[name]]
                                for name, rec in items_by_name.items() if rec["status"] == "allocated")
    used_plants_list = [label for label in plant_names if label in plants_to_items]
    plants_used_val = len(used_plants_list)

    # Diagnostics per model name and soft shortfall totals
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model_names_plants_used = {}
        placed_per_model_name = {}
        for fam in unique_names:
            ci = model_name_index[fam]
            model_names_plants_used[fam] = sum(int(s.Value(z[ci][p])) for p in range(P))
            placed_per_model_name[fam] = sum(1 for i in items_of_name[fam] if items_by_name[item_names[i]]["status"] == "allocated")

        # Evaluate linear expressions directly (supported by OR-Tools)
        extra_plants_val = s.Value(extra_plants_expr)
        soft_shortfall_total = s.Value(sum(soft_shortfall_vars)) if soft_shortfall_vars else 0

        # Optional: per-pair shortfalls for inspection/tuning
        soft_shortfall_by_pair = {
            (fam, plant): int(s.Value(sf)) for (fam, plant, sf) in soft_shortfall_pairs
        }
    else:
        model_names_plants_used = {fam: 0 for fam in unique_names}
        placed_per_model_name = {fam: 0 for fam in unique_names}
        extra_plants_val = 0
        soft_shortfall_total = 0
        soft_shortfall_by_pair = {}

    # Achieved raw sums for additive objectives (pre-normalization)
    achieved = {}
    for spec in additive_objectives:
        v = spec.values
        achieved[spec.name] = sum(v[name_to_index[name]]
                                  for name, rec in items_by_name.items() if rec["status"] == "allocated")

    # --------------------------- Markdown tables ---------------------------

    # Per-plant tables (Item | Model name | Quantity)
    md_by_plant: Dict[str, str] = {}
    for label in plant_names:
        assigned_names = plants_to_items.get(label, [])
        num_assigned = len(assigned_names)
        total_qty = sum(item_quantities[name_to_index[name]] for name in assigned_names)
        cap = plant_quantity_capacities[plant_names.index(label)]
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

    # --------------------------- Return structured result ---------------------------

    return {
        # Item-level assignments (by item name)
        "items": items_by_name,                                 # {item_name: {"status","plant","model_name"}}
        # Plant/model_name summaries
        "plants_to_items": plants_to_items,                     # {plant_label: [item_name]}
        "plants_to_model_names": plants_to_model_names,         # {plant_label: [model_name]}
        "model_name_to_plants": model_name_to_plants,           # {model_name: [plant_label]}
        # Tallies
        "items_placed": items_placed,
        "total_quantity_placed": total_quantity_placed,
        "used_plants": used_plants_list,
        "plants_used": plants_used_val,
        "extra_plants": extra_plants_val,
        "model_name_plants_used": model_names_plants_used,
        "placed_per_model_name": placed_per_model_name,
        # Upfront unsupported (renamed keys)
        "unsupported_items": unsupported_names,
        "unsupported_items_by_model_name": _group_names_by_model_name(unsupported_idx, model_names, item_names),
        # Eligible but skipped in the solve
        "unallocated_items": unallocated_items,
        # Markdown
        "plant_markdown_tables_by_plant": md_by_plant,
        "plant_markdown_tables": md_plants_concat,
        "unallocated_markdown_table": unallocated_md,
        "unsupported_model_name_markdown_table": unsupported_md,
        "markdown_all_tables": md_all,
        # Diagnostics
        "objective_breakdown": {
            "additive_specs_info": additive_specs_info,
            "achieved_additive_raw": achieved,
            "structural_normalizers": {
                "extra_plants_max": extra_plants_max,
                "plants_used_max": plants_used_max,
                "total_capacity": total_capacity,
            },
            "soft_min_qty": {
                "threshold": soft_min_qty_of_items_same_model_name_in_a_plant,
                "weight": w_soft_min_qty_of_items_same_model_name_in_a_plant,
                "allowed_pairs": sum(1 for fam in unique_names for p in range(P) if fam in allowed_sets[p]),
                "denom_soft": denom_soft,                    # added to aid weight tuning
                "coef": c_soft,
                "total_shortfall": soft_shortfall_total,
                "shortfall_by_pair": soft_shortfall_by_pair,  # {(model name, plant): value}
            },
            "coefficients": {"K": K, "c_group": c_group, "c_plants": c_plants},
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else ("FEASIBLE" if status == cp_model.FEASIBLE else "INFEASIBLE"),
        },
    }
