"""Shared API schemas for sport modules."""
from pydantic import BaseModel, Field


class BatchDeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
