"""
Domain type definitions for production allocation.
"""
from __future__ import annotations

from typing import List, TypedDict


class Plant(TypedDict):
    plantid: int
    plantfamily: str
    capacity: int
    allowedModels: List[str]


class Item(TypedDict):
    modelFamily: str
    model: str
    submodel: str
    quantity: int


class Order(TypedDict):
    order: str
    dueDate: str  # yyyy-MM-dd
    items: List[Item]
