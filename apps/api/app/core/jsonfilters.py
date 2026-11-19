"""Portable predicates for JSON-encoded array columns.

SQLAlchemy's ``JSON.contains`` compiles to the ``@>`` operator only for
PostgreSQL ``JSONB``; the schema uses plain ``JSON``, where ``@>`` does not
exist. SQLite stores JSON as text and has no ``@>`` at all. This helper keeps
array-membership filters working identically on both backends.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import String, cast, literal
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement


def json_array_contains(db: Session, column: Any, value: str) -> ColumnElement[bool]:
    """Return a predicate matching rows whose JSON array column holds ``value``."""
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return cast(column, JSONB).op("@>")(cast(literal(json.dumps([value])), JSONB))
    # SQLite: the serialized token keeps the surrounding quotes, so ``"ab"``
    # never matches the stored token ``"a"``.
    return cast(column, String).contains(json.dumps(value))
