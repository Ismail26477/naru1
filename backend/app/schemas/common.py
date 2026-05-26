"""Common Pydantic response wrappers and helpers."""
from pydantic import BaseModel, Field, ConfigDict
from typing import Generic, TypeVar, Optional
from datetime import datetime, date
import uuid

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
