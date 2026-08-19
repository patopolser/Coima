"""
src/api/schemas/common.py - Shared Pydantic response models.
"""

from __future__ import annotations

from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    page: int
    total_pages: int
    total: int
    per_page: int
