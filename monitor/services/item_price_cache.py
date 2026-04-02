from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterable, Mapping, Protocol


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_type_ids(type_ids: Iterable[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for type_id in type_ids:
        parsed = _to_int(type_id)
        if parsed is not None and parsed > 0:
            normalized.add(parsed)
    return tuple(sorted(normalized))


class EveItemPriceCacheBackend(Protocol):
    """Abstract unit-price cache backend."""

    default_ttl_seconds: int

    def get_many(
        self,
        *,
        method: str,
        market_key: str,
        type_ids: Iterable[int],
        max_age_seconds: int | None = None,
    ) -> Mapping[int, float]:
        ...

    def set_many(
        self,
        *,
        method: str,
        market_key: str,
        prices: Mapping[int, float],
    ) -> None:
        ...

    def flush(self) -> None:
        ...


class NoopItemPriceCacheBackend:
    """No-op cache backend."""

    def __init__(self, *, default_ttl_seconds: int = 3600) -> None:
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))

    def get_many(
        self,
        *,
        method: str,
        market_key: str,
        type_ids: Iterable[int],
        max_age_seconds: int | None = None,
    ) -> Mapping[int, float]:
        _ = method, market_key, type_ids, max_age_seconds
        return {}

    def set_many(
        self,
        *,
        method: str,
        market_key: str,
        prices: Mapping[int, float],
    ) -> None:
        _ = method, market_key, prices

    def flush(self) -> None:
        return


class JsonFileItemPriceCacheBackend:
    """JSON-file cache backend with TTL semantics."""

    schema_version = 1

    def __init__(
        self,
        *,
        file_path: str,
        default_ttl_seconds: int = 3600,
        max_pending_entries: int = 100,
    ) -> None:
        self.file_path = Path(file_path)
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))
        self._max_pending_entries = max(1, int(max_pending_entries))
        self._lock = threading.Lock()
        self._pending_entries: dict[str, dict[str, object]] = {}

    @staticmethod
    def _entry_key(*, method: str, market_key: str, type_id: int) -> str:
        return f"{method}|{market_key}|{type_id}"

    def _read_unlocked(self) -> dict[str, object]:
        if not self.file_path.exists():
            return {"schema_version": self.schema_version, "entries": {}}
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return {"schema_version": self.schema_version, "entries": {}}
        if not isinstance(payload, dict):
            return {"schema_version": self.schema_version, "entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def _write_unlocked(self, payload: dict[str, object]) -> None:
        payload["schema_version"] = self.schema_version
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.file_path)

    def _flush_unlocked(self) -> None:
        if not self._pending_entries:
            return
        payload = self._read_unlocked()
        entries = payload.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            payload["entries"] = entries
        entries.update(self._pending_entries)
        payload["updated_at"] = int(time.time())
        self._write_unlocked(payload)
        self._pending_entries.clear()

    def get_many(
        self,
        *,
        method: str,
        market_key: str,
        type_ids: Iterable[int],
        max_age_seconds: int | None = None,
    ) -> Mapping[int, float]:
        normalized = _normalize_type_ids(type_ids)
        if not normalized:
            return {}

        ttl_seconds = (
            self.default_ttl_seconds
            if max_age_seconds is None
            else max(1, int(max_age_seconds))
        )
        now_epoch = int(time.time())

        with self._lock:
            payload = self._read_unlocked()
            entries = payload.get("entries", {})
            if not isinstance(entries, dict):
                return {}
            if self._pending_entries:
                entries = {**entries, **self._pending_entries}
            out: dict[int, float] = {}
            for type_id in normalized:
                key = self._entry_key(
                    method=method,
                    market_key=market_key,
                    type_id=type_id,
                )
                row = entries.get(key)
                if not isinstance(row, dict):
                    continue
                updated_at = _to_int(row.get("updated_at"))
                if updated_at is None:
                    continue
                if now_epoch - updated_at > ttl_seconds:
                    continue
                unit_price = _to_float(row.get("unit_price_isk"))
                if unit_price is None:
                    continue
                out[type_id] = unit_price
        return out

    def set_many(
        self,
        *,
        method: str,
        market_key: str,
        prices: Mapping[int, float],
    ) -> None:
        if not prices:
            return
        now_epoch = int(time.time())
        with self._lock:
            for raw_type_id, raw_price in prices.items():
                type_id = _to_int(raw_type_id)
                unit_price = _to_float(raw_price)
                if type_id is None or unit_price is None:
                    continue
                key = self._entry_key(
                    method=method,
                    market_key=market_key,
                    type_id=type_id,
                )
                self._pending_entries[key] = {
                    "unit_price_isk": float(unit_price),
                    "updated_at": now_epoch,
                }
            if len(self._pending_entries) >= self._max_pending_entries:
                self._flush_unlocked()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()


class DjangoModelItemPriceCacheBackend:
    """
    Django-model cache backend.

    This is the integration-ready backend for the future DB model.
    It currently degrades to no-op when the configured model is unavailable.
    """

    def __init__(
        self,
        *,
        model_label: str = "monitor.EveItemPriceCacheRecord",
        using: str = "default",
        default_ttl_seconds: int = 3600,
    ) -> None:
        self.model_label = model_label
        self.using = using
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))

    def _get_model(self):
        try:
            from django.apps import apps
        except Exception:
            return None
        try:
            return apps.get_model(self.model_label)
        except Exception:
            return None

    def get_many(
        self,
        *,
        method: str,
        market_key: str,
        type_ids: Iterable[int],
        max_age_seconds: int | None = None,
    ) -> Mapping[int, float]:
        model = self._get_model()
        if model is None:
            return {}
        normalized = _normalize_type_ids(type_ids)
        if not normalized:
            return {}
        ttl_seconds = (
            self.default_ttl_seconds
            if max_age_seconds is None
            else max(1, int(max_age_seconds))
        )
        try:
            from django.utils import timezone
        except Exception:
            return {}
        cutoff = timezone.now() - timezone.timedelta(seconds=ttl_seconds)
        try:
            rows = model.objects.using(self.using).filter(
                method=method,
                market_key=market_key,
                type_id__in=list(normalized),
                updated_at__gte=cutoff,
            )
        except Exception:
            return {}
        out: dict[int, float] = {}
        for row in rows:
            type_id = _to_int(getattr(row, "type_id", None))
            unit_price = _to_float(getattr(row, "unit_price_isk", None))
            if type_id is None or unit_price is None:
                continue
            out[type_id] = unit_price
        return out

    def set_many(
        self,
        *,
        method: str,
        market_key: str,
        prices: Mapping[int, float],
    ) -> None:
        if not prices:
            return
        model = self._get_model()
        if model is None:
            return
        try:
            from django.utils import timezone
        except Exception:
            return
        now = timezone.now()
        for raw_type_id, raw_price in prices.items():
            type_id = _to_int(raw_type_id)
            unit_price = _to_float(raw_price)
            if type_id is None or unit_price is None:
                continue
            try:
                model.objects.using(self.using).update_or_create(
                    method=method,
                    market_key=market_key,
                    type_id=type_id,
                    defaults={"unit_price_isk": unit_price, "updated_at": now},
                )
            except Exception:
                continue

    def flush(self) -> None:
        return
