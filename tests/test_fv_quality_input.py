"""04_analyze_stock feeds FinalVerdict's quality_score from the fundamentals
analytics layer. Guard the contract: the analytics keys the page maps from
exist, and the mapped dict yields a real compute_quality_score value.
(Previously the page called a non-existent ``.to_metrics_dict()``, so
quality_score was always None.)
"""
import inspect
import pathlib

from analysis.fundamentals import analytics
from analysis.fundamentals.analytics import AnalyticResult
from analysis.portfolio_fundamentals import compute_quality_score

PAGE = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "04_analyze_stock.py"
KEY_MAP = {"roe": "roe", "roce": "roce", "revenue_cagr": "revenue_cagr_5y", "eps_cagr": "eps_cagr_5y"}


def test_page_uses_analytics_not_missing_method():
    src = PAGE.read_text(encoding="utf-8")
    assert "_fv_cf.to_metrics_dict()" not in src
    assert "compute_all(_fv_cf)" in src
    for k_src, k_dst in KEY_MAP.items():
        assert f'"{k_src}": "{k_dst}"' in src


def test_compute_all_emits_mapped_keys():
    body = inspect.getsource(analytics.compute_all)
    for k in KEY_MAP:
        assert f'"{k}"' in body


def test_mapped_metrics_produce_quality_score():
    an = {
        "roe": AnalyticResult("ROE", 15.0, "%", True, "high"),
        "roce": AnalyticResult("ROCE", 7.5, "%", True, "high"),
        "revenue_cagr": AnalyticResult("Revenue CAGR", None, "%", False, "low"),
        "eps_cagr": AnalyticResult("EPS CAGR", 20.0, "%", True, "high"),
    }
    metrics = {dst: r.value for src, dst in KEY_MAP.items()
               if (r := an[src]).available and r.value is not None}
    assert "revenue_cagr_5y" not in metrics
    qs = compute_quality_score(metrics)
    assert 0 < qs <= 100
