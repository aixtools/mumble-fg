from __future__ import annotations

import atexit
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from ..models import EveItemPrice, EveItemStack, EveItemValuation
from .item_price_cache import (
    DjangoModelItemPriceCacheBackend,
    EveItemPriceCacheBackend,
    JsonFileItemPriceCacheBackend,
    NoopItemPriceCacheBackend,
)

_CACHE_BACKENDS: dict[str, EveItemPriceCacheBackend] = {}
_CACHE_BACKENDS_LOCK = threading.Lock()
_CACHE_ATEXIT_REGISTERED = False


def _monitor_user_agent() -> str:
    try:
        return f"monitor/{package_version('monitor')}"
    except PackageNotFoundError:
        return "monitor/unknown"


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


def _chunks(values: tuple[int, ...], size: int) -> Iterable[tuple[int, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _normalize_type_ids(type_ids: Iterable[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for type_id in type_ids:
        parsed = _to_int(type_id)
        if parsed is not None and parsed > 0:
            normalized.add(parsed)
    return tuple(sorted(normalized))


class EvePricingMethod(Protocol):
    """A method that can return per-type unit prices in ISK."""

    name: str

    def fetch_unit_prices(
        self,
        type_ids: Iterable[int],
        *,
        market: int | str | None = None,
    ) -> Mapping[int, float]:
        ...


class JanicePricingMethod:
    """Preferred pricing method using Janice REST API."""

    name = "janice"
    DEFAULT_BASE_URL = "https://janice.e-351.com/api/rest/v2"
    EXAMPLE_API_KEY = "FAKE-JANICE-API-KEY-EXAMPLE-0000"
    VALID_PRICING = frozenset({"buy", "split", "sell", "purchase"})
    VALID_VARIANTS = frozenset({"immediate", "top5percent"})
    VALID_DAYS = frozenset({0, 1, 5, 30})
    MARKET_IDS = {
        "jita": 2,
        "r1o-gn": 3,
        "perimeter": 4,
        "jitameter": 5,
        "npc": 6,
        "t5zi-s": 113,
        "mj-5f9": 114,
        "amarr": 115,
        "rens": 116,
        "dodixie": 117,
        "hek": 118,
        "e8-432": 119,
        "r-ag7w": 120,
    }

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        default_market: int | str | None = "jita",
        default_pricing: str = "sell",
        default_variant: str = "immediate",
        default_days: int | str = 0,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key:
            raise ValueError("Janice API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_market = default_market
        self.default_pricing = self._resolve_pricing(default_pricing)
        self.default_variant = self._resolve_variant(default_variant)
        self.default_days = self._resolve_days(default_days)
        self.timeout_seconds = timeout_seconds

    def _resolve_pricing(self, pricing: str | None) -> str:
        value = str(pricing or "sell").strip().lower()
        if value not in self.VALID_PRICING:
            raise ValueError(f"Unknown Janice pricing: {pricing}")
        return value

    def _resolve_variant(self, variant: str | None) -> str:
        value = str(variant or "immediate").strip().lower()
        if value not in self.VALID_VARIANTS:
            raise ValueError(f"Unknown Janice pricing variant: {variant}")
        return value

    def _resolve_days(self, days: int | str | None) -> int:
        parsed = _to_int(days)
        if parsed is None:
            parsed = 0
        if parsed not in self.VALID_DAYS:
            raise ValueError(
                f"Unknown Janice days value: {days} (allowed: 0, 1, 5, 30)"
            )
        return parsed

    def _resolve_market_id(self, market: int | str | None) -> int:
        value = self.default_market if market is None else market
        if isinstance(value, int):
            return value
        if value is None:
            return self.MARKET_IDS["jita"]
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        market_id = self.MARKET_IDS.get(text.lower())
        if market_id is None:
            raise ValueError(f"Unknown Janice market: {value}")
        return market_id

    @staticmethod
    def _instant_keys_for_pricing(pricing: str) -> tuple[str, ...]:
        if pricing == "buy":
            return ("buyPrice", "buy")
        if pricing == "sell":
            return ("sellPrice", "sell")
        if pricing == "purchase":
            return ("buyPrice", "buy")
        # split has no guaranteed instant key; degrade to buy/sell candidates.
        return ("splitPrice", "sellPrice", "buyPrice", "sell", "buy")

    def _pick_unit_price(
        self,
        row: Mapping[str, object],
        *,
        pricing: str,
        variant: str,
        days: int,
    ) -> float | None:
        if days in (0, 1):
            price_map_key = (
                "top5percentPrices" if variant == "top5percent" else "immediatePrices"
            )
            nested = row.get(price_map_key)
            if isinstance(nested, Mapping):
                for key in self._instant_keys_for_pricing(pricing):
                    candidate = _to_float(nested.get(key))
                    if candidate is not None:
                        return candidate
            # Fallback for payloads that flatten immediate fields.
            for key in self._instant_keys_for_pricing(pricing):
                candidate = _to_float(row.get(key))
                if candidate is not None:
                    return candidate

        if days in (5, 30):
            candidate = _to_float(row.get(f"{pricing}Price{days}DayMedian"))
            if candidate is not None:
                return candidate

        # Final compatibility fallback for older responses.
        for key in (
            "sellPriceMin",
            "buyPriceMax",
            "sellPrice",
            "buyPrice",
            "price",
        ):
            candidate = _to_float(row.get(key))
            if candidate is not None:
                return candidate
        return None

    @classmethod
    def verify(
        cls,
        *,
        api_key: str | None,
        market: int | str | None = "2",
        pricing: str = "sell",
        variant: str = "immediate",
        days: int | str = 0,
        timeout_seconds: float = 12.0,
    ) -> tuple[bool, str | None]:
        key = str(api_key or "").strip()
        if not key or key == cls.EXAMPLE_API_KEY:
            return False, "no key configured"
        try:
            method = cls(
                api_key=key,
                default_market=market,
                default_pricing=pricing,
                default_variant=variant,
                default_days=days,
                timeout_seconds=timeout_seconds,
            )
            prices = method.fetch_unit_prices((34,), market=market)
        except Exception as exc:
            return False, str(exc)
        if not prices:
            return False, "empty response for probe type"
        return True, None

    def fetch_unit_prices(
        self,
        type_ids: Iterable[int],
        *,
        market: int | str | None = None,
    ) -> Mapping[int, float]:
        normalized = _normalize_type_ids(type_ids)
        if not normalized:
            return {}

        market_id = self._resolve_market_id(market)
        pricing = self.default_pricing
        variant = self.default_variant
        days = self.default_days
        payload = "\n".join(str(type_id) for type_id in normalized).encode("utf-8")
        query = urllib.parse.urlencode(
            {
                "market": market_id,
                "pricing": pricing,
                "pricingVariant": variant,
            }
        )
        request = urllib.request.Request(
            f"{self.base_url}/pricer?{query}",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/json",
                "X-ApiKey": self.api_key,
                "User-Agent": _monitor_user_agent(),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")
            data = json.loads(body)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Janice HTTP error: {exc.code} {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Janice URL error: {reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Janice request timed out") from exc
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            raise RuntimeError(f"Janice response parse error: {exc}") from exc

        if not isinstance(data, list):
            return {}

        prices: dict[int, float] = {}
        for row in data:
            if not isinstance(row, Mapping):
                continue
            item_type = row.get("itemType")
            type_id = None
            if isinstance(item_type, Mapping):
                type_id = _to_int(item_type.get("eid"))
            if type_id is None:
                type_id = _to_int(row.get("type_id"))
            if type_id is None:
                continue
            price = self._pick_unit_price(
                row,
                pricing=pricing,
                variant=variant,
                days=days,
            )
            if price is None:
                continue
            prices[type_id] = price
        return prices


class MemberauditPricingMethod:
    """Fallback pricing method from EveUniverse market prices table."""

    name = "memberaudit"
    QUERY_VARIANTS = (
        ("eveuniverse_evemarketprice", "eve_type_id"),
        ("eveuniverse_evemarketprice", "id"),
        ("eveuniverse_eve_market_price", "eve_type_id"),
        ("eveuniverse_eve_market_price", "id"),
    )

    def __init__(self, *, using: str = "default") -> None:
        self.using = using

    def _query_variant(
        self,
        *,
        table_name: str,
        column_name: str,
        type_ids: tuple[int, ...],
    ) -> Mapping[int, float]:
        from django.db import connections

        placeholders = ", ".join(["%s"] * len(type_ids))
        statement = (
            f"SELECT {column_name} AS type_id, average_price "
            f"FROM {table_name} WHERE {column_name} IN ({placeholders})"
        )
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(statement, list(type_ids))
            rows = cursor.fetchall()
        prices: dict[int, float] = {}
        for type_id, average_price in rows:
            parsed_type_id = _to_int(type_id)
            parsed_price = _to_float(average_price)
            if parsed_type_id is None or parsed_price is None:
                continue
            prices[parsed_type_id] = parsed_price
        return prices

    def fetch_unit_prices(
        self,
        type_ids: Iterable[int],
        *,
        market: int | str | None = None,
    ) -> Mapping[int, float]:
        _ = market
        normalized = _normalize_type_ids(type_ids)
        if not normalized:
            return {}

        prices: dict[int, float] = {}
        for batch in _chunks(normalized, 500):
            batch_prices: dict[int, float] = {}
            for table_name, column_name in self.QUERY_VARIANTS:
                try:
                    batch_prices = dict(
                        self._query_variant(
                            table_name=table_name,
                            column_name=column_name,
                            type_ids=batch,
                        )
                    )
                    break
                except Exception:
                    continue
            prices.update(batch_prices)
        return prices


@dataclass(frozen=True)
class EveItemPricer:
    """Attempts preferred pricing first, then fills misses from fallback."""

    preferred: EvePricingMethod | None = None
    fallback: EvePricingMethod | None = None
    cache_backend: EveItemPriceCacheBackend | None = None
    cache_ttl_seconds: int = 3600

    @staticmethod
    def _market_cache_key(market: int | str | None) -> str:
        if market is None:
            return "-"
        return str(market).strip() or "-"

    def price_items(
        self,
        items: Iterable[EveItemStack],
        *,
        market: int | str | None = None,
    ) -> EveItemValuation:
        item_rows = tuple(items)
        if not item_rows:
            return EveItemValuation()

        unresolved = set(_normalize_type_ids(item.type_id for item in item_rows))
        preferred_prices: dict[int, float] = {}
        fallback_prices: dict[int, float] = {}
        attempted: list[str] = []
        market_key = self._market_cache_key(market)
        ttl_seconds = max(1, int(self.cache_ttl_seconds))

        if self.preferred is not None and unresolved:
            attempted.append(self.preferred.name)
            if self.cache_backend is not None:
                cached = self.cache_backend.get_many(
                    method=self.preferred.name,
                    market_key=market_key,
                    type_ids=unresolved,
                    max_age_seconds=ttl_seconds,
                )
                for type_id, price in cached.items():
                    parsed_type_id = _to_int(type_id)
                    if parsed_type_id is None:
                        continue
                    preferred_prices[parsed_type_id] = float(price)
                unresolved.difference_update(preferred_prices.keys())
            fetched_preferred: dict[int, float] = {}
            if unresolved:
                try:
                    for type_id, price in self.preferred.fetch_unit_prices(
                        unresolved,
                        market=market,
                    ).items():
                        parsed_type_id = _to_int(type_id)
                        if parsed_type_id is None:
                            continue
                        fetched_preferred[parsed_type_id] = float(price)
                except Exception:
                    fetched_preferred = {}
            preferred_prices.update(fetched_preferred)
            if self.cache_backend is not None and fetched_preferred:
                self.cache_backend.set_many(
                    method=self.preferred.name,
                    market_key=market_key,
                    prices=fetched_preferred,
                )
            unresolved.difference_update(preferred_prices.keys())

        if self.fallback is not None and unresolved:
            attempted.append(self.fallback.name)
            if self.cache_backend is not None:
                cached = self.cache_backend.get_many(
                    method=self.fallback.name,
                    market_key=market_key,
                    type_ids=unresolved,
                    max_age_seconds=ttl_seconds,
                )
                for type_id, price in cached.items():
                    parsed_type_id = _to_int(type_id)
                    if parsed_type_id is None:
                        continue
                    fallback_prices[parsed_type_id] = float(price)
                unresolved.difference_update(fallback_prices.keys())
            fetched_fallback: dict[int, float] = {}
            if unresolved:
                try:
                    for type_id, price in self.fallback.fetch_unit_prices(
                        unresolved,
                        market=market,
                    ).items():
                        parsed_type_id = _to_int(type_id)
                        if parsed_type_id is None:
                            continue
                        fetched_fallback[parsed_type_id] = float(price)
                except Exception:
                    fetched_fallback = {}
            fallback_prices.update(fetched_fallback)
            if self.cache_backend is not None and fetched_fallback:
                self.cache_backend.set_many(
                    method=self.fallback.name,
                    market_key=market_key,
                    prices=fetched_fallback,
                )
            unresolved.difference_update(fallback_prices.keys())

        price_rows: list[EveItemPrice] = []
        for item in item_rows:
            unit_price = preferred_prices.get(item.type_id)
            method = self.preferred.name if unit_price is not None else ""
            if unit_price is None:
                unit_price = fallback_prices.get(item.type_id)
                method = self.fallback.name if unit_price is not None else ""
            if unit_price is None:
                continue
            price_rows.append(
                EveItemPrice(
                    item=item,
                    method=method,
                    market=market,
                    unit_price_isk=float(unit_price),
                )
            )

        return EveItemValuation(
            prices=tuple(price_rows),
            unpriced_type_ids=tuple(sorted(unresolved)),
            attempted_methods=tuple(attempted),
        )


def flush_item_price_caches() -> None:
    """Flush all registered price cache backends."""

    with _CACHE_BACKENDS_LOCK:
        backends = tuple(_CACHE_BACKENDS.values())
    for backend in backends:
        try:
            backend.flush()
        except Exception:
            continue


def clear_item_price_caches(*, cache_file: str | None = None) -> None:
    """Clear in-memory and JSON-file price caches."""

    with _CACHE_BACKENDS_LOCK:
        backends = tuple(_CACHE_BACKENDS.values())
        _CACHE_BACKENDS.clear()

    json_paths: set[Path] = set()
    for backend in backends:
        if isinstance(backend, JsonFileItemPriceCacheBackend):
            json_paths.add(Path(backend.file_path))

    explicit = str(cache_file or os.getenv("ITEM_PRICE_CACHE_FILE") or "").strip()
    if explicit:
        json_paths.add(Path(explicit))
    if not json_paths:
        json_paths.add(Path("/var/tmp/monitor-item-price-cache.json"))

    for path in json_paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue
        try:
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.unlink(missing_ok=True)
        except Exception:
            continue


def _ensure_cache_atexit_registered() -> None:
    global _CACHE_ATEXIT_REGISTERED
    with _CACHE_BACKENDS_LOCK:
        if _CACHE_ATEXIT_REGISTERED:
            return
        atexit.register(flush_item_price_caches)
        _CACHE_ATEXIT_REGISTERED = True


def _cache_backend_key(
    *,
    backend_name: str,
    using: str,
    cache_path: str | None,
    ttl_seconds: int,
) -> str:
    normalized_path = str(Path(cache_path).resolve()) if cache_path else "-"
    return f"{backend_name}|{using}|{normalized_path}|{ttl_seconds}"


def _build_cache_backend(
    *,
    backend_name: str,
    using: str,
    cache_path: str | None,
    ttl_seconds: int,
) -> EveItemPriceCacheBackend:
    if backend_name == "none":
        return NoopItemPriceCacheBackend(default_ttl_seconds=ttl_seconds)
    if backend_name == "django":
        return DjangoModelItemPriceCacheBackend(
            using=using,
            default_ttl_seconds=ttl_seconds,
        )
    resolved_path = cache_path or "/var/tmp/monitor-item-price-cache.json"
    return JsonFileItemPriceCacheBackend(
        file_path=str(Path(resolved_path)),
        default_ttl_seconds=ttl_seconds,
    )


def _get_or_create_cache_backend(
    *,
    backend_name: str,
    using: str,
    cache_path: str | None,
    ttl_seconds: int,
) -> EveItemPriceCacheBackend:
    key = _cache_backend_key(
        backend_name=backend_name,
        using=using,
        cache_path=cache_path,
        ttl_seconds=ttl_seconds,
    )
    with _CACHE_BACKENDS_LOCK:
        existing = _CACHE_BACKENDS.get(key)
        if existing is not None:
            return existing
        backend = _build_cache_backend(
            backend_name=backend_name,
            using=using,
            cache_path=cache_path,
            ttl_seconds=ttl_seconds,
        )
        _CACHE_BACKENDS[key] = backend
    _ensure_cache_atexit_registered()
    return backend


def build_default_item_pricer(
    *,
    using: str = "default",
    janice_api_key: str | None = None,
    janice_market: int | str | None = None,
    janice_pricing: str | None = None,
    janice_variant: str | None = None,
    janice_days: int | str | None = None,
    cache_backend: EveItemPriceCacheBackend | None = None,
    cache_backend_name: str | None = None,
    cache_file: str | None = None,
    cache_ttl_seconds: int | None = None,
) -> EveItemPricer:
    """Build default Janice-first pricer with memberaudit fallback and cache."""

    api_key = (
        janice_api_key
        or os.getenv("JANICE_API_KEY")
        or os.getenv("JANICE_API_KEY")
    )
    ttl_seconds = (
        int(cache_ttl_seconds)
        if cache_ttl_seconds is not None
        else int(os.getenv("ITEM_PRICE_CACHE_TTL_SECONDS", "3600"))
    )
    ttl_seconds = max(1, ttl_seconds)

    selected_cache_backend = cache_backend
    if selected_cache_backend is None:
        backend_name = (
            cache_backend_name
            or os.getenv("ITEM_PRICE_CACHE_BACKEND", "json")
        ).strip().lower()
        cache_path = cache_file or os.getenv(
            "ITEM_PRICE_CACHE_FILE",
            "/var/tmp/monitor-item-price-cache.json",
        )
        selected_cache_backend = _get_or_create_cache_backend(
            backend_name=backend_name,
            using=using,
            cache_path=cache_path,
            ttl_seconds=ttl_seconds,
        )

    preferred = None
    if api_key:
        preferred = JanicePricingMethod(
            api_key=api_key,
            default_market=janice_market or os.getenv("JANICE_MARKET", "2"),
            default_pricing=janice_pricing or os.getenv("JANICE_PRICING", "sell"),
            default_variant=janice_variant or os.getenv("JANICE_VARIANT", "immediate"),
            default_days=(
                janice_days
                if janice_days is not None
                else os.getenv("JANICE_DAYS", "0")
            ),
        )
    fallback = MemberauditPricingMethod(using=using)
    return EveItemPricer(
        preferred=preferred,
        fallback=fallback,
        cache_backend=selected_cache_backend,
        cache_ttl_seconds=ttl_seconds,
    )
