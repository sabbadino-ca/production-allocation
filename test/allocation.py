"""
Unit tests for the allocate function in prod_allocation.py.

Covers:
- Variables created only for allowed (plant,item) pairs.
- Demand satisfaction per item across compatible plants.
- Skipping items with no compatible plants.
- Handling zero-quantity items.
- Aggregated summary stats integrity.

Uses Python's built-in unittest to keep dependencies minimal.
"""
from __future__ import annotations

import unittest
from typing import List

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

    Returns:
        An Item-typed dict suitable for allocate().
    """
    return {
        "modelFamily": model_family,
        "model": model,
        "submodel": submodel,
        "quantity": qty,
    }


def _order(order_id: str, items: List[Item], due_date: str = "2025-01-01") -> Order:
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
    def test_basic_allowed_and_demand_split(self) -> None:
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 10)]),
        ]
        res = allocate(plants, orders)

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
            _order("O1", [_item("M1", "S1", 5)]),
        ]
        res = allocate(plants, orders)

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
            _order("O1", [_item("M1", "S1", 0)]),
        ]
        res = allocate(plants, orders)

        # No allocations and no skipped (qty=0 means no variables, no constraint)
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 0)
        self.assertEqual(res["summary"]["total_demand"], 0)

    def test_multiple_orders_and_models(self) -> None:
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M2", "M3"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 4), _item("M2", "S2", 6)]),
            _order("O2", [_item("M2", "S3", 5), _item("M3", "S4", 3)]),
        ]
        res = allocate(plants, orders)

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
            _order("O1", [_item("M1", "S1", 5)]),
            _order("O2", [_item("M2", "S2", 8)]),
        ]
        res = allocate(plants, orders)

        self.assertEqual(res["summary"]["plants_count"], 2)
        self.assertEqual(res["summary"]["orders_count"], 2)
        self.assertEqual(res["summary"]["unique_models_count"], 2)
        self.assertEqual(res["summary"]["total_capacity"], 120)
        self.assertEqual(res["summary"]["total_demand"], 13)
        self.assertEqual(res["summary"]["capacity_minus_demand"], 120 - 13)
        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})


if __name__ == "__main__":
    unittest.main()
