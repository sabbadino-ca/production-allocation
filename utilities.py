# --------------------------- Utilities ---------------------------
from typing import Sequence, List, Dict
from collections import defaultdict

def _fractional_knapsack_ub(values: Sequence[int], quantities: Sequence[int], capacity: int) -> float: # type: ignore
    """
    Capacity-aware UB used to normalize additive objectives.
    Supports zero-quantity items:
      - Items with quantity==0 contribute their full value "for free".
      - Positive-quantity items use a fractional-knapsack bound.

    Returns a float upper bound on the maximum achievable sum of 'values'
    subject to 'quantities' and total capacity.
    """
    if capacity < 0 or not values:
        return 0.0

    # Free contribution: quantity == 0
    free = sum(v for v, q in zip(values, quantities) if q == 0 and v > 0)

    # Fractional part: quantity > 0
    pos = [(v, q) for v, q in zip(values, quantities) if q > 0 and v > 0]
    if not pos:
        return float(free)

    # Sort by value/quantity ratio descending
    pos.sort(key=lambda vq: vq[0] / vq[1], reverse=True)

    cap = float(capacity)
    ub = 0.0
    for v, q in pos:
        if cap <= 0:
            break
        take = min(cap, q)
        ub += v * (take / q)
        cap -= take

    return float(free) + ub


def _group_names_by_model_name(indices: List[int], model_names: List[str], names: List[str]) -> Dict[str, List[str]]:
    """Helper for reporting: group item names by their model_name."""
    out = defaultdict(list)
    for i in indices: # type: ignore
        out[model_names[i]].append(names[i])
    return dict(out)
