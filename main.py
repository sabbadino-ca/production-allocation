"""
Main entry point for production allocation optimization.
Requires two input file paths as command line arguments.
"""
import argparse
from datetime import datetime
from data_loader import load_plants, load_orders, load_settings
from typing import List
from domain_types import Plant, Order
from prod_allocation import allocate
from allocation_types import WeightsConfig

def main():
    parser = argparse.ArgumentParser(description="Production Allocation Optimizer")
    parser.add_argument('--plants', required=True, help='Path to plants info JSON file')
    parser.add_argument('--orders', required=True, help='Path to orders JSON file')
    parser.add_argument('--settings', required=True, help='Path to JSON settings file containing w_quantity and w_due')
    args = parser.parse_args()

    plants: List[Plant] = load_plants(args.plants)
    orders: List[Order] = load_orders(args.orders)

    print(f"Loaded {len(plants)} plants and {len(orders)} orders.")
    current_date = datetime.now()
    settings = load_settings(args.settings)
    weights: WeightsConfig = {
        "w_quantity": float(settings.get("w_quantity", 5.0)),
        "w_due": float(settings.get("w_due", 1.0)),
    }
    print(f"Loaded weights -> w_quantity={weights['w_quantity']}, w_due={weights['w_due']}")
    result = allocate(plants, orders, current_date, weights)
    
    # Print summary
    summary = result.get("summary", {})
    print("\n" + "="*60)
    print("OPTIMIZATION SUMMARY")
    print("="*60)
    print(f"Status: {summary.get('status', 'UNKNOWN')}")
    print(f"Plants: {summary.get('plants_count', 0)}  | Orders: {summary.get('orders_count', 0)}  | Unique Models: {summary.get('unique_models_count', 0)}")
    print(f"Total Capacity: {summary.get('total_capacity', 0)}  | Total Demand: {summary.get('total_demand', 0)}  | Capacity - Demand: {summary.get('capacity_minus_demand', 0)}")
    print(f"Total Input Items: {summary.get('total_input_items', 0)}")
    print(f"Allocated Items: {summary.get('allocated_items_count', 0)}  | Unallocated Items: {summary.get('unallocated_items_count', 0)}  | Skipped Items: {summary.get('skipped_count', 0)} (demand: {summary.get('skipped_demand', 0)})  | Zero-Qty Items: {summary.get('zero_quantity_items_count', 0)}")
    print(f"Total Allocated Quantity: {summary.get('total_allocated_quantity', 0)}  | Allocated Ratio: {summary.get('allocated_ratio', 0.0):.2%}")
    print(f"Total Output Reported Items: {summary.get('total_output_reported_items', 0)}")
    print(f"Missing Items Count (should be 0): {summary.get('missing_items_count', 0)}")

    # Objective components
    obj_comp = summary.get('objective_components', {}) or {}
    if obj_comp:
        print("\nObjective Components (scaled):")
        print(f"  Quantity Component: {obj_comp.get('quantity_component', 0)} (int_w_quantity={obj_comp.get('int_w_quantity', 0)})")
        print(f"  Due Component:      {obj_comp.get('due_component', 0)} (int_w_due={obj_comp.get('int_w_due', 0)})")
        print(f"  scale={obj_comp.get('scale', 0)} weight_precision={obj_comp.get('weight_precision', 0)}")
    obj_bound = summary.get('objective_bound_metrics', {}) or {}
    if obj_bound:
        print("Objective Bound Metrics:")
        print(f"  Objective Value: {obj_bound.get('objective_value', 'NA')}  | Best Bound: {obj_bound.get('best_objective_bound', 'NA')}")
        print(f"  Gap Abs: {obj_bound.get('gap_abs', 'NA')}  | Gap Rel: {obj_bound.get('gap_rel', 'NA')}")

    # Plant utilization table
    plant_util = summary.get('plant_utilization', []) or []
    if plant_util:
        print("\nPLANT UTILIZATION")
        print("-"*60)
        print(f"{'Plant':<8} {'Capacity':<10} {'Used':<10} {'Util %':<8}")
        print("-"*60)
        for row in plant_util:
            print(f"{row.get('plantid', '-'):<8} {row.get('capacity', 0):<10} {row.get('used_capacity', 0):<10} {row.get('utilization_pct', 0.0):<8.2f}")
    
    # Print allocations
    allocations = result.get("allocations", [])
    print(f"\nALLOCATIONS ({len(allocations)} items)")
    print("-"*80)
    if allocations:
        print(f"{'Plant':<8} {'Order':<12} {'Model':<15} {'Submodel':<15} {'Quantity':<10}")
        print("-"*80)
        for alloc in allocations:
            print(f"{alloc['plantid']:<8} {alloc['order']:<12} {alloc['model']:<15} {alloc['submodel']:<15} {alloc['allocated_qty']:<10}")
        
        # Print allocation summary by plant
        plant_totals = {}
        for alloc in allocations:
            plant_id = alloc['plantid']
            plant_totals[plant_id] = plant_totals.get(plant_id, 0) + alloc['allocated_qty']
        
        print(f"\nALLOCATION BY PLANT")
        print("-"*30)
        for plant_id, total in sorted(plant_totals.items()):
            print(f"Plant {plant_id}: {total} units")
    else:
        print("No items allocated.")
    
    # Print skipped items
    skipped = result.get("skipped", [])
    if skipped:
        print(f"\nSKIPPED ITEMS ({len(skipped)} items)")
        print("-"*80)
        print(f"{'Order':<12} {'Model':<15} {'Submodel':<15} {'Quantity':<10} {'Reason':<25}")
        print("-"*80)
        for skip in skipped:
            print(f"{skip['order']:<12} {skip['model']:<15} {skip['submodel']:<15} {skip['quantity']:<10} {skip['reason']:<25}")
    
    # Print unallocated items
    unallocated = result.get("unallocated", [])
    if unallocated:
        print(f"\nUNALLOCATED ITEMS ({len(unallocated)} items)")
        print("-"*80)
        print(f"{'Order':<12} {'Model':<15} {'Submodel':<15} {'Quantity':<10} {'Reason':<25}")
        print("-"*80)
        for unalloc in unallocated:
            print(f"{unalloc['order']:<12} {unalloc['model']:<15} {unalloc['submodel']:<15} {unalloc['requested_qty']:<10} {unalloc['reason']:<25}")
    
    # Print zero quantity items
    zero_qty = result.get("zero_quantity_items", [])
    if zero_qty:
        print(f"\nZERO QUANTITY ITEMS ({len(zero_qty)} items) - Excluded from model")
        print("-"*80)
        print(f"{'Order':<12} {'Model':<15} {'Submodel':<15} {'Quantity':<10}")
        print("-"*80)
        for z in zero_qty:
            print(f"{z['order']:<12} {z['model']:<15} {z['submodel']:<15} {z['quantity']:<10}")

    print("\n" + "="*60)

if __name__ == "__main__":
    main()
