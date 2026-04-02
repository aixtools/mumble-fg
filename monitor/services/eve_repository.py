from __future__ import annotations

from typing import Literal

from ..adapters.repositories import DjangoAuthRepository, DjangoCubeRepository
from ..models import EveRepository

AppType = Literal["AUTH", "CUBE"]


def get_repository(app: AppType, *, using: str = "default") -> EveRepository:
    """Factory for selecting the correct repository implementation."""
    if app == "AUTH":
        return DjangoAuthRepository(using=using)
    if app == "CUBE":
        return DjangoCubeRepository(using=using)
    raise ValueError(f"Unknown app type: {app}")
