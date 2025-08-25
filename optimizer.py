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
from utilities import _fractional_knapsack_ub, _group_names_by_model_name, decode_solution
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
    plants_quantity_capacities: List[int],           # > 0 per plant
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
    random_seed: Optional[int] = None,
    num_search_workers: Optional[int] = None
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
        This forbids running a model_name at a plant in tiny lots.

        Optional Soft Minimum (global, shortfall-only)
        ----------------------------------------------
        If soft_min_qty_of_items_same_model_name_in_a_plant > 0 and its weight > 0:
            shortfall[f,p] ≥ soft_min * z[f,p] - Σ_{i in f} quantity_i * x[i,p]
            shortfall[f,p] ≥ 0
            Objective adds a penalty term: - coef_soft * Σ shortfall[f,p]
        Penalty applies only when below the threshold; no reward above it.

        Objective (single scalarized maximize)
        --------------------------------------
        Maximize:
            + Σ_k  sgn_k * (K * w_k / UB_k) * Σ_i v_k[i] * x[i,·]
            - (K * w_group  / extra_plants_max) * (Σ z - Σ u)
            - (K * w_plants / plants_used_max) * (Σ y)
            - (K * w_soft   / denom_soft)      * Σ shortfall[f,p]      (if enabled)

        Solver controls
        ---------------
        - random_seed (Optional[int]): If provided, sets CpSolverParameters.random_seed to make
            the search pseudo-deterministic and reproducible for tests. See CP-SAT parameters
            reference: https://developers.google.com/optimization/reference/python/sat/python/cp_model#cpsolverparameters
        - num_search_workers (Optional[int]): If provided, sets CpSolverParameters.num_search_workers
            to control parallelism. Setting to 1 helps reproducibility; >1 may improve speed.

        Returns
        -------
        dict
                - item-level assignments and statuses ("allocated" | "unallocated" | "unsupported model_name")
                - per-plant and per-model_name summaries
                - Markdown tables for quick display
                - diagnostics: achieved additive sums, coefficients, normalizers, solver status
                - naming note: 'unsupported_items' = items with model_names unsupported by all plants;
                    'unallocated_items' = eligible items not assigned to any plant.

    Raises
    ------
    AssertionError
        If structural validations fail (shapes, duplicates, capacities).
    ValueError
        If objective specs are invalid (e.g., non-integer values or negative additive values),
        or if senses are not one of {"maximize","minimize"}.
    """

    # ---------- validations start  ----------
    validate_input(
        item_names=item_names,
        model_names=model_names,
        item_quantities=item_quantities,
        plant_names=plant_names,
        plant_quantity_capacities=plants_quantity_capacities,
        allowed_model_names_per_plant=allowed_model_names_per_plant,
        additive_objectives=additive_objectives,
        min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed_qty_of_items_same_model_name_in_a_plant,
        soft_min_qty_of_items_same_model_name_in_a_plant=soft_min_qty_of_items_same_model_name_in_a_plant,
    )
    # ---------- validations end  ----------

    n = len(model_names)
    P = len(plants_quantity_capacities)
    
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
            cap = plants_quantity_capacities[p]
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
    total_capacity = sum(plants_quantity_capacities)

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
              <= plants_quantity_capacities[p])

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
    if random_seed is not None:
        s.parameters.random_seed = int(random_seed)
    if num_search_workers is not None:
        s.parameters.num_search_workers = int(num_search_workers)
    status = s.Solve(m)

    # --------------------------- Decode solution ---------------------------
    decoded = decode_solution(
        solver=s,
        status=status,
        num_items=n,
        num_plants=P,
        kept_items=kept_items,
        local_to_orig=local_to_orig,
        name_to_index=name_to_index,
        unique_model_names=unique_names,
        model_name_index=model_name_index,
        items_of_name=items_of_name,
        item_names=item_names,
        model_names=model_names,
        item_quantities=item_quantities,
        plant_names=plant_names,
        plants_quantity_capacities=plants_quantity_capacities,
        unsupported_set=unsupported_set,
        unsupported_idx=unsupported_idx,
        x=x,
        z=z,
        extra_plants_expr=extra_plants_expr,
        soft_shortfall_vars=soft_shortfall_vars,
        soft_shortfall_pairs=soft_shortfall_pairs,
        additive_objectives=additive_objectives,
    )

    # --------------------------- Return structured result ---------------------------

    return {
        # Item-level assignments (by item name)
        "items": decoded["items_by_name"],                      # {item_name: {"status","plant","model_name"}}
        # Plant/model_name summaries
        "plants_to_items": decoded["plants_to_items"],
        "plants_to_model_names": decoded["plants_to_model_names"],
        "model_name_to_plants": decoded["model_name_to_plants"],
        # Tallies
        "items_placed": decoded["items_placed"],
        "total_quantity_placed": decoded["total_quantity_placed"],
        "used_plants": decoded["used_plants_list"],
        "plants_used": decoded["plants_used_val"],
        "extra_plants": decoded["extra_plants_val"],
        "model_name_plants_used": decoded["model_names_plants_used"],
        "placed_per_model_name": decoded["placed_per_model_name"],
        # Upfront unsupported (renamed keys)
        "unsupported_items": decoded["unsupported_names"],
        "unsupported_items_by_model_name": _group_names_by_model_name(unsupported_idx, model_names, item_names),
        # Eligible but skipped in the solve
        "unallocated_items": decoded["unallocated_items"],
        # Markdown
        "plant_markdown_tables_by_plant": decoded["md_by_plant"],
        "plant_markdown_tables": decoded["md_plants_concat"],
        "unallocated_markdown_table": decoded["unallocated_md"],
        "unsupported_model_name_markdown_table": decoded["unsupported_md"],
        "markdown_all_tables": decoded["md_all"],
        # Diagnostics
        "objective_breakdown": {
            "additive_specs_info": additive_specs_info,
            "achieved_additive_raw": decoded["achieved"],
            "structural_normalizers": {
                "extra_plants_max": extra_plants_max,
                "plants_used_max": plants_used_max,
                "total_capacity": total_capacity,
            },
            "soft_min_qty": {
                "threshold": soft_min_qty_of_items_same_model_name_in_a_plant,
                "weight": w_soft_min_qty_of_items_same_model_name_in_a_plant,
                "allowed_pairs": sum(1 for fam in unique_names for p in range(P) if fam in allowed_sets[p]),
                "denom_soft": denom_soft,
                "coef": c_soft,
                "total_shortfall": decoded["soft_shortfall_total"],
                "shortfall_by_pair": decoded["soft_shortfall_by_pair"],
            },
            "coefficients": {"K": K, "c_group": c_group, "c_plants": c_plants},
            "status": s.StatusName(status),
        },
    }
