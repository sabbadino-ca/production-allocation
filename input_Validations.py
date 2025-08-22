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

from typing import List
from datetime import datetime
from domain_types import Plant, Order

__all__ = ["validate_input_data"]

def validate_input_data(plants: List[Plant], orders: List[Order]) -> None:
  """Validate input data for plants and orders.

  Args:
    plants: List of Plant dictionaries to validate.
    orders: List of Order dictionaries to validate.

  Raises:
    ValueError: If data does not meet schema expectations.

  Rules enforced (integer policy update):
    - Plant capacity must be a non-negative integer (floats that are not whole
      numbers are rejected).
    - Item quantity must be a non-negative integer (floats that are not whole
      numbers are rejected).
  """
  # Validate plants data
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

  # Validate orders data  
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
