"""
Main entry point for production allocation optimization.
Requires two input file paths as command line arguments.
"""
import argparse
from datetime import datetime
from data_loader import load_plants, load_orders
from typing import List
from domain_types import Plant, Order
from prod_allocation import allocate

def main():
    parser = argparse.ArgumentParser(description="Production Allocation Optimizer")
    parser.add_argument('--plants', required=True, help='Path to plants info JSON file')
    parser.add_argument('--orders', required=True, help='Path to orders JSON file')
    args = parser.parse_args()

    plants: List[Plant] = load_plants(args.plants)
    orders: List[Order] = load_orders(args.orders)

    print(f"Loaded {len(plants)} plants and {len(orders)} orders.")
    current_date = datetime.now()
    result = allocate(plants, orders, current_date)
    
    # Print summary
    summary = result.get("summary", {})
    print("\n" + "="*60)
    print("OPTIMIZATION SUMMARY")
    print("="*60)
    print(f"Status: {summary.get('status', 'UNKNOWN')}")
    print(f"Plants: {summary.get('plants_count', 0)}")
    print(f"Orders: {summary.get('orders_count', 0)}")
    print(f"Unique Models: {summary.get('unique_models_count', 0)}")
    print(f"Total Capacity: {summary.get('total_capacity', 0)}")
    print(f"Total Demand: {summary.get('total_demand', 0)}")
    print(f"Capacity - Demand: {summary.get('capacity_minus_demand', 0)}")
    print(f"Skipped Items: {summary.get('skipped_count', 0)} (demand: {summary.get('skipped_demand', 0)})")
    
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
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()
