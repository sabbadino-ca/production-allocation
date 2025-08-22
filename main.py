from solver import optimize


if __name__ == "__main__":
    # Example with unified item dicts
    raw_items = [
        {"name": "r0", "model": "red",   "item_quantity": 3},
        {"name": "r1", "model": "red",   "item_quantity": 2},
        {"name": "r2", "model": "red",   "item_quantity": 2},
        {"name": "r3", "model": "red",   "item_quantity": 4},
        {"name": "b0", "model": "blue",  "item_quantity": 5},
        {"name": "b1", "model": "blue",  "item_quantity": 3},
        {"name": "b2", "model": "blue",  "item_quantity": 2},
        {"name": "g0", "model": "green", "item_quantity": 1},
        {"name": "g1", "model": "green", "item_quantity": 6},
        {"name": "y0", "model": "yellow","item_quantity": 2},  # disallowed everywhere
    ]
    num_plants = 3
    plant_item_quantity_capacity = 8

    # Per-plant allowed model sets (hard constraints)
    allowed_models_per_plant = [
        {"red", "blue"},      # Plant 0
        {"red", "green"},     # Plant 1
        {"blue", "green"},    # Plant 2
    ]

    res = optimize(
        raw_items,
        num_plants,
        plant_item_quantity_capacity,
        allowed_models_per_plant,
        w_fill=1.0,
        w_group=0.4,
        time_limit_s=5,
        log=False,
    )

    item_lookup = {d["name"]: d for d in raw_items}
    status_by_name = res["assignment_status_by_name"]
    plants = res["plants_to_items"]

    print(f"Solver status: {res['solver_status']} (code={res['solver_status_code']})")
    print(f"Items placed: {res['items_placed']}  |  Total item_quantity placed: {res['total_item_quantity_placed']}  |  Extra plants: {res['extra_plants']}")
    print()
    print("## Plant Allocations (Markdown)")
    for p in sorted(plants.keys()):
        names_in_plant = plants[p]
        print(f"\n### Plant {p}")
        print("| Item | Model | Item Quantity |")
        print("|------|-------|--------------|")
        for nm in names_in_plant:
            info = item_lookup.get(nm, {})
            print(f"| {nm} | {info.get('model','?')} | {info.get('item_quantity','?')} |")

    # Collect unplaced and disallowed
    no_place = [nm for nm, st in status_by_name.items() if st == 'no_place']
    not_allowed = [nm for nm, st in status_by_name.items() if st == 'not_allowed_model']

    if no_place:
        print("\n### Items Not Placed (status=no_place)")
        for nm in no_place:
            info = item_lookup.get(nm, {})
            print(f"- {nm} (model={info.get('model','?')}, item_quantity={info.get('item_quantity','?')})")
    else:
        print("\n### Items Not Placed (status=no_place)\n- _None_")

    if not_allowed:
        print("\n### Items Skipped (status=not_allowed_model)")
        for nm in not_allowed:
            info = item_lookup.get(nm, {})
            print(f"- {nm} (model={info.get('model','?')}, item_quantity={info.get('item_quantity','?')})")
    else:
        print("\n### Items Skipped (status=not_allowed_model)\n- _None_")

    # Optional summary by model
    print("\n### Model Summary")
    print("| Model | Items Placed | Plants Used |")
    print("|-------|--------------|-------------|")
    for model, placed in res["placed_per_model"].items():
        plants_used = res["model_plants_used"].get(model, 0)
        print(f"| {model} | {placed} | {plants_used} |")

    if res["skipped_item_names"]:
        print("\n_Skipped upfront due to no allowed plants:_", ', '.join(res["skipped_item_names"]))
