import unittest
from typing import Iterable, List, Sequence

from inputvalidations import validate_input, ObjectiveSpecValidation
from datatypes import ObjectiveSpec


def _valid_args():
	"""Return a baseline set of valid arguments for validate_input."""
	item_names = ["i1", "i2"]
	model_names = ["mA", "mB"]
	item_quantities = [1, 2]

	plant_names = ["P1", "P2"]
	plant_quantity_capacities = [10, 5]
	allowed_model_names_per_plant: Sequence[Iterable[str]] = [
		{"mA", "mB"},
		{"mB"},
	]

	additive_objectives = [
		ObjectiveSpec(name="fill", values=[1, 1], sense="maximize", weight=1.0),
	]

	min_allowed = 0
	soft_min = 0

	return (
		item_names,
		model_names,
		item_quantities,
		plant_names,
		plant_quantity_capacities,
		allowed_model_names_per_plant,
		additive_objectives,
		min_allowed,
		soft_min,
	)


class TestInputValidation(unittest.TestCase):
	def test_validate_input_ok(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		# Should not raise
		validate_input(
			item_names=item_names,
			model_names=model_names,
			item_quantities=item_quantities,
			plant_names=plant_names,
			plant_quantity_capacities=plant_caps,
			allowed_model_names_per_plant=allowed,
			additive_objectives=objectives,
			min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
			soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
		)

	def test_mismatch_lengths_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		# Remove one item to break lengths
		item_names_bad = item_names[:-1]
		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names_bad,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_duplicate_item_names_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		item_names_bad = ["i1", "i1"]
		with self.assertRaises(ValueError):
			validate_input(
				item_names=item_names_bad,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_plant_arrays_mismatch_length_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		plant_caps_bad = plant_caps + [100]
		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps_bad,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

		# Also P == 0
		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=[],
				plant_quantity_capacities=[],
				allowed_model_names_per_plant=[],
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_duplicate_plant_names_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		plant_names_bad = ["P1", "P1"]
		with self.assertRaises(ValueError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names_bad,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_non_positive_plant_capacity_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		plant_caps_bad = [0, 5]
		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps_bad,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_negative_item_quantity_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		item_quantities_bad = [1, -2]
		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities_bad,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_min_allowed_negative_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			_min_allowed,
			soft_min,
		) = _valid_args()

		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=-1,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_soft_min_negative_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			objectives,
			min_allowed,
			_soft_min,
		) = _valid_args()

		with self.assertRaises(AssertionError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=-5,
			)

	def test_allowed_models_empty_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			_allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		# Make the first plant have an empty allowed models list
		allowed_bad: Sequence[Iterable[str]] = [[], {"mB"}]
		with self.assertRaises(ValueError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed_bad,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_allowed_models_duplicates_raises(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			_allowed,
			objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		# Duplicate "mA" for the first plant
		allowed_bad: Sequence[Iterable[str]] = [["mA", "mA"], {"mB"}]
		with self.assertRaises(ValueError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed_bad,
				additive_objectives=objectives,
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_objectives_type_error_when_not_objectivespec(self) -> None:
		(
			item_names,
			model_names,
			item_quantities,
			plant_names,
			plant_caps,
			allowed,
			_objectives,
			min_allowed,
			soft_min,
		) = _valid_args()

		with self.assertRaises(TypeError):
			ObjectiveSpecValidation(["not an ObjectiveSpec"])  # type: ignore[arg-type]

		with self.assertRaises(TypeError):
			validate_input(
				item_names=item_names,
				model_names=model_names,
				item_quantities=item_quantities,
				plant_names=plant_names,
				plant_quantity_capacities=plant_caps,
				allowed_model_names_per_plant=allowed,
				additive_objectives=["not an ObjectiveSpec"],  # type: ignore[list-item]
				min_allowed_qty_of_items_same_model_name_in_a_plant=min_allowed,
				soft_min_qty_of_items_same_model_name_in_a_plant=soft_min,
			)

	def test_objective_values_not_iterable_raises(self) -> None:
		# values=123 is not iterable -> TypeError
		bad = ObjectiveSpec(name="bad", values=123, sense="maximize", weight=1.0)  # type: ignore[arg-type]
		with self.assertRaises(TypeError):
			ObjectiveSpecValidation([bad])

	def test_objective_has_non_integer_value_raises(self) -> None:
		bad = ObjectiveSpec(name="bad", values=[1, 2.5], sense="maximize", weight=1.0)  # type: ignore[list-item]
		with self.assertRaises(ValueError):
			ObjectiveSpecValidation([bad])


if __name__ == "__main__":
	unittest.main()

