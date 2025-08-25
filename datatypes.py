# --------------------------- Per-item additive objective spec ---------------------------


from dataclasses import dataclass
from typing import List

@dataclass
class ObjectiveSpec:
    """
    Per-item additive objective: Score = sum over allocated items of values[i].

    Examples:
      - "fill":           values = [1, 1, ..., 1]             (maximize #items placed)
      - "due_date_boost": values = per-item in [0..100]        (maximize urgency)
      - "quantity":       values = per-item quantity (>=0)     (maximize total quantity)

    Attributes
    ----------
    name   : label for reporting (e.g., "fill")
    values : nonnegative ints, one per item (len(values) == #items)
    sense  : "maximize" or "minimize"
    weight : nonnegative float; combined with normalization to act as a slider
    """
    name: str
    values: List[int]
    sense: str
    weight: float = 1.0
