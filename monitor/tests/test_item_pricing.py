from __future__ import annotations

import unittest
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from tempfile import TemporaryDirectory
from typing import Iterable, Mapping
from unittest.mock import patch

from monitor.models import EveAssetItem, EveItemBasket, EveItemStack, EveItemType
from monitor.services.item_price_cache import JsonFileItemPriceCacheBackend
from monitor.services.item_pricing import EveItemPricer, JanicePricingMethod


@dataclass
class _StubPricingMethod:
    name: str
    prices: Mapping[int, float]
    last_market: int | str | None = None
    last_type_ids: tuple[int, ...] = ()
    call_count: int = 0

    def fetch_unit_prices(
        self,
        type_ids: Iterable[int],
        *,
        market: int | str | None = None,
    ) -> Mapping[int, float]:
        self.call_count += 1
        requested = tuple(sorted({int(type_id) for type_id in type_ids}))
        self.last_market = market
        self.last_type_ids = requested
        return {
            type_id: price
            for type_id, price in self.prices.items()
            if type_id in requested
        }


class TestEveItemObjects(unittest.TestCase):
    def test_asset_item_and_basket(self) -> None:
        row = {
            "source_pk": 10,
            "character_id": 90000001,
            "item_id": 777,
            "type_id": 34,
            "type_name": "Tritanium",
            "group_id": 18,
            "quantity": 3200,
            "is_blueprint_copy": False,
            "location_id": 60003760,
            "location_name": "Jita IV - Moon 4",
        }
        item = EveAssetItem.from_record(
            row,
            source_app="AUTH",
            source_model="memberaudit.asset",
            raw=row,
        )
        self.assertEqual(item.type_id, 34)
        self.assertEqual(item.type_name, "Tritanium")
        self.assertEqual(item.display_name, "Tritanium")
        self.assertEqual(item.location_name, "Jita IV - Moon 4")

        basket = EveItemBasket(
            source_app="AUTH",
            source_model="memberaudit.asset_basket",
            source_pk=90000001,
            character_id=90000001,
            items=(item,),
        )
        self.assertEqual(basket.item_count, 1)
        self.assertEqual(basket.total_quantity, 3200)
        self.assertEqual(basket.unique_type_count, 1)


class TestEveItemPricer(unittest.TestCase):
    def test_preferred_then_fallback(self) -> None:
        type_a = EveItemType(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=1,
            id=34,
            name="Tritanium",
        )
        type_b = EveItemType(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=2,
            id=35,
            name="Pyerite",
        )
        item_a = EveItemStack(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=11,
            character_id=90000001,
            item_type=type_a,
            quantity=1000,
        )
        item_b = EveItemStack(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=12,
            character_id=90000001,
            item_type=type_b,
            quantity=100,
        )
        preferred = _StubPricingMethod(name="janice", prices={34: 5.0})
        fallback = _StubPricingMethod(name="memberaudit", prices={35: 8.0})
        pricer = EveItemPricer(preferred=preferred, fallback=fallback)

        result = pricer.price_items((item_a, item_b), market="jita")

        self.assertEqual(preferred.last_type_ids, (34, 35))
        self.assertEqual(fallback.last_type_ids, (35,))
        self.assertEqual(result.attempted_methods, ("janice", "memberaudit"))
        self.assertEqual(len(result.prices), 2)
        self.assertAlmostEqual(result.total_estimated_isk, 5800.0)
        self.assertEqual(result.unpriced_type_ids, ())

    def test_unpriced_types_returned(self) -> None:
        item_type = EveItemType(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=1,
            id=23911,
            name="Skiff",
        )
        item = EveItemStack(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=11,
            character_id=90000001,
            item_type=item_type,
            quantity=1,
        )
        pricer = EveItemPricer(
            preferred=_StubPricingMethod(name="janice", prices={}),
            fallback=_StubPricingMethod(name="memberaudit", prices={}),
        )

        result = pricer.price_items((item,))

        self.assertEqual(len(result.prices), 0)
        self.assertEqual(result.unpriced_type_ids, (23911,))

    def test_uses_cache_before_remote_lookup(self) -> None:
        type_a = EveItemType(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=1,
            id=34,
            name="Tritanium",
        )
        item_a = EveItemStack(
            source_app="AUTH",
            source_model="memberaudit.asset",
            source_pk=11,
            character_id=90000001,
            item_type=type_a,
            quantity=1000,
        )
        with TemporaryDirectory() as tmpdir:
            cache = JsonFileItemPriceCacheBackend(
                file_path=f"{tmpdir}/item-prices.json",
                default_ttl_seconds=3600,
            )
            cache.set_many(
                method="janice",
                market_key="jita",
                prices={34: 7.0},
            )
            preferred = _StubPricingMethod(name="janice", prices={34: 99.0})
            pricer = EveItemPricer(
                preferred=preferred,
                fallback=None,
                cache_backend=cache,
                cache_ttl_seconds=3600,
            )

            result = pricer.price_items((item_a,), market="jita")

            self.assertEqual(preferred.call_count, 0)
            self.assertEqual(len(result.prices), 1)
            self.assertAlmostEqual(result.prices[0].unit_price_isk, 7.0)

    def test_json_cache_flush_persists_to_restart(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/item-prices.json"
            cache = JsonFileItemPriceCacheBackend(
                file_path=path,
                default_ttl_seconds=3600,
                max_pending_entries=1000,
            )
            cache.set_many(
                method="memberaudit",
                market_key="-",
                prices={34: 5.5},
            )
            cache.flush()

            cache2 = JsonFileItemPriceCacheBackend(
                file_path=path,
                default_ttl_seconds=3600,
                max_pending_entries=1000,
            )
            got = cache2.get_many(
                method="memberaudit",
                market_key="-",
                type_ids=(34,),
                max_age_seconds=3600,
            )
            self.assertEqual(got, {34: 5.5})


class _DummyUrlopenResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")
        self.status = 200
        self.reason = "OK"

    def __enter__(self) -> "_DummyUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = (exc_type, exc, tb)
        return False

    def read(self) -> bytes:
        return self._body


class TestJanicePricingMethod(unittest.TestCase):
    def test_verify_returns_no_key(self) -> None:
        ok, error = JanicePricingMethod.verify(api_key=None, market=2)
        self.assertFalse(ok)
        self.assertEqual(error, "no key configured")

    def test_verify_returns_exception_message(self) -> None:
        with patch.object(
            JanicePricingMethod,
            "fetch_unit_prices",
            side_effect=RuntimeError("Janice HTTP error: 403 Forbidden"),
        ):
            ok, error = JanicePricingMethod.verify(api_key="k", market=2)
        self.assertFalse(ok)
        self.assertEqual(error, "Janice HTTP error: 403 Forbidden")

    def test_verify_returns_success(self) -> None:
        with patch.object(
            JanicePricingMethod,
            "fetch_unit_prices",
            return_value={34: 4.2},
        ):
            ok, error = JanicePricingMethod.verify(api_key="k", market=2)
        self.assertTrue(ok)
        self.assertIsNone(error)

    def test_sets_monitor_user_agent_with_version(self) -> None:
        captured: dict[str, object] = {}

        def _fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _DummyUrlopenResponse(
                '[{"itemType":{"eid":34},"immediatePrices":{"sellPrice":4.2}}]'
            )

        with (
            patch("monitor.services.item_pricing.package_version", return_value="0.3.2.dev0"),
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            method = JanicePricingMethod(
                api_key="k",
                default_market=2,
                default_pricing="sell",
                default_variant="immediate",
                default_days=0,
            )
            prices = method.fetch_unit_prices((34,), market=2)

        self.assertEqual(prices, {34: 4.2})
        request = captured["request"]
        self.assertEqual(request.get_header("User-agent"), "monitor/0.3.2.dev0")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("X-apikey"), "k")
        self.assertIn("market=2", request.full_url)
        self.assertIn("pricing=sell", request.full_url)
        self.assertIn("pricingVariant=immediate", request.full_url)

    def test_user_agent_fallback_when_version_unavailable(self) -> None:
        captured: dict[str, object] = {}

        def _fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _DummyUrlopenResponse(
                '[{"itemType":{"eid":34},"immediatePrices":{"sellPrice":4.2}}]'
            )

        with (
            patch(
                "monitor.services.item_pricing.package_version",
                side_effect=PackageNotFoundError,
            ),
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            method = JanicePricingMethod(api_key="k", default_market=2)
            method.fetch_unit_prices((34,), market=2)

        request = captured["request"]
        self.assertEqual(request.get_header("User-agent"), "monitor/unknown")

    def test_uses_30_day_field_when_configured(self) -> None:
        with patch(
            "urllib.request.urlopen",
            return_value=_DummyUrlopenResponse(
                '[{"itemType":{"eid":34},"sellPrice30DayMedian":7.25}]'
            ),
        ):
            method = JanicePricingMethod(
                api_key="k",
                default_market=2,
                default_pricing="sell",
                default_variant="immediate",
                default_days=30,
            )
            prices = method.fetch_unit_prices((34,), market=2)
        self.assertEqual(prices, {34: 7.25})

    def test_day_1_aliases_to_immediate(self) -> None:
        with patch(
            "urllib.request.urlopen",
            return_value=_DummyUrlopenResponse(
                '[{"itemType":{"eid":34},"immediatePrices":{"sellPrice":4.2}}]'
            ),
        ):
            method = JanicePricingMethod(
                api_key="k",
                default_market=2,
                default_pricing="sell",
                default_variant="immediate",
                default_days=1,
            )
            prices = method.fetch_unit_prices((34,), market=2)
        self.assertEqual(prices, {34: 4.2})


if __name__ == "__main__":
    unittest.main()
