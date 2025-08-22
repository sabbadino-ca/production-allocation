"""
Type definitions for production allocation results and related structures.
"""
from __future__ import annotations

from typing import List, TypedDict, Literal


class AllocationRow(TypedDict):
    """One non-zero allocation row in the result."""
    plantid: int
    order: str
    model: str
    submodel: str
    allocated_qty: int


class SkippedRow(TypedDict):
        """One item that was skipped during modeling and the reason why.

        Reasons:
            - no_compatible_plant: No plant can produce the item's model.
            - too_large_for_any_plant: Compatible plants exist but each capacity is
                smaller than the item's quantity (item is unsplittable).
        """
        order: str
        order_index: int
        model: str
        submodel: str
        quantity: int
        reason: Literal["no_compatible_plant", "too_large_for_any_plant"]


class Summary(TypedDict):
    """Aggregated statistics about the modeled instance and solve status."""
    plants_count: int
    orders_count: int
    unique_models_count: int
    total_capacity: int
    total_demand: int
    capacity_minus_demand: int
    skipped_count: int
    skipped_demand: int
    status: str
    objective_components: dict[str, int]


class UnallocatedRow(TypedDict):
    """One item that could not be placed due to capacity or packing limits."""
    order: str
    order_index: int
    model: str
    submodel: str
    requested_qty: int
    reason: Literal["insufficient_capacity"]


class AllocateResult(TypedDict):
    """Result container for allocate()."""
    summary: Summary
    allocations: List[AllocationRow]
    skipped: List[SkippedRow]
    unallocated: List[UnallocatedRow]