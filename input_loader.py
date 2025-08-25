from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence, Tuple
import json
from datetime import datetime, date


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


def load_items_arrays(items_file: str | Path) -> Tuple[List[str], List[str], List[int], List[int], List[str]]:
	"""Load items from JSON and produce arrays for the optimizer, including due date boosts and order IDs.

	Parameters
	----------
	items_file : str | Path
		Path to a JSON file shaped like inputs/items_to_be_allocated-1.json:
		{
		  "orders": [
		    { "order": "...", "dueDate": "YYYY-MM-DD", "items": [
		        {"modelFamily": "...", "model": "...", "submodel": "...", "quantity": int}, ...
		    ]}
		  ]
		}

		Returns
		-------
		Tuple[List[str], List[str], List[int], List[int], List[str]]
				- item_names: unique item labels
				- model_names: per item, as "{modelFamily}_{model}_{submodel}"
				- item_quantities: per item quantity (int)
				- due_date_boosts: per item integer boost in [0, 100], linearly mapped from due dates
					with 100 when due date is 100 days overdue (now - 100), 0 when due date is 100 days ahead (now + 100),
					and 50 when due date is today.
				- order_ids: per item order identifier (stringified), matching the order's "order" field

	Raises
	------
	FileNotFoundError
		If the given file path does not exist.
	ValueError
		If the JSON structure or dates are invalid.
	"""
	path = Path(items_file)
	if not path.exists():
		raise FileNotFoundError(f"items file not found: {path}")

	with path.open("r", encoding="utf-8") as f:
		try:
			data = json.load(f)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid JSON in items file: {path}") from exc

	orders = data.get("orders") if isinstance(data, dict) else None
	if not isinstance(orders, list):
		raise ValueError("Items JSON must have key 'orders' as a list.")

	def _parse_date(d: str) -> date:
		try:
			return datetime.strptime(d, "%Y-%m-%d").date()
		except Exception as exc:
			raise ValueError(f"Invalid dueDate format (expected YYYY-MM-DD): {d!r}") from exc

	def _boost_for_due(due: date, today: date) -> int:
		days = (due - today).days
		# clamp to [-100, 100]
		if days < -100:
			days = -100
		elif days > 100:
			days = 100
		# linear map: overdue -100 -> 100, today -> 50, ahead +100 -> 0
		# Equivalent formula: boost = ((-days + 100) / 200) * 100
		boost = ((-days + 100) / 200.0) * 100.0
		return int(round(boost))

	today = date.today()
	item_names: List[str] = []
	model_names: List[str] = []
	item_quantities: List[int] = []
	due_date_boosts: List[int] = []
	order_ids: List[str] = []

	seq = 0
	for oi, order in enumerate(orders):
		if not isinstance(order, dict):
			raise ValueError(f"Order at index {oi} must be an object.")
		due_str = order.get("dueDate")
		if not isinstance(due_str, str):
			raise ValueError(f"Order at index {oi} missing valid 'dueDate'.")
		due = _parse_date(due_str)
		boost_val = _boost_for_due(due, today)

		items = order.get("items")
		if not isinstance(items, list):
			raise ValueError(f"Order at index {oi} must have 'items' list.")

		# Normalize order id to string; tolerate missing by using empty string
		ord_id_raw = order.get("order")
		ord_id = str(ord_id_raw) if ord_id_raw is not None else ""

		for ii, it in enumerate(items):
			if not isinstance(it, dict):
				raise ValueError(f"Item at order {oi} index {ii} must be an object.")
			fam = it.get("modelFamily")
			mod = it.get("model")
			sub = it.get("submodel")
			qty = it.get("quantity")
			if not isinstance(fam, str) or not isinstance(mod, str) or not isinstance(sub, str):
				raise ValueError(f"Item at order {oi} index {ii} must have string fields modelFamily/model/submodel.")
			if qty is None:
				raise ValueError(f"Item at order {oi} index {ii} missing 'quantity'.")
			if not isinstance(qty, int):
				try:
					qty = int(qty)
				except Exception as exc:
					raise ValueError(f"Item at order {oi} index {ii} has non-integer quantity: {qty!r}.") from exc

			# Build model name as family_model, but tolerate empty parts by trimming underscores
			model_name = f"{fam}_{mod}".strip("_")
			item_name = f"{model_name}_{sub}#{seq}"
			seq += 1

			item_names.append(item_name)
			model_names.append(model_name)
			item_quantities.append(qty)
			due_date_boosts.append(boost_val)
			order_ids.append(ord_id)

	return item_names, model_names, item_quantities, due_date_boosts, order_ids
