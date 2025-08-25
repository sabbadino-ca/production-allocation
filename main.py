


# --------------------------- Example usage ---------------------------
from datatypes import ObjectiveSpec
from optimizer import optimize_plants_assignment  # Add this import if the function is defined in optimize.py
from pathlib import Path
import argparse
from input_loader import load_plants_arrays, load_items_arrays

if __name__ == "__main__":
    # Require plants and items file paths as input parameters
    parser = argparse.ArgumentParser(description="Run production allocation example")
    parser.add_argument("--plants-file", required=True, help="Path to plants JSON file")
    parser.add_argument("--items-file", required=True, help="Path to items JSON file")
    args = parser.parse_args()

    plant_names, plant_quantity_capacities, allowed_model_names_per_plant = load_plants_arrays(args.plants_file)
    item_names, model_names, quantities, due_date_boosts = load_items_arrays(args.items_file)

    # Per-item additive objectives (family of sums)
    specs = [
        ObjectiveSpec(name="fill",            values=[1]*len(item_names), sense="maximize", weight=5.0),
        ObjectiveSpec(name="due_date_boost",  values=due_date_boosts[:],  sense="maximize", weight=0.8),
        ObjectiveSpec(name="quantity",        values=quantities[:],        sense="maximize", weight=0.2),
    ]

    # --- Run A: SOFT minimum only (penalize below 6; no reward above) ---
    res_soft = optimize_plants_assignment(
        item_names=item_names,
        model_names =model_names,
        item_quantities=quantities,
        plant_names=plant_names,
        plants_quantity_capacities=plant_quantity_capacities,
        allowed_model_names_per_plant=allowed_model_names_per_plant,
        additive_objectives=specs,
        w_group=1.2,   # grouping penalty on
        w_plants=1.0,  # prefer fewer plants
        min_allowed_qty_of_items_same_model_name_in_a_plant=0,  # HARD min OFF
        soft_min_qty_of_items_same_model_name_in_a_plant=6,     # SOFT min = 6
        w_soft_min_qty_of_items_same_model_name_in_a_plant=.1, # give the penalty meaningful weight
        time_limit_s=5,
        log=False
    )
    print("#=== SOFT MIN ONLY ===")
    print(f"solver status: {res_soft['objective_breakdown']['status']}")
    print(res_soft["markdown_all_tables"])

    # --- Run B: HARD minimum only (must reach 6 per model name ×plant to run there) ---
    # res_hard = optimize_plants_assignment(
    #     item_names=item_names,
    #     model_names=model_names,
    #     item_quantities=quantities,
    #     plant_names=plant_names,
    #     plant_quantity_capacities=plant_caps,
    #     allowed_model_names_per_plant=allowed_model_names_per_plant,
    #     additive_objectives=specs,
    #     w_group=1.2,
    #     w_plants=1.0,
    #     min_allowed_qty_of_items_same_model_name_in_a_plant=6,   # HARD min ON
    #     soft_min_qty_of_items_same_model_name_in_a_plant=0,      # SOFT min OFF
    #     time_limit_s=5,
    #     log=False
    # )
    # print("\n#=== HARD MIN ONLY ===")
    # print(res_hard["markdown_all_tables"])
