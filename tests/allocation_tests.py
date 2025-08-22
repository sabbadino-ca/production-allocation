"""
Unit tests for the allocate function in prod_allocation.py.

Covers:
- Variables created only for allowed (plant,item) pairs.
- Demand satisfaction per item across compatible plants.
- Skipping items with no compatible plants.
- Handling zero-quantity items.
- Due date prioritization in allocation decisions.
- Aggregated summary stats integrity.

Uses Python's built-in unittest to keep dependencies minimal.
"""
from __future__ import annotations

import unittest
from typing import List, cast
from datetime import datetime, timedelta

from prod_allocation import allocate
from domain_types import Plant, Order, Item


def _plant(pid: int, capacity: int, allowed: List[str]) -> Plant:
    """Build a Plant dict with required fields and types.

    Args:
        pid: Plant identifier (int).
        capacity: Maximum capacity of the plant.
        allowed: List of model names this plant can produce.

    Returns:
        A Plant-typed dict suitable for allocate().
    """
    return {
        "plantid": pid,
        "plantfamily": "F1",
        "capacity": capacity,
        "allowedModels": allowed,
    }


def _item(model: str, submodel: str, qty: int, model_family: str = "F1") -> Item:
    """Build an Item dict with required fields.

    Args:
        model: Model name.
        submodel: Submodel identifier.
        qty: Required quantity.
        model_family: Optional model family name (defaults to "F1").
        due_date: Optional due date string in ISO format.

    Returns:
        An Item-typed dict suitable for allocate().
    """
    item_dict: Item = {
        "modelFamily": model_family,
        "model": model,
        "submodel": submodel,
        "quantity": qty,
    }
    return item_dict


def _order(order_id: str, items: List[Item], due_date: str) -> Order:
    """Build an Order dict with required fields.

    Args:
        order_id: External order identifier.
        items: List of items in the order.
        due_date: ISO date string yyyy-MM-dd.

    Returns:
        An Order-typed dict suitable for allocate().
    """
    return {"order": order_id, "dueDate": due_date, "items": items}


class TestAllocate(unittest.TestCase):
    def setUp(self) -> None:
        """Set up test fixtures with a fixed current date for consistent testing."""
        self.current_date = datetime(2025, 8, 21)  # Fixed test date
    def test_basic_allowed_and_demand_split(self) -> None:
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 10)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        self.assertIn("summary", res)
        self.assertIn("allocations", res)
        self.assertIn("skipped", res)

        # Demand must be satisfied exactly for M1 S1 quantity 10 across P1,P2
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertEqual(total_alloc, 10)
        # No skipped since both plants can make M1
        self.assertEqual(len(res["skipped"]), 0)

    def test_skip_when_no_compatible_plant(self) -> None:
        plants = [
            _plant(1, 100, ["M2"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 5)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        # Item should be skipped
        self.assertEqual(res["skipped"][0]["reason"], "no_compatible_plant")
        self.assertEqual(res["skipped"][0]["quantity"], 5)
        self.assertEqual(res["summary"]["skipped_count"], 1)
        self.assertEqual(res["summary"]["skipped_demand"], 5)
        # No allocations since not modeled
        self.assertEqual(len(res["allocations"]), 0)

    def test_zero_quantity_items_are_ignored(self) -> None:
        plants = [
            _plant(1, 100, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 0)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)
        # Zero quantity with compatible plant: no allocation, not skipped
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 0)
        self.assertEqual(res["summary"]["total_demand"], 0)

    def test_incompatible_zero_quantity_item_is_skipped(self) -> None:
        plants = [
            _plant(1, 100, ["M1"]),  # Does NOT allow M2
        ]
        orders = [
            _order("O1", [_item("M2", "Sx", 0)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertEqual(res["skipped"][0]["reason"], "no_compatible_plant")
        self.assertEqual(res["skipped"][0]["quantity"], 0)

    def test_multiple_orders_and_models(self) -> None:
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M2", "M3"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 4), _item("M2", "S2", 6)], datetime.now().strftime("%Y-%m-%d")),
            _order("O2", [_item("M2", "S3", 5), _item("M3", "S4", 3)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        # All items have at least one compatible plant, so no skipped
        self.assertEqual(res["summary"]["skipped_count"], 0)
        self.assertEqual(len(res["skipped"]), 0)
        # Demand totals should match
        self.assertEqual(res["summary"]["total_demand"], 4 + 6 + 5 + 3)
        # Allocations sum equals demand
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertEqual(total_alloc, 18)

    def test_summary_stats(self) -> None:
        plants = [
            _plant(1, 50, ["M1"]),
            _plant(2, 70, ["M2"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 5)], datetime.now().strftime("%Y-%m-%d")),
            _order("O2", [_item("M2", "S2", 8)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        self.assertEqual(res["summary"]["plants_count"], 2)
        self.assertEqual(res["summary"]["orders_count"], 2)
        self.assertEqual(res["summary"]["unique_models_count"], 2)
        self.assertEqual(res["summary"]["total_capacity"], 120)
        self.assertEqual(res["summary"]["total_demand"], 13)
        self.assertEqual(res["summary"]["capacity_minus_demand"], 120 - 13)
        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})

    def test_partial_packing_like_bin_packing(self) -> None:
        """Two plants, capacities 5 and 3 (total 8). Three items M1 with
        quantities 4, 2, 2. Only two items can be placed; one remains unallocated.
        No infeasibility should be reported.
        """
        plants = [
            _plant(1, 5, ["M1"]),
            _plant(2, 3, ["M1"]),
        ]
        orders = [
            _order("O1", [
                _item("M1", "S1", 4),
                _item("M1", "S2", 2),
                _item("M1", "S3", 2),
            ], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        # Best packing: 4 on plant 5, 2 on plant 3 => 6 total; one 2 remains
        self.assertEqual(total_alloc, 6)
        # Exactly one item should be unallocated
        self.assertEqual(len(res.get("unallocated", [])), 1)
        # All items are compatible, so skipped is zero
        self.assertEqual(len(res["skipped"]), 0)

    def test_over_demand_returns_unallocated_instead_of_infeasible(self) -> None:
        """When demand exceeds capacity, solution is feasible with maximum placement
        and leftover items reported under 'unallocated'."""
        plants = [
            _plant(1, 5, ["M1"]),
            _plant(2, 3, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 10)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date)

        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})
        # Single item quantity=10 cannot be partially placed; expect 0 allocated
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertEqual(total_alloc, 0)
        # The item should be marked unallocated
        self.assertEqual(len(res.get("unallocated", [])), 1)

    def test_due_date_priority_past_vs_future(self) -> None:
        """Past due items should get allocated before future due items when capacity is limited."""
        plants = [
            _plant(1, 5, ["M1"]),  # Limited capacity for only one item
        ]
        past_due = (self.current_date - timedelta(days=11)).strftime("%Y-%m-%d")
        future_near = (self.current_date + timedelta(days=4)).strftime("%Y-%m-%d") 
        future_far = (self.current_date + timedelta(days=9)).strftime("%Y-%m-%d")
        
        orders = [
            _order("O1", [_item("M1", "S1", 5)], past_due),    # 11 days overdue
            _order("O2", [_item("M1", "S2", 5)], future_near), # 4 days in future
            _order("O3", [_item("M1", "S3", 5)], future_far),  # 9 days in future
        ]
        res = allocate(plants, orders, self.current_date)
        
        # Only past due item should be allocated
        self.assertEqual(len(res["allocations"]), 1)
        allocated_item = res["allocations"][0]
        self.assertEqual(allocated_item["submodel"], "S1")  # Past due item
        self.assertEqual(allocated_item["allocated_qty"], 5)
        
        # Future items should be unallocated
        self.assertEqual(len(res.get("unallocated", [])), 2)

    def test_due_date_priority_different_overdue_periods(self) -> None:
        """More overdue items should get higher priority."""
        plants = [
            _plant(1, 5, ["M1"]),  # Only capacity for one item
        ]
        overdue_6 = (self.current_date - timedelta(days=6)).strftime("%Y-%m-%d")
        overdue_11 = (self.current_date - timedelta(days=11)).strftime("%Y-%m-%d")
        overdue_3 = (self.current_date - timedelta(days=3)).strftime("%Y-%m-%d")
        
        orders = [
            _order("O1", [_item("M1", "S1", 5)],overdue_6),  # 6 days overdue
            _order("O2", [_item("M1", "S2", 5)], overdue_11), # 11 days overdue (higher priority)
            _order("O3", [_item("M1", "S3", 5)], overdue_3),  # 3 days overdue
        ]
        res = allocate(plants, orders, self.current_date)
        
        # Most overdue item should be allocated
        self.assertEqual(len(res["allocations"]), 1)
        allocated_item = res["allocations"][0]
        self.assertEqual(allocated_item["submodel"], "S2")  # Most overdue
        self.assertEqual(allocated_item["allocated_qty"], 5)

    def test_due_date_priority_future_ordering(self) -> None:
        """Among future items, closer due dates should be preferred."""
        plants = [
            _plant(1, 5, ["M1"]),  # Only capacity for one item
        ]
        future_9 = (self.current_date + timedelta(days=9)).strftime("%Y-%m-%d")
        future_4 = (self.current_date + timedelta(days=4)).strftime("%Y-%m-%d")
        future_15 = (self.current_date + timedelta(days=15)).strftime("%Y-%m-%d")
        
        orders = [
            _order("O1", [_item("M1", "S1", 5)],future_9),  # 9 days away
            _order("O2", [_item("M1", "S2", 5)],future_4),  # 4 days away (higher priority)
            _order("O3", [_item("M1", "S3", 5)],future_15), # 15 days away
        ]
        res = allocate(plants, orders, self.current_date)
        
        # Closest due date should be allocated
        self.assertEqual(len(res["allocations"]), 1)
        allocated_item = res["allocations"][0]
        self.assertEqual(allocated_item["submodel"], "S2")  # Closest due date
        self.assertEqual(allocated_item["allocated_qty"], 5)

    def test_due_date_priority_near_vs_far_future(self) -> None:
        """Near future items should get higher priority than far future items."""
        plants = [
            _plant(1, 5, ["M1"]),  # Only capacity for one item
        ]
        future_near = (self.current_date + timedelta(days=4)).strftime("%Y-%m-%d")
        future_far = (self.current_date + timedelta(days=20)).strftime("%Y-%m-%d")
        
        orders = [
            _order("O1", [_item("M1", "S1", 5)], future_far),  # 20 days away (lower priority)
            _order("O2", [_item("M1", "S2", 5)], future_near),  # 4 days away (higher priority)
        ]
        res = allocate(plants, orders, self.current_date)
        
        # Near future item should be allocated over far future item
        self.assertEqual(len(res["allocations"]), 1)
        allocated_item = res["allocations"][0]
        self.assertEqual(allocated_item["submodel"], "S2")  # Near future date
        self.assertEqual(allocated_item["allocated_qty"], 5)

    def test_due_date_priority_with_quantity_weight(self) -> None:
        """Due date priority should be combined with quantity (not override it completely)."""
        plants = [
            _plant(1, 15, ["M1"]),  # Capacity for both items
        ]
        overdue_11 = (self.current_date - timedelta(days=11)).strftime("%Y-%m-%d")
        future_4 = (self.current_date + timedelta(days=4)).strftime("%Y-%m-%d")
        
        orders = [
            _order("O1", [_item("M1", "S1", 10)], overdue_11), # 11 days overdue, qty 10
            _order("O2", [_item("M1", "S2", 5)], future_4),    # 4 days future, qty 5
        ]
        res = allocate(plants, orders, self.current_date)
        
        # Both should be allocated since capacity allows
        self.assertEqual(len(res["allocations"]), 2)
        total_allocated = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertEqual(total_allocated, 15)
        
        # No unallocated items
        self.assertEqual(len(res.get("unallocated", [])), 0)


if __name__ == "__main__":
    unittest.main()
