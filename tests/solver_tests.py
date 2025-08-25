import unittest
from typing import List, Iterable, Sequence, Dict

from datatypes import ObjectiveSpec
from optimizer import optimize_plants_assignment


def _mk_fill_spec(n: int, weight: float = 1.0) -> ObjectiveSpec:
	"""Create a simple per-item 'fill' objective (maximize #items placed).

	Parameters
	----------
	n : int
		Number of items; length of the values vector.
	weight : float
		Objective weight; nonnegative.

	Returns
	-------
	ObjectiveSpec
		Fill objective with all-ones values of length n.
	"""
	return ObjectiveSpec(name="fill", values=[1] * n, sense="maximize", weight=weight)


class TestSolverSingleFactor(unittest.TestCase):
	def test_fill_only_allocates_all_feasible_items(self) -> None:
		"""With only 'fill' active and ample compatible capacity, all feasible items are allocated."""
		item_names = ["i1", "i2", "i3"]
		model_names = ["A", "A", "B"]
		item_quantities = [5, 5, 5]

		plant_names = ["P1", "P2"]
		plant_caps = [10, 5]
		allowed: Sequence[Iterable[str]] = [
			{"A"},  # P1 makes A
			{"B"},  # P2 makes B
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			w_group=0.0,
			w_plants=0.0,
			min_allowed_qty_of_items_same_model_name_in_a_plant=0,
			soft_min_qty_of_items_same_model_name_in_a_plant=0,
			time_limit_s=2,
			log=False,
		)

		self.assertEqual(res["items_placed"], 3)
		self.assertEqual(res["total_quantity_placed"], 15)
		self.assertEqual(res["plants_used"], 2)
		self.assertEqual(res["model_name_plants_used"].get("A"), 1)
		self.assertEqual(res["model_name_plants_used"].get("B"), 1)

		# Sanity: each allocated item must go to an allowed plant
		allowed_map: Dict[str, set[str]] = {"P1": {"A"}, "P2": {"B"}}
		for name, rec in res["items"].items():
			if rec["status"] == "allocated":
				self.assertIn(rec["model_name"], allowed_map[rec["plant"]])

	def test_plants_penalty_prefers_one_plant_when_possible(self) -> None:
		"""With plants penalty active, solution should pack into a single plant if capacity allows."""
		item_names = ["i1", "i2"]
		model_names = ["M1", "M2"]
		item_quantities = [3, 3]

		plant_names = ["P1", "P2"]
		plant_caps = [6, 6]
		allowed = [
			{"M1", "M2"},
			{"M1", "M2"},
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			w_group=0.0,
			w_plants=2.0,  # emphasize fewer plants
			min_allowed_qty_of_items_same_model_name_in_a_plant=0,
			soft_min_qty_of_items_same_model_name_in_a_plant=0,
			time_limit_s=2,
			log=False,
		)

		self.assertEqual(res["items_placed"], 2)
		self.assertEqual(res["plants_used"], 1)

	def test_grouping_penalty_avoids_splitting_model_across_plants(self) -> None:
		"""With grouping penalty, a model should use the minimum number of plants when capacity allows."""
		item_names = ["i1", "i2", "i3"]
		model_names = ["A", "A", "A"]
		item_quantities = [1, 1, 1]

		plant_names = ["P1", "P2"]
		plant_caps = [3, 3]
		allowed = [
			{"A"},
			{"A"},
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=0.5)],  # small tie-breaker to allocate all
			w_group=1.0,
			w_plants=0.0,
			min_allowed_qty_of_items_same_model_name_in_a_plant=0,
			soft_min_qty_of_items_same_model_name_in_a_plant=0,
			time_limit_s=2,
			log=False,
		)

		self.assertEqual(res["items_placed"], 3)
		# All items of model A should be in a single plant
		self.assertEqual(res["model_name_plants_used"].get("A"), 1)
		self.assertLessEqual(res["extra_plants"], 0)  # exactly 0 for one model

	def test_soft_min_encourages_packing_to_meet_threshold(self) -> None:
		"""Soft minimum (shortfall-only) should push packing to one plant to avoid shortfall."""
		item_names = ["i1", "i2"]
		model_names = ["A", "A"]
		item_quantities = [2, 2]

		plant_names = ["P1", "P2"]
		plant_caps = [4, 4]
		allowed = [
			{"A"},
			{"A"},
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=0.2)],
			w_group=0.0,
			w_plants=0.0,
			min_allowed_qty_of_items_same_model_name_in_a_plant=0,
			soft_min_qty_of_items_same_model_name_in_a_plant=3,
			w_soft_min_qty_of_items_same_model_name_in_a_plant=1.0,
			time_limit_s=2,
			log=False,
		)

		self.assertEqual(res["items_placed"], 2)
		self.assertEqual(res["model_name_plants_used"].get("A"), 1)
		# No shortfall if all 4 go to one plant (meets 3); presence only on that plant
		soft_meta = res["objective_breakdown"]["soft_min_qty"]
		self.assertEqual(soft_meta.get("total_shortfall"), 0)

	def test_unsupported_model_names_are_reported(self) -> None:
		"""Items with model names unsupported by all plants should be flagged as 'unsupported'."""
		item_names = ["i1", "i2"]
		model_names = ["X", "Y"]
		item_quantities = [1, 1]

		plant_names = ["P1"]
		plant_caps = [10]
		allowed = [
			{"X"},  # Y unsupported everywhere
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			w_group=0.0,
			w_plants=0.0,
			min_allowed_qty_of_items_same_model_name_in_a_plant=0,
			soft_min_qty_of_items_same_model_name_in_a_plant=0,
			time_limit_s=2,
			log=False,
		)

		self.assertIn("i2", res["unsupported_items"])  # Y unsupported
		# i1 should be allocated to P1
		self.assertEqual(res["items"].get("i1", {}).get("status"), "allocated")


class TestWeightSensitivityAndMinima(unittest.TestCase):
	def test_plants_weight_sensitivity_nonincreasing(self) -> None:
		"""Increasing w_plants should not increase plants_used (nonincreasing monotonicity)."""
		item_names = ["i1", "i2"]
		model_names = ["M1", "M2"]
		item_quantities = [3, 3]
		plant_names = ["P1", "P2"]
		plant_caps = [6, 6]
		allowed = [
			{"M1", "M2"},
			{"M1", "M2"},
		]

		base = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			w_group=0.0,
			w_plants=0.0,
			time_limit_s=2,
			log=False,
		)

		strong = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			w_group=0.0,
			w_plants=5.0,
			time_limit_s=2,
			log=False,
		)

		self.assertGreaterEqual(base["items_placed"], strong["items_placed"])  # penalty can reduce placements
		self.assertLessEqual(strong["plants_used"], base["plants_used"])       # monotone nonincreasing

	def test_grouping_weight_sensitivity_nonincreasing(self) -> None:
		"""Increasing w_group should not increase the number of plants used by a model."""
		item_names = ["i1", "i2", "i3"]
		model_names = ["A", "A", "A"]
		item_quantities = [1, 1, 1]
		plant_names = ["P1", "P2"]
		plant_caps = [3, 3]
		allowed = [
			{"A"},
			{"A"},
		]

		low = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=0.5)],
			w_group=0.0,
			w_plants=0.0,
			time_limit_s=2,
			log=False,
		)

		high = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=0.5)],
			w_group=5.0,
			w_plants=0.0,
			time_limit_s=2,
			log=False,
		)

		self.assertLessEqual(high["model_name_plants_used"].get("A", 0), low["model_name_plants_used"].get("A", 0))

	def test_soft_min_weight_sensitivity_shortfall_nonincreasing(self) -> None:
		"""With higher soft-min weight, total shortfall should be nonincreasing (or equal)."""
		item_names = ["i1", "i2"]
		model_names = ["A", "A"]
		item_quantities = [2, 2]
		plant_names = ["P1", "P2"]
		plant_caps = [2, 2]  # each plant cannot reach 3
		allowed = [
			{"A"},
			{"A"},
		]

		low = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			soft_min_qty_of_items_same_model_name_in_a_plant=3,
			w_soft_min_qty_of_items_same_model_name_in_a_plant=0.1,
			time_limit_s=2,
			log=False,
		)

		high = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			soft_min_qty_of_items_same_model_name_in_a_plant=3,
			w_soft_min_qty_of_items_same_model_name_in_a_plant=5.0,
			time_limit_s=2,
			log=False,
		)

		low_short = low["objective_breakdown"]["soft_min_qty"].get("total_shortfall", 0)
		high_short = high["objective_breakdown"]["soft_min_qty"].get("total_shortfall", 0)
		self.assertLessEqual(high_short, low_short)

	def test_hard_min_blocks_when_no_plant_can_reach_threshold(self) -> None:
		"""Hard min forbids allocation if no plant can reach the required per-plant quantity."""
		item_names = ["i1", "i2"]
		model_names = ["A", "A"]
		item_quantities = [2, 2]  # total 4
		plant_names = ["P1", "P2"]
		plant_caps = [2, 2]       # each < min=3
		allowed = [
			{"A"},
			{"A"},
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			min_allowed_qty_of_items_same_model_name_in_a_plant=3,
			time_limit_s=2,
			log=False,
		)

		self.assertEqual(res["items_placed"], 0)
		self.assertEqual(len(res["unallocated_items"]), 2)
		self.assertEqual(res["model_name_plants_used"].get("A", 0), 0)

	def test_soft_min_allows_partial_allocation_with_penalty(self) -> None:
		"""Soft min permits allocation below threshold; expect positive shortfall and allocated items."""
		item_names = ["i1", "i2"]
		model_names = ["A", "A"]
		item_quantities = [2, 2]
		plant_names = ["P1", "P2"]
		plant_caps = [2, 2]
		allowed = [
			{"A"},
			{"A"},
		]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			soft_min_qty_of_items_same_model_name_in_a_plant=3,
			w_soft_min_qty_of_items_same_model_name_in_a_plant=1.0,
			time_limit_s=2,
			log=False,
		)

		self.assertGreater(res["items_placed"], 0)
		self.assertGreaterEqual(res["total_quantity_placed"], 2)
		soft_meta = res["objective_breakdown"]["soft_min_qty"]
		self.assertGreater(soft_meta.get("total_shortfall", 0), 0)

	def test_regression_invariants_objective_breakdown_keys(self) -> None:
		"""Ensure key diagnostics are present to guard against regressions in output schema."""
		item_names = ["i1"]
		model_names = ["A"]
		item_quantities = [1]
		plant_names = ["P1"]
		plant_caps = [1]
		allowed = [{"A"}]

		res = optimize_plants_assignment(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=[_mk_fill_spec(len(item_names), weight=1.0)],
			time_limit_s=2,
			log=False,
		)

		ob = res.get("objective_breakdown", {})
		self.assertIn("additive_specs_info", ob)
		self.assertIn("achieved_additive_raw", ob)
		self.assertIn("structural_normalizers", ob)
		self.assertIn("soft_min_qty", ob)
		self.assertIn("status", ob)


if __name__ == "__main__":
	unittest.main()
