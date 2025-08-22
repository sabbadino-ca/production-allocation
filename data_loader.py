"""Data loading utilities.

This module now performs *only* file existence checks and JSON parsing.
All structural / semantic validation of plants, orders, and settings has
been moved to the dedicated validation functions in ``input_Validations``.

Design choice
-------------
Separating parsing from validation keeps I/O concerns (file reading &
deserialization) decoupled from business rules. Tests that assert error
conditions for malformed content must now explicitly call the validation
functions (``validate_plants`` / ``validate_orders``) after loading.
"""
import json
from typing import List, cast, Any, Dict
import os
from domain_types import Plant, Order

__all__ = ["load_plants", "load_orders", "load_settings"]

def load_plants(path: str) -> List[Plant]:
    """Load plants JSON file without performing structural validation.

    Only responsibilities:
      * Check that the file exists.
      * Parse JSON content.
      * Return the raw list (cast) – may be invalid until validated separately.

    Args:
        path: Path to a JSON file expected to contain a list of plants.

    Returns:
        Parsed JSON cast to ``List[Plant]`` (no guarantees about schema).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If JSON parsing fails.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Plants file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse plants JSON: {e}")
    # Intentionally no structural checks here; caller should invoke validate_plants.
    return cast(List[Plant], data)

def load_orders(path: str) -> List[Order]:
    """Load orders JSON file without structural validation.

    Behavior:
      * Checks file existence.
      * Parses JSON.
      * If top-level object contains an ``orders`` key, returns that value;
        otherwise, if the top-level itself is a list, returns it directly.
      * No date / field / type checks are performed here.

    Args:
        path: Path to a JSON file containing either a list of orders or an
              object with an ``orders`` list.

    Returns:
        Parsed list of orders (possibly unvalidated) cast to ``List[Order]``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If JSON parsing fails.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Orders file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse orders JSON: {e}")
    if isinstance(data, dict) and "orders" in data:
        orders_raw = data["orders"]
    else:
        orders_raw = data  # could already be a list
    return cast(List[Order], orders_raw)


def load_settings(path: str) -> Any:
    """Load settings JSON file (no validation).

    Args:
        path: Path to a JSON settings file.

    Returns:
        Parsed JSON object (dict or other JSON type) as-is.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If JSON parsing fails.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Settings file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data: Dict[str, Any] = json.load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse settings JSON: {e}")
    return data
