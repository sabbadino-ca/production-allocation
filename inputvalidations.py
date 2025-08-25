from typing import Iterable, List, Sequence
from datatypes import ObjectiveSpec


def ObjectiveSpecValidation(objectives: Iterable[ObjectiveSpec]) -> None:
	"""Validate that each ObjectiveSpec has integer values only.

	Parameters
	----------
	objectives : Iterable[ObjectiveSpec]
		Collection of additive objective specifications to validate.

	Raises
	------
	TypeError
		If any element is not an ObjectiveSpec or values is not a list-like of integers.
	ValueError
		If any value inside ObjectiveSpec.values is not an integer.
	"""
	for spec in objectives:
		if not isinstance(spec, ObjectiveSpec):
			raise TypeError("All objectives must be instances of ObjectiveSpec.")
		vals = spec.values
		# Allow any iterable but prefer list/tuple checks for performance
		if not isinstance(vals, (list, tuple)):
			try:
				vals = list(vals)
			except Exception as exc:
				raise TypeError("ObjectiveSpec.values must be an iterable of integers.") from exc
		# Check integer-ness strictly
		for idx, v in enumerate(vals):
			if not isinstance(v, int):
				raise ValueError(f"Objective '{spec.name}' has a non-integer value at index {idx}: {v!r}")


def validate_input(
	*,
	item_names: List[str],
	model_names: List[str],
	item_quantities: List[int],
	order_ids: List[str],
	plant_names: List[str],
	plant_quantity_capacities: List[int],
	allowed_model_names_per_plant: Sequence[Iterable[str]],
	additive_objectives: Iterable[ObjectiveSpec],
	min_allowed_qty_of_items_same_model_name_in_a_plant: int,
	soft_min_qty_of_items_same_model_name_in_a_plant: int,
) -> None:
	"""Validate all inputs for the CP-SAT optimizer.

	Parameters
	----------
	item_names : List[str]
		Unique identifiers for items (must be unique and match lengths).
	model_names : List[str]
		Model name per item, same length as item_names.
	item_quantities : List[int]
		Non-negative integer quantity per item, same length as item_names.
	order_ids : List[str]
		Order identifier per item (string), same length as item_names/model_names.
	plant_names : List[str]
		Plant labels (must be unique, aligned with capacities and allowed sets).
	plant_quantity_capacities : List[int]
		Strictly positive integer capacity per plant.
	allowed_model_names_per_plant : Sequence[Iterable[str]]
		For each plant, the set/iterable of model names it can produce.
	additive_objectives : Iterable[ObjectiveSpec]
		Collection of additive objective specs; each must have integer values.
	min_allowed_qty_of_items_same_model_name_in_a_plant : int
		Global hard minimum quantity per (model_name, plant); 0 disables.
	soft_min_qty_of_items_same_model_name_in_a_plant : int
		Global soft minimum quantity per (model_name, plant); 0 disables.

	Raises
	------
	AssertionError
		If core shape/type constraints fail (e.g., mismatched lengths, nonpositive capacities).
	ValueError
		If names are not unique or objective values are not integers.
	"""

	# Basic shape validations
	n = len(model_names)
	if not (len(item_names) == n and len(item_quantities) == n and len(order_ids) == n):
		raise AssertionError("item_names/model_names/item_quantities/order_ids mismatch")
	if len(set(item_names)) != n:
		raise ValueError("item_names must be unique.")

	# order_ids basic typing
	if not all(isinstance(oid, str) for oid in order_ids):
		raise AssertionError("order_ids must be a list of strings with length matching items")

	P = len(plant_quantity_capacities)
	if not (P > 0 and len(allowed_model_names_per_plant) == P and len(plant_names) == P):
		raise AssertionError("plant arrays must align")
	if len(set(plant_names)) != P:
		raise ValueError("plant_names must be unique.")

	# Types and ranges
	if not all(isinstance(c, int) and c > 0 for c in plant_quantity_capacities):
		raise AssertionError("plant capacities must be positive ints")
	if not all(isinstance(q, int) and q >= 0 for q in item_quantities):
		raise AssertionError("item quantities must be nonnegative ints")
	if not (isinstance(min_allowed_qty_of_items_same_model_name_in_a_plant, int) and min_allowed_qty_of_items_same_model_name_in_a_plant >= 0):
		raise AssertionError(
			"min_allowed_qty_of_items_same_model_name_in_a_plant must be a non-negative int"
		)
	if not (isinstance(soft_min_qty_of_items_same_model_name_in_a_plant, int) and soft_min_qty_of_items_same_model_name_in_a_plant >= 0):
		raise AssertionError(
			"soft_min_qty_of_items_same_model_name_in_a_plant must be a non-negative int"
		)

	# Objectives validation (ensures integer values)
	ObjectiveSpecValidation(additive_objectives)

	# Validate allowed models per plant
	for p_idx, models in enumerate(allowed_model_names_per_plant):
		# Disallow passing a single string directly
		if isinstance(models, (str, bytes)):
			raise TypeError(
				f"allowed_model_names_per_plant[{p_idx}] must be an iterable of strings, not a string."
			)
		try:
			lst = list(models)
		except Exception as exc:
			raise TypeError(
				f"allowed_model_names_per_plant[{p_idx}] must be an iterable of strings."
			) from exc
		# Non-empty requirement
		if len(lst) == 0:
			raise ValueError(
				f"allowed models for plant '{plant_names[p_idx]}' must be non-empty."
			)
		# All entries must be strings and non-blank
		for j, m in enumerate(lst):
			if not isinstance(m, str):
				raise TypeError(
					f"allowed model at plant '{plant_names[p_idx]}' index {j} must be str, got {type(m).__name__}."
				)
			if m.strip() == "":
				raise ValueError(
					f"allowed model at plant '{plant_names[p_idx]}' index {j} must not be empty/blank."
				)
		# Duplicates check (preserve case-sensitivity as-is)
		if len(set(lst)) != len(lst):
			raise ValueError(
				f"allowed models for plant '{plant_names[p_idx]}' contain duplicates: {lst}"
			)
