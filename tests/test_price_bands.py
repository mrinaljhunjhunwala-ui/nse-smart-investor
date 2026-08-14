from analysis.price_bands import compute_quantile_thresholds, assign_band, normalize_within_bands


def test_quantile_thresholds_and_assignment():
    prices = [10, 12, 13, 15, 20, 22, 30, 40, 100]
    th = compute_quantile_thresholds(prices, n_bands=4)
    assert isinstance(th, list) and len(th) == 3

    # Rough sanity: thresholds non-decreasing
    assert th[0] <= th[1] <= th[2]

    # assign some known prices
    assert assign_band(10, th) >= 0
    assert assign_band(100, th) >= 0
    assert assign_band(None, th) == -1
    assert assign_band(float("nan"), th) == -1


def test_normalize_within_bands_sets_score_norm():
    res = [
        {"ticker": "A", "price": 10, "score": 50},
        {"ticker": "B", "price": 12, "score": 60},
        {"ticker": "C", "price": 40, "score": 30},
        {"ticker": "D", "price": 100, "score": 10},
    ]
    th = compute_quantile_thresholds([r["price"] for r in res], n_bands=4)
    for r in res:
        r["band"] = assign_band(r["price"], th)
    normalize_within_bands(res, band_key="band", score_key="score")
    for r in res:
        assert "score_norm" in r
        assert 0.0 <= r["score_norm"] <= 1.0
