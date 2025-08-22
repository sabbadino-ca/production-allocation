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


class ObjectiveComponents(TypedDict):
    """Integer objective component breakdown (scaled)."""
    quantity_component: int
    due_component: int
    int_w_quantity: int
    int_w_due: int
    scale: int
    weight_precision: int


class ObjectiveBoundMetrics(TypedDict):
    """Solver-reported objective value and bound/gap metrics."""
    objective_value: float | None
    best_objective_bound: float | None
    gap_abs: float | None
    gap_rel: float | None


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
    objective_components: ObjectiveComponents
    objective_bound_metrics: ObjectiveBoundMetrics
    total_allocated_quantity: int
    allocated_ratio: float
    plant_utilization: List["PlantUtilizationRow"]
    diagnostics: "Diagnostics"


class PlantUtilizationRow(TypedDict):
    """Per-plant capacity usage diagnostic."""
    plantid: int
    capacity: int
    used_capacity: int
    utilization_pct: float


class Diagnostics(TypedDict):
    """Urgency-related diagnostic arrays for transparency."""
    item_days: List[int]
    normalized_urgencies: List[float]
    max_overdue_days: int
    horizon_days: int


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


class _WeightsConfigRequired(TypedDict):
    """Required weight keys.

    These are mandatory for building the objective.
    """
    w_quantity: float
    w_due: float


class WeightsConfig(_WeightsConfigRequired, total=False):
    """Weight configuration for objective components.

    Required:
        w_quantity: Weight applied to quantity component (>=0).
        w_due: Weight applied to due-date urgency component (>=0).
    Optional:
        horizon_days: Planning horizon for urgency decay (>=1, default 30).
        scale: Scaling factor for normalized components (default 1000).
        weight_precision: Integer precision multiplier for weights (default 1).
    """
    horizon_days: int
    scale: int
    weight_precision: int