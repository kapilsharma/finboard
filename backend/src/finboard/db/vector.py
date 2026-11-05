"""A minimal `vector(n)` column type for pgvector (ADR-0031), so the core install doesn't need
the pgvector Python package. Values go to Postgres as the text form `[0.1,0.2,...]`, cast to
vector in SQL; reads come back as lists of floats."""

from typing import Any

from sqlalchemy import cast
from sqlalchemy.types import Text, UserDefinedType


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_expression(self, bindvalue: Any) -> Any:
        return cast(cast(bindvalue, Text), self)

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            if len(value) != self.dimensions:
                raise ValueError(f"expected {self.dimensions} dimensions, got {len(value)}")
            return "[" + ",".join(repr(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: Any) -> list[float] | None:
            if value is None or isinstance(value, list):
                return value
            return [float(v) for v in str(value).strip("[]").split(",") if v]

        return process


def to_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"
