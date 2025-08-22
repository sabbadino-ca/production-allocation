from collections import defaultdict
from typing import List, Dict

def group_by_model_names(indices: List[int], models: List[str], names: List[str]) -> Dict[str, List[str]]:
    """
    Groups item names by their model labels.

    Args:
        indices: List of indices to group.
        models: List of model labels for all items.
        names: List of item names for all items.

    Returns:
        Dictionary mapping model label to list of item names.
    """
    out = defaultdict(list)
    for i in indices:
        out[models[i]].append(names[i])
    return dict(out)
