"""
Data loading utilities for production allocation optimization.

Provides typed loaders that return domain-typed structures defined in
`domain_types` (Plant, Order, Item).
"""
import json
from typing import List, cast, Tuple, Any, Dict
import os
from domain_types import Plant, Order

def load_plants(path: str) -> List[Plant]:
    """Load plant info from JSON file.

    Args:
        path: Path to a JSON file containing a list of plants. Each element
              must include keys: "plantid" (int), "plantfamily" (str),
              "capacity" (int), and "allowedModels" (list[str]).

    Returns:
        A list of Plant-typed dictionaries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the JSON does not meet schema expectations.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Plants file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Plants data must be a list.")
    for plant in data:
        if not all(k in plant for k in ("plantid", "plantfamily", "capacity", "allowedModels")):
            raise ValueError(f"Missing required plant fields in: {plant}")
        if not isinstance(plant["allowedModels"], list):
            raise ValueError(f"allowedModels must be a list in: {plant}")
        if len(plant["allowedModels"]) < 1:
            raise ValueError(f"allowedModels must contain at least one item in: {plant}")
    return cast(List[Plant], data)

def load_orders(path: str) -> List[Order]:
    """Load orders from JSON file.

    Args:
        path: Path to a JSON file containing an object with an "orders" array,
              where each order has keys: "order" (str), "dueDate" (yyyy-MM-dd),
              and "items" (list[Item]).

    Returns:
        A list of Order-typed dictionaries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the JSON does not meet schema expectations or dates are invalid.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Orders file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if "orders" not in data or not isinstance(data["orders"], list):
        raise ValueError("Orders data must contain a list under 'orders' key.")
    from datetime import datetime
    for order in data["orders"]:
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
    return cast(List[Order], data["orders"])


def load_settings(path: str) -> Tuple[float, float]:
    """Load optimization weighting settings.

    Expects a JSON object containing at least the keys:
      - "w_quantity" (number >= 0)
      - "w_due" (number >= 0)

    Example JSON:
    {
      "w_quantity": 5.0,
      "w_due": 1.0
    }

    Args:
        path: Path to a JSON settings file.

    Returns:
        Tuple (w_quantity, w_due) as floats.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required keys are missing or invalid.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Settings file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data: Dict[str, Any] = json.load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse settings JSON: {e}")

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
    return w_quantity, w_due
