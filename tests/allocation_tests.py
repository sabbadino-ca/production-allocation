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
from allocation_types import WeightsConfig
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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})

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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})

        # Item should be skipped
        self.assertEqual(res["skipped"][0]["reason"], "no_compatible_plant")
        self.assertEqual(res["skipped"][0]["quantity"], 5)
        self.assertEqual(res["summary"]["skipped_count"], 1)
        self.assertEqual(res["summary"]["skipped_demand"], 5)
        # No allocations since not modeled
        self.assertEqual(len(res["allocations"]), 0)

    def test_zero_quantity_items_are_reported_separately(self) -> None:
        plants = [
            _plant(1, 100, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 0)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        # Zero quantity with compatible plant: no allocation, not skipped, appears in zero_quantity_items
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 0)
        self.assertEqual(len(res.get("zero_quantity_items", [])), 1)
        self.assertEqual(res["summary"]["zero_quantity_items_count"], 1)
        self.assertEqual(res["summary"]["total_demand"], 0)

    def test_default_horizon_days_used(self) -> None:
        plants = [
            _plant(1, 100, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 10)], datetime.now().strftime("%Y-%m-%d")),
        ]
    # Omit horizon_days in weights
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        self.assertIn("diagnostics", res["summary"])
        self.assertEqual(res["summary"]["diagnostics"]["horizon_days"], 30)

    def test_incompatible_zero_quantity_item_is_still_reported_zero_qty(self) -> None:
        plants = [
            _plant(1, 100, ["M1"]),  # Does NOT allow M2
        ]
        orders = [
            _order("O1", [_item("M2", "Sx", 0)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        # Even though incompatible, zero quantity classification takes precedence; reported in zero_quantity_items
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 0)
        self.assertEqual(len(res.get("zero_quantity_items", [])), 1)
        self.assertEqual(res["summary"]["zero_quantity_items_count"], 1)

    def test_skip_when_item_too_large_for_any_single_plant(self) -> None:
        plants = [
            _plant(1, 5, ["M1"]),
            _plant(2, 4, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 6)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        self.assertEqual(len(res["allocations"]), 0)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertEqual(res["skipped"][0]["reason"], "too_large_for_any_plant")
        self.assertEqual(res["skipped"][0]["quantity"], 6)

    def test_multiple_orders_and_models(self) -> None:
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M2", "M3"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 4), _item("M2", "S2", 6)], datetime.now().strftime("%Y-%m-%d")),
            _order("O2", [_item("M2", "S3", 5), _item("M3", "S4", 3)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})

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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})

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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})

        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        # Best packing: 4 on plant 5, 2 on plant 3 => 6 total; one 2 remains
        self.assertEqual(total_alloc, 6)
        # Exactly one item should be unallocated
        self.assertEqual(len(res.get("unallocated", [])), 1)
        # All items are compatible, so skipped is zero
        self.assertEqual(len(res["skipped"]), 0)

    def test_single_oversized_item_is_skipped_not_unallocated(self) -> None:
        """An unsplittable item whose quantity exceeds every compatible plant's
        individual capacity is structurally impossible and must be SKIPPED with
        reason 'too_large_for_any_plant' (not reported as unallocated)."""
        plants = [
            _plant(1, 5, ["M1"]),
            _plant(2, 3, ["M1"]),
        ]
        orders = [
            _order("O1", [_item("M1", "S1", 10)], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})
        # No allocation possible
        self.assertEqual(len(res["allocations"]), 0)
        # Should be skipped with the correct reason
        self.assertEqual(len(res["skipped"]), 1)
        self.assertEqual(res["skipped"][0]["reason"], "too_large_for_any_plant")
        # No unallocated items because it never entered the model
        self.assertEqual(len(res.get("unallocated", [])), 0)

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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        
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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        
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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        
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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        
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
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        
        # Both should be allocated since capacity allows
        self.assertEqual(len(res["allocations"]), 2)
        total_allocated = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertEqual(total_allocated, 15)
        
        # No unallocated items
        self.assertEqual(len(res.get("unallocated", [])), 0)

    def test_over_demand_returns_some_unallocated(self) -> None:
        """When aggregate demand exceeds total capacity we should get a feasible solution with >=1 unallocated item.

        We don't assert an exact count (solver may choose any maximal packing), only that not all modelable items were placed.
        """
        plants = [
            _plant(1, 5, ["M1"]),
            _plant(2, 4, ["M1"]),
        ]  # total capacity 9
        orders = [
            _order("O1", [
                _item("M1", "S1", 5),
                _item("M1", "S2", 4),
                _item("M1", "S3", 3),  # total demand 12 > 9
            ], datetime.now().strftime("%Y-%m-%d")),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        self.assertIn(res["summary"]["status"], {"OPTIMAL", "FEASIBLE"})
        total_alloc = sum(a["allocated_qty"] for a in res["allocations"])
        self.assertLess(total_alloc, 12)
        self.assertGreaterEqual(len(res.get("unallocated", [])), 1)

    def test_compactness_objective_reward(self) -> None:
        """Compactness weight should reward concentrating each model on a single plant.

        We assert:
          * Positive compactness_component when weight active.
          * Each model ends up on exactly one plant (given ample capacity & symmetry).
          * With weight disabled reward becomes 0 (distribution may still be consolidated by coincidence).
        """
        plants = [
            _plant(1, 100, ["M1", "M2"]),
            _plant(2, 100, ["M1", "M2"]),
        ]
        today = self.current_date.strftime("%Y-%m-%d")
        orders = [
            _order("O1", [_item("M1", "S1", 5), _item("M1", "S2", 7)], today),
            _order("O2", [_item("M2", "S3", 4), _item("M2", "S4", 6)], today),
        ]
        res_active = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        obj_active = res_active["summary"]["objective_components"]
        self.assertGreater(obj_active.get("compactness_component", 0), 0)
        model_to_plants_active = {}
        for a in res_active["allocations"]:
            model_to_plants_active.setdefault(a["model"], set()).add(a["plantid"])
        for m, plant_set in model_to_plants_active.items():
            self.assertEqual(len(plant_set), 1, f"Model {m} split across {plant_set}")
        # Disabled weight run
        res_inert = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":0.0})
        obj_inert = res_inert["summary"]["objective_components"]
        self.assertEqual(obj_inert.get("compactness_component", -1), 0)

    def test_compactness_distribution_consolidates_models(self) -> None:
        """With compactness enabled, each model's items should end up on exactly one plant when
        there exists a tie on other objective components (quantity, due).

        Construction:
          * Two models M1, M2; each has two items whose quantities sum to 11.
          * Two plants each capacity 11 and can produce both models.
          * All due dates identical (neutralize urgency component) and quantities already maximal.
          * Without compactness there are many optimal packings (mixing items across plants or
            consolidating each model to a plant). With compactness active, consolidating each
            model entirely on one plant yields an extra reward (scale per model), so the solver
            should pick a layout where every model uses exactly one plant.

        We validate by reconstructing model->set(plantid) from allocations and asserting all sets
        have size 1.
        """
        plants = [
            _plant(1, 11, ["M1", "M2"]),
            _plant(2, 11, ["M1", "M2"]),
        ]
        today = self.current_date.strftime("%Y-%m-%d")
        # Each model sums to 11 exactly (fills one plant perfectly)
        orders = [
            _order("O1", [_item("M1", "S1", 6), _item("M1", "S2", 5)], today),
            _order("O2", [_item("M2", "S3", 5), _item("M2", "S4", 6)], today),
        ]
        res = allocate(plants, orders, self.current_date, {"w_quantity":5.0, "w_due":1.0, "w_compactness":2.0})
        allocs = res["allocations"]
        self.assertEqual(len(allocs), 4)
        model_to_plants = {}
        for a in allocs:
            model_to_plants.setdefault(a["model"], set()).add(a["plantid"])
        for model, plant_set in model_to_plants.items():
            self.assertEqual(len(plant_set), 1, f"Model {model} spread across multiple plants: {plant_set}")
        obj = res["summary"]["objective_components"]
        self.assertGreater(obj.get("compactness_component", 0), 0)
# Ensure no stray global assertions remain below (cleanup)
if __name__ == "__main__":
    unittest.main()
