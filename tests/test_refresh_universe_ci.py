"""tools/refresh_universe.py --ci: diff / rename / guard logic with fixture CSVs.

Offline: fetch, publish (git + gh) and Telegram are all stubbed. Fixtures use
NSE's documented constituent-CSV shape:
    Company Name,Industry,Symbol,Series,ISIN Code
"""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from data import universe
from tools import refresh_universe as ru

TODAY = dt.date(2026, 11, 15)  # a Sunday
NSE_HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def _nse_csv(rows):
    """rows: [(symbol, company)] -> NSE constituent CSV text."""
    body = "".join(f"{c},Financial Services,{s},EQ,INE{i:09d}\n" for i, (s, c) in enumerate(rows))
    return NSE_HEADER + body


def _tier_rows(n_per_tier=20):
    """{tier: [(sym, company)]} — disjoint symbols per tier, 120 in total."""
    return {tier: [(f"{tier[:3]}{i:02d}", f"{tier.title()} Company {i} Ltd.") for i in range(n_per_tier)]
            for tier, _ in ru.TIERS}


def _fetched(tiers):
    return {t: ru.parse_index_csv(_nse_csv(rows)) for t, rows in tiers.items()}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Committed CSV + meta in tmp; Telegram + publish captured."""
    out, meta = tmp_path / "const.csv", tmp_path / "const.meta.json"
    base = _tier_rows()
    ru.write(ru.build(_fetched(base)), path=str(out), meta_path=str(meta), today=TODAY - dt.timedelta(days=7))
    sent, published = [], []
    monkeypatch.setattr(ru, "notify", lambda text: sent.append(text))

    def fake_publish(branch, title, body, paths):
        published.append({"branch": branch, "title": title, "body": body, "paths": paths})
        return "77"

    def run(tiers=None, fetch=None, today=TODAY):
        fetch = fetch or (lambda: _fetched(tiers))
        return ru.run_ci(today=today, fetch=fetch, publish_fn=fake_publish,
                         out_path=str(out), meta_path=str(meta))

    return {"out": out, "meta": meta, "base": base, "sent": sent, "published": published, "run": run}


def _copy(base):
    return {t: list(rows) for t, rows in base.items()}


def test_no_change_exits_zero_without_writing(repo, capsys):
    before = repo["out"].read_bytes(), repo["meta"].read_bytes()
    assert repo["run"](_copy(repo["base"])) == 0
    assert "universe unchanged" in capsys.readouterr().out
    assert (repo["out"].read_bytes(), repo["meta"].read_bytes()) == before
    assert repo["published"] == []
    assert repo["sent"] == ["Universe check: unchanged"]


def test_unchanged_but_old_check_restamps_meta_only(repo, capsys):
    csv_before = repo["out"].read_bytes()
    assert repo["run"](_copy(repo["base"]), today=TODAY + dt.timedelta(days=30)) == 0
    assert "universe unchanged" in capsys.readouterr().out
    assert repo["out"].read_bytes() == csv_before
    meta = json.loads(repo["meta"].read_text())
    assert meta["checked"] == (TODAY + dt.timedelta(days=30)).isoformat()
    assert meta["refreshed"] == (TODAY - dt.timedelta(days=7)).isoformat()
    assert len(repo["published"]) == 1 and "re-stamped" in repo["sent"][-1]


def test_additions_open_pr_with_table(repo):
    tiers = _copy(repo["base"])
    tiers["MIDCAP150"] += [("NEWCO", "Brand New Industries Ltd."), ("FRESH", "Fresh Foods Ltd.")]
    assert repo["run"](tiers) == 0
    rows = ru.load_existing(str(repo["out"]))
    assert {"NEWCO", "FRESH"} <= {r["Symbol"] for r in rows}
    pub = repo["published"][0]
    assert pub["branch"] == "auto/universe-2026-11-15"
    assert "### Added (2)" in pub["body"] and "| NEWCO | Brand New Industries Ltd. | MIDCAP150 |" in pub["body"]
    assert repo["sent"][-1] == "Universe check: +2 added (FRESH, NEWCO), −0 removed, PR #77"
    meta = json.loads(repo["meta"].read_text())
    assert meta["refreshed"] == meta["checked"] == "2026-11-15" and meta["count"] == 122


def test_removals_open_pr(repo):
    tiers = _copy(repo["base"])
    tiers["SMALLCAP250"] = tiers["SMALLCAP250"][2:]   # drop SMA00, SMA01 (118/120 > 90%)
    assert repo["run"](tiers) == 0
    syms = {r["Symbol"] for r in ru.load_existing(str(repo["out"]))}
    assert "SMA00" not in syms and "SMA01" not in syms
    assert "### Removed (2)" in repo["published"][0]["body"]
    assert repo["sent"][-1] == "Universe check: +0 added, −2 removed (SMA00, SMA01), PR #77"


def test_rename_pair_detected(repo):
    tiers = _copy(repo["base"])
    # Same company, new symbol (suffix/punctuation noise must not matter).
    old_sym, company = tiers["NEXT50"][3]
    tiers["NEXT50"][3] = ("NXTNEW", company.replace(" Ltd.", " Limited"))
    d = ru.diff(ru.build(_fetched(repo["base"])), ru.build(_fetched(tiers)))
    assert d["renamed"] == [(old_sym, "NXTNEW")]
    assert d["added"] == [] and d["removed"] == []
    assert repo["run"](tiers) == 0
    assert "### Renamed" in repo["published"][0]["body"]
    assert f"1 renamed ({old_sym}→NXTNEW)" in repo["sent"][-1]


def test_ambiguous_company_name_is_not_a_rename():
    old = [{"Symbol": "AAA", "Company": "Twin Ltd.", "Industry": "", "Index": "NIFTY50"}]
    new = [{"Symbol": "BBB", "Company": "Twin Ltd", "Industry": "", "Index": "NIFTY50"},
           {"Symbol": "CCC", "Company": "Twin Limited", "Industry": "", "Index": "NIFTY50"}]
    d = ru.diff(old, new)
    assert d["renamed"] == [] and d["removed"] == ["AAA"] and d["added"] == ["BBB", "CCC"]


def test_too_small_list_fails_and_writes_nothing(repo):
    before = repo["out"].read_bytes(), repo["meta"].read_bytes()
    tiers = _copy(repo["base"])
    tiers["TOTALMARKET"] = tiers["TOTALMARKET"][:5]   # 105/120 = 87.5% < 90%
    assert repo["run"](tiers) != 0
    assert (repo["out"].read_bytes(), repo["meta"].read_bytes()) == before
    assert repo["published"] == []
    assert repo["sent"][-1].startswith("Universe check FAILED: fetched 105 symbols")


def test_fetch_failure_fails_and_writes_nothing(repo):
    before = repo["out"].read_bytes(), repo["meta"].read_bytes()

    def broken_download(name):
        return None if "smallcap" in name else _nse_csv([("X", "X Ltd.")])

    assert repo["run"](fetch=lambda: ru.fetch_all(download=broken_download, pause=0,
                                                  api=lambda tier: [])) != 0
    assert (repo["out"].read_bytes(), repo["meta"].read_bytes()) == before
    assert repo["published"] == []
    assert "FAILED: could not fetch SMALLCAP250" in repo["sent"][-1]
    assert "NSE index API backup also failed" in repo["sent"][-1]


def _api_payload(index_name, rows):
    """NSE equity-stockIndices JSON: the index row first, then constituents."""
    data = [{"symbol": index_name, "priority": 1}]
    data += [{"symbol": s, "series": "EQ", "meta": {"companyName": c, "industry": "Financial Services"}}
             for s, c in rows]
    return {"name": index_name, "data": data}


def test_parse_index_api_skips_index_row_dummies_and_non_eq():
    payload = _api_payload("NIFTY 50", [("AAA", "Aaa Ltd."), ("DUMMYX", "Dummy")])
    payload["data"].append({"symbol": "BBB", "series": "SM", "meta": {"companyName": "Bbb"}})
    rows = ru.parse_index_api(payload, "NIFTY 50")
    assert rows == [{"Symbol": "AAA", "Company": "Aaa Ltd.", "Industry": "Financial Services"}]


def test_api_backup_fills_a_tier_the_csv_hosts_refuse(repo):
    """22 Nov 2026: both CSV hosts answered 403 for Nifty 50 from GitHub Actions."""
    base = repo["base"]
    csv_by_name = {names[0]: _nse_csv(base[tier]) for tier, names in ru.TIERS}
    api_calls = []

    def download(name):
        return None if name == "ind_nifty50list.csv" else csv_by_name.get(name)

    def api(tier):
        api_calls.append(tier)
        return ru.parse_index_api(_api_payload(ru.API_INDEX[tier], base[tier]), ru.API_INDEX[tier])

    fetched = ru.fetch_all(download=download, pause=0, api=api)
    assert api_calls == ["NIFTY50"]
    assert [r["Symbol"] for r in fetched["NIFTY50"]] == [s for s, _ in base["NIFTY50"]]
    assert repo["run"](fetch=lambda: fetched) == 0
    assert repo["published"] == [] and repo["sent"][-1] == "Universe check: unchanged"


def test_api_index_covers_every_tier():
    assert set(ru.API_INDEX) == {tier for tier, _ in ru.TIERS}


def test_publish_failure_is_non_zero(repo):
    def boom(*a, **k):
        raise RuntimeError("gh: label not found")
    tiers = _copy(repo["base"])
    tiers["NIFTY50"].append(("ZZNEW", "Zz New Ltd."))
    rc = ru.run_ci(today=TODAY, fetch=lambda: _fetched(tiers), publish_fn=boom,
                   out_path=str(repo["out"]), meta_path=str(repo["meta"]))
    assert rc != 0 and "could not open the PR" in repo["sent"][-1]


def test_notify_never_raises(monkeypatch):
    import utils.telegram as tg

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no telegram")
    monkeypatch.setattr(tg, "TelegramAlerter", Boom)
    ru.notify("Universe check: unchanged")   # must not raise


def test_committed_csv_round_trips_byte_for_byte():
    # The CI write must not churn the committed file (line endings, order).
    with open(ru.OUT_PATH, encoding="utf-8", newline="") as f:
        assert ru.render_csv(ru.load_existing()) == f.read()


# ── data.universe staleness guard ────────────────────────────────────────────

def _meta(tmp_path, **kw):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(kw))
    return str(p)


def test_stale_warning_fresh_and_stale(tmp_path):
    p = _meta(tmp_path, refreshed="2026-09-01", checked="2026-10-20")
    assert universe.stale_universe_warning(today=dt.date(2026, 11, 10), meta_path=p) is None
    msg = universe.stale_universe_warning(today=dt.date(2026, 12, 10), meta_path=p)
    assert msg and "51 days ago" in msg and "20 Oct 2026" in msg


def test_stale_warning_degrades_without_meta(tmp_path):
    assert universe.stale_universe_warning(meta_path=str(tmp_path / "missing.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert universe.stale_universe_warning(meta_path=str(bad)) is None


def test_committed_meta_is_readable():
    assert os.path.isfile(universe._CONSTITUENTS_META)
    assert universe.universe_refresh_date() is not None


# ── removed / renamed symbols stay resolvable ────────────────────────────────
def test_update_former_records_removed_and_renamed(tmp_path):
    path = tmp_path / "former.json"
    d = {"removed": ["GONE"], "renamed": [("OLDCO", "NEWCO")], "added": ["FRESH"]}
    assert ru.update_former(d, ["NEWCO", "FRESH", "KEEP"], path=str(path), today=TODAY) is True
    assert json.loads(path.read_text()) == {"removed": {"GONE": "2026-11-15"}, "renamed": {"OLDCO": "NEWCO"}}
    assert ru.update_former(d, ["NEWCO", "FRESH", "KEEP"], path=str(path), today=TODAY) is False   # no change
    # GONE re-enters the universe a week later: it is no longer "former"; the first date is kept otherwise
    later = TODAY + dt.timedelta(days=7)
    assert ru.update_former({"removed": ["OTHER"], "renamed": []}, ["GONE", "NEWCO"], path=str(path),
                            today=later) is True
    assert json.loads(path.read_text()) == {"removed": {"OTHER": "2026-11-22"}, "renamed": {"OLDCO": "NEWCO"}}
    # a symbol first seen as removed, then detected as a rename, moves to renamed
    assert ru.update_former({"removed": [], "renamed": [("OTHER", "OTHER2")]}, ["OTHER2"], path=str(path),
                            today=later) is True
    got = json.loads(path.read_text())
    assert got["removed"] == {} and got["renamed"] == {"OLDCO": "NEWCO", "OTHER": "OTHER2"}


def test_run_ci_publishes_the_former_file_with_the_refresh(repo, tmp_path):
    former = tmp_path / "former.json"
    tiers = _copy(repo["base"])
    first_tier = next(iter(tiers))
    dropped = tiers[first_tier].pop(0)[0]
    out, meta = repo["out"], repo["meta"]
    published = []
    rc = ru.run_ci(today=TODAY, fetch=lambda: _fetched(tiers),
                   publish_fn=lambda b, t, body, paths: published.append(paths) or "78",
                   out_path=str(out), meta_path=str(meta), former_path=str(former))
    assert rc == 0 and len(published[0]) == 3 and published[0][2].endswith("former.json")
    assert json.loads(former.read_text())["removed"] == {dropped: "2026-11-15"}
    # the default run on temp paths (no former_path) must not touch the real file
    before = open(ru.FORMER_PATH, encoding="utf-8").read()
    assert repo["run"](tiers=_copy(repo["base"])) == 0
    assert open(ru.FORMER_PATH, encoding="utf-8").read() == before


def test_universe_resolves_removed_and_renamed_symbols(tmp_path, monkeypatch):
    path = tmp_path / "former.json"
    path.write_text(json.dumps({"removed": {"GONECO": "2026-11-15"}, "renamed": {"OLDSYM": "TCS", "OLDER": "OLDSYM"}}))
    removed, renamed = universe.load_former_symbols(str(path))
    assert removed == ["GONECO"] and renamed == {"OLDSYM": "TCS", "OLDER": "OLDSYM"}
    assert universe.load_former_symbols(str(tmp_path / "missing.json")) == ([], {})
    (tmp_path / "bad.json").write_text("not json")
    assert universe.load_former_symbols(str(tmp_path / "bad.json")) == ([], {})
    monkeypatch.setattr(universe, "RENAMED_SYMBOLS", renamed)
    monkeypatch.setattr(universe, "FORMER_CONSTITUENTS", universe.FORMER_CONSTITUENTS + ["GONECO.NS"])
    monkeypatch.setattr(universe, "_NAME_MAP", {})
    assert universe.resolve_ticker("GONECO") == "GONECO.NS"
    assert universe.resolve_ticker("OLDSYM") == "TCS.NS" and universe.resolve_ticker("OLDER") == "TCS.NS"
    monkeypatch.setattr(universe, "_NAME_MAP", {})               # rebuilt from the real lists afterwards


def test_committed_former_file_covers_the_15_nov_refresh():
    removed, renamed = universe.load_former_symbols()
    assert {"CCAVENUE", "ICICIPRULI"} <= set(removed)
    assert universe.resolve_ticker("CCAVENUE") == "CCAVENUE.NS"
    assert universe.resolve_ticker("ICICIPRULI") == "ICICIPRULI.NS"
    assert not (set(universe.FORMER_CONSTITUENTS) & set(universe.get_universe("all")))
