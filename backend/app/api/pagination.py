"""Shared pagination helpers."""
from typing import Any, TypeVar
from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page(BaseModel):
    items: list[Any]
    total: int
    skip: int
    limit: int
    has_more: bool


def pagination_params(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max records to return"),
) -> dict[str, int]:
    return {"skip": skip, "limit": limit}


def paginate(items: list[Any], total: int, skip: int, limit: int) -> Page:
    return Page(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=(skip + len(items)) < total,
    )
