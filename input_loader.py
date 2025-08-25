from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence, Tuple
import json


def load_plants_arrays(plants_file: str | Path) -> Tuple[List[str], List[int], List[List[str]]]:
	"""Load plant data from a JSON file and return arrays expected by the optimizer.

	Parameters
	----------
	plants_file : str | Path
		Path to the JSON file containing a list of plant objects with keys:
		- "plant_name": str
		- "plant_quantity_capacity": int
		- "allowedModels": list[str]

	Returns
	-------
	Tuple[List[str], List[int], List[List[str]]]
		- plant_names: list of plant labels (as strings)
		- plant_quantity_capacities: list of capacities per plant (ints)
		- allowed_model_names_per_plant: list of lists of allowed model names per plant

	Raises
	------
	FileNotFoundError
		If the given file path does not exist.
	ValueError
		If the JSON structure is invalid or missing required keys.
	"""
	path = Path(plants_file)
	if not path.exists():
		raise FileNotFoundError(f"plants file not found: {path}")

	with path.open("r", encoding="utf-8") as f:
		try:
			data = json.load(f)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid JSON in plants file: {path}") from exc

	if not isinstance(data, list):
		raise ValueError("Plants JSON must be a list of objects.")

	plant_names: List[str] = []
	plant_quantity_capacities: List[int] = []
	allowed_model_names_per_plant: List[List[str]] = []

	for idx, obj in enumerate(data):
		if not isinstance(obj, dict):
			raise ValueError(f"Plant entry at index {idx} must be an object.")
		if "plant_name" not in obj or "plant_quantity_capacity" not in obj or "allowedModels" not in obj:
			raise ValueError(
				f"Plant entry at index {idx} missing required keys ('plant_name', 'plant_quantity_capacity', 'allowedModels')."
			)

		name = str(obj["plant_name"])  # normalize to str
		cap_raw = obj["plant_quantity_capacity"]
		if not isinstance(cap_raw, int):
			try:
				cap = int(cap_raw)
			except Exception as exc:
				raise ValueError(f"Capacity for plant '{name}' must be an integer; got {cap_raw!r}.") from exc
		else:
			cap = cap_raw

		models_raw = obj["allowedModels"]
		if isinstance(models_raw, (str, bytes)):
			raise ValueError(f"allowedModels for plant '{name}' must be a list of strings, not a string.")
		try:
			models_list = list(models_raw)
		except Exception as exc:
			raise ValueError(f"allowedModels for plant '{name}' must be an iterable of strings.") from exc

		plant_names.append(name)
		plant_quantity_capacities.append(cap)
		allowed_model_names_per_plant.append(models_list)

	return plant_names, plant_quantity_capacities, allowed_model_names_per_plant
