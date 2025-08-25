from typing import Iterable, List
from dataclasses import is_dataclass
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
