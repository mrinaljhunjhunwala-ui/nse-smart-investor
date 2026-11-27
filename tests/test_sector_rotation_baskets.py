"""Sector-rotation baskets are built from data/universe, not typed by hand."""
from data.universe import NIFTY50_OFFICIAL, get_sector
from strategies.sector_rotation import BASKET_SIZE, SECTORS


def test_baskets_follow_the_main_sector_list():
    assert "Other" not in SECTORS and len(SECTORS) >= 20
    for sector, names in SECTORS.items():
        assert 1 <= len(names) <= BASKET_SIZE, sector
        assert all(get_sector(t) == sector for t in names), sector


def test_biggest_companies_come_first():
    assert SECTORS["Banking"][0] in NIFTY50_OFFICIAL
    assert "HDFCBANK.NS" in SECTORS["Banking"]
