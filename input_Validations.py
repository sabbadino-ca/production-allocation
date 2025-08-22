"""Input validation utilities for production allocation.

This module contains functions to validate the structure and values of
plants and orders prior to building the CP-SAT allocation model.

Functions
---------
validate_input_data(plants, orders)
    Ensures required keys exist and that capacities / quantities are
    non-negative integers (rejecting non-integer floats), and dates are
    in YYYY-MM-DD format.
"""
from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from domain_types import Plant, Order
from allocation_types import WeightsConfig

__all__ = ["validate_plants", "validate_orders", "validate_input_data", "validate_settings_payload"]


def validate_plants(plants: List[Plant]) -> None:
  """Validate a list of plants.

  Args:
    plants: List of Plant dictionaries to validate.

  Raises:
    ValueError: If plant list or any plant entry is invalid.
  """
  if not isinstance(plants, list):
    raise ValueError("Plants data must be a list.")

  for plant in plants:
    if not all(k in plant for k in ("plantid", "plantfamily", "capacity", "allowedModels")):
      raise ValueError(f"Missing required plant fields in: {plant}")
    if not isinstance(plant["allowedModels"], list):
      raise ValueError(f"allowedModels must be a list in: {plant}")
    if len(plant["allowedModels"]) < 1:
      raise ValueError(f"allowedModels must contain at least one item in: {plant}")
    # Capacity integer & non-negative validation
    capacity_val = plant.get("capacity")
    if not isinstance(capacity_val, (int, float)):
      raise ValueError(f"Plant capacity must be numeric (plantid={plant.get('plantid')})")
    if isinstance(capacity_val, float) and not capacity_val.is_integer():
      raise ValueError(f"Plant capacity must be an integer (plantid={plant.get('plantid')} got {capacity_val})")
    if int(capacity_val) < 0:
      raise ValueError(f"Plant capacity must be >= 0 (plantid={plant.get('plantid')} got {capacity_val})")


def validate_orders(orders: List[Order]) -> None:
  """Validate a list of orders (and nested items).

  Args:
    orders: List of Order dictionaries to validate.

  Raises:
    ValueError: If order list, order entries, or item entries are invalid.
  """
  if not isinstance(orders, list):
    raise ValueError("Orders data must be a list.")

  for order in orders:
    if not all(k in order for k in ("order", "dueDate", "items")):
      raise ValueError(f"Missing required order fields in: {order}")
    # Check dueDate format
    try:
      datetime.strptime(order["dueDate"], "%Y-%m-%d")
    except Exception:
      raise ValueError(f"dueDate must be in yyyy-MM-dd format in: {order}")
    if not isinstance(order["items"], list):
      raise ValueError(f"Items must be a list in: {order}")
    for item in order["items"]:
      if not all(k in item for k in ("modelFamily", "model", "submodel", "quantity")):
        raise ValueError(f"Missing required item fields in: {item}")
      # Validate quantity is non-negative integer
      quantity = item.get("quantity", 0)
      if not isinstance(quantity, (int, float)):
        raise ValueError(f"Item quantity must be numeric but got {type(quantity)} in: {item}")
      if isinstance(quantity, float) and not quantity.is_integer():
        raise ValueError(f"Item quantity must be an integer (got {quantity}) in: {item}")
      if int(quantity) < 0:
        raise ValueError(f"Item quantity must be >= 0 but got {quantity} in: {item}")

def validate_input_data(
    plants: List[Plant],
    orders: List[Order],
    settings: WeightsConfig
) -> None:
  """Validate plants, orders, and optionally weights.

  Args:
    plants: Plants to validate.
    orders: Orders to validate.
    settings: Optional weights config (must contain w_quantity & w_due if provided).

  Raises:
    ValueError: If any structural validation fails or mandatory weight keys missing.
  """
  validate_plants(plants)
  validate_orders(orders)
  if settings is not None:
    validate_settings_payload(dict(settings))  # cast for type checker


def validate_settings_payload(data: dict) -> tuple[float, float]:
  """Validate settings JSON payload and extract weights.

  Args:
    data: Parsed JSON object expected to contain "w_quantity" and "w_due".

  Returns:
    Tuple (w_quantity, w_due) as non-negative floats.

  Raises:
    ValueError: If structure or values are invalid.
  """
  if not isinstance(data, dict):
    raise ValueError("Settings file must contain a JSON object.")
  missing = [k for k in ("w_quantity", "w_due") if k not in data]
  if missing:
    raise ValueError(f"Settings file missing keys: {missing}")
  try:
    w_quantity = float(data["w_quantity"])
    w_due = float(data["w_due"])
  except Exception:
    raise ValueError("w_quantity and w_due must be numeric.")
  if w_quantity < 0 or w_due < 0:
    raise ValueError("w_quantity and w_due must be non-negative.")
  # Optional horizon_days validation centralized here (must be >=1 if provided)
  if "horizon_days" in data:
    try:
      horizon_val = int(data["horizon_days"])
    except Exception:
      raise ValueError("horizon_days must be an integer >= 1")
    if horizon_val < 1:
      raise ValueError("horizon_days must be >= 1 (received 0)")
  return w_quantity, w_due
