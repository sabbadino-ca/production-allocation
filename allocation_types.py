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


class ZeroQuantityRow(TypedDict):
    """One input item whose requested quantity was 0 and thus excluded from modeling.

    Zero-quantity items are *never* modeled (no variables) and are reported
    separately from ``skipped`` (structural infeasibility) and ``unallocated``
    (modeled but not chosen). They do not contribute to demand or objective.
    """
    order: str
    order_index: int
    model: str
    submodel: str
    quantity: int  # always 0


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
    """Aggregated statistics about the modeled instance and solve status.

    Added fields (2025-08) for improved reconciliation transparency:
        total_input_items: Count of all items parsed from input orders (including zero-qty & those later skipped).
        allocated_items_count: Number of rows in allocations list.
        unallocated_items_count: Number of modeled items that remained unallocated.
        total_output_reported_items: allocations + skipped + unallocated lengths (coverage measure).
        missing_items_excluding_unallocated: total_input_items - (allocated_items_count + skipped_count);
            highlights items that disappeared because they were zero quantity or filtered out in logic but not classified.
        missing_items_count: total_input_items - (allocated_items_count + skipped_count + unallocated_items_count);
            should normally be 0; non‑zero indicates a reporting gap.
    """
    plants_count: int
    orders_count: int
    unique_models_count: int
    total_input_items: int
    total_capacity: int
    total_demand: int
    capacity_minus_demand: int
    skipped_count: int
    skipped_demand: int
    status: str
    allocated_items_count: int
    unallocated_items_count: int
    objective_components: ObjectiveComponents
    objective_bound_metrics: ObjectiveBoundMetrics
    total_allocated_quantity: int
    allocated_ratio: float
    total_output_reported_items: int
    missing_items_count: int
    zero_quantity_items_count: int
    plant_utilization: List["PlantUtilizationRow"]
    diagnostics: "Diagnostics"
    solver_parameters: "SolverParameters"


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
    """Result container for allocate().

    Keys:
        summary: Summary metrics (see Summary for detailed field list).
        allocations: Full-quantity placements.
        skipped: Items structurally omitted (no decision vars).
        unallocated: Modeled items not placed due to capacity competition.

    Note: Reconciliation fields now permit end-to-end item accounting.
    """
    summary: Summary
    allocations: List[AllocationRow]
    skipped: List[SkippedRow]
    unallocated: List[UnallocatedRow]
    zero_quantity_items: List[ZeroQuantityRow]


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
        max_time_seconds: Time limit for the CP-SAT solver wall clock (default 60).
    """
    horizon_days: int
    scale: int
    weight_precision: int
    max_time_seconds: float


class SolverParameters(TypedDict):
    """Subset of solver parameters we expose in output for transparency."""
    max_time_seconds: float