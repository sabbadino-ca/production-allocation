"""
Main entry point for production allocation optimization.
Requires two input file paths as command line arguments.
"""
import argparse
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
    result = allocate(plants, orders)
    summary = result.get("summary", {})
    print(
        "Summary => plants: {plants_count}, orders: {orders_count}, models: {unique_models_count}, capacity: {total_capacity}, demand: {total_demand}, delta: {delta}".format(
            plants_count=summary.get("plants_count"),
            orders_count=summary.get("orders_count"),
            unique_models_count=summary.get("unique_models_count"),
            total_capacity=summary.get("total_capacity"),
            total_demand=summary.get("total_demand"),
            delta=summary.get("capacity_minus_demand"),
        )
    )

if __name__ == "__main__":
    main()
