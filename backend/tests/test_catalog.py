"""Tests for datagen.catalog: item catalogs and GST rate slabs."""

from collections import Counter
from datetime import date

from datagen.catalog import CATALOG, CATEGORY_LABELS, GST_RATES_FROM_2_0, valid_gst_rates

EXPECTED_CATEGORIES = {
    "it_hardware", "it_services", "office_supplies", "packaging", "logistics",
    "facility_management", "raw_materials", "marketing_printing", "furniture", "electrical_maintenance",
}


def test_all_ten_categories_with_10_to_25_items():
    assert set(CATALOG) == EXPECTED_CATEGORIES == set(CATEGORY_LABELS)
    for category, items in CATALOG.items():
        assert 10 <= len(items) <= 25, category
        assert len({item.description for item in items}) == len(items), f"duplicate item in {category}"


def test_items_have_valid_gst_2_0_rates_and_price_ranges():
    for items in CATALOG.values():
        for item in items:
            assert item.gst_rate in GST_RATES_FROM_2_0, item
            assert 0 < item.price_min < item.price_max, item
            assert item.unit


def test_services_use_sac_and_goods_use_hsn():
    for items in CATALOG.values():
        for item in items:
            if item.is_service:
                assert item.hsn_sac.startswith("99") and len(item.hsn_sac) == 6, item
            else:
                assert not item.hsn_sac.startswith("99") and item.hsn_sac.isdigit(), item
    assert all(item.is_service for item in CATALOG["it_services"])
    assert all(item.hsn_sac.startswith("99") for item in CATALOG["it_services"])


def test_mostly_18_and_5_percent():
    rates = Counter(item.gst_rate for items in CATALOG.values() for item in items)
    assert rates[18.0] + rates[5.0] == sum(rates.values())
    assert rates[18.0] > rates[5.0] > 0


def test_valid_rates_change_with_gst_2_0():
    assert 12.0 in valid_gst_rates(date(2025, 9, 21))
    assert 28.0 in valid_gst_rates(date(2025, 9, 21))
    assert 12.0 not in valid_gst_rates(date(2025, 9, 22))
    assert 40.0 in valid_gst_rates(date(2025, 9, 22))
