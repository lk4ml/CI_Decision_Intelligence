"""Shared router dependencies: DB session and X-Actor / X-Role headers (Addendum A #10)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

from app.db import get_session  # noqa: F401  (re-export)
from app.models import ROLES

DEFAULT_ROLE = "Reviewer"  # missing X-Role => read-only (safety review #4)


@dataclass
class Who:
    actor: str
    role: str


def who(x_actor: Optional[str] = Header(default=None), x_role: Optional[str] = Header(default=None)) -> Who:
    role = x_role or DEFAULT_ROLE
    if role not in ROLES:
        raise HTTPException(400, f"Unknown X-Role {role!r}; expected one of {ROLES}")
    return Who(actor=x_actor or "anonymous", role=role)
