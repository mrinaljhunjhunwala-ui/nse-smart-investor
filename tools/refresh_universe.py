"""
tools/refresh_universe.py — regenerate data/nse_index_constituents.csv from NSE's
official index constituent CSVs (nsearchives / niftyindices archives).

The universe in data/universe.py is static on purpose (no network at import).
Its index-backed tiers are read from data/nse_index_constituents.csv, which this
tool rewrites. Columns: Symbol, Company, Industry, Index — Index is the narrowest
tier the symbol belongs to (NIFTY50 > NEXT50 > MIDCAP150 > SMALLCAP250 >
MICROCAP250 > TOTALMARKET). Every write also stamps the sidecar
data/nse_index_constituents.meta.json ({"refreshed", "checked", "count"}),
which data.universe.stale_universe_warning() reads.

Usage:
    py tools/refresh_universe.py            # dry run: fetch + print diff, write nothing
    py tools/refresh_universe.py --apply    # also rewrite the CSV
    python tools/refresh_universe.py --ci   # GitHub Actions (refresh_universe.yml):
        fetch -> diff -> if changed, write + branch auto/universe-YYYY-MM-DD +
        commit + push + `gh pr create --label automerge`; Telegram summary.
        Exit 0 = unchanged or PR opened; non-zero = fetch failed / list too
        small (< 90% of the committed size) / git or gh failed. On a fetch or
        size failure nothing is written.

NSE needs a browser User-Agent; requests are sequential with a pause (be polite).
After --apply, run tests/test_universe*.py and check the "Other" sector count.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from typing import Callable, Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:  # `python tools/refresh_universe.py` → make utils/ importable
    sys.path.insert(0, _ROOT)
OUT_PATH = os.path.join(_ROOT, "data", "nse_index_constituents.csv")
META_PATH = os.path.join(_ROOT, "data", "nse_index_constituents.meta.json")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HOSTS = ("https://nsearchives.nseindia.com/content/indices/",
          "https://www.niftyindices.com/IndexConstituent/")

# Tier name -> candidate file names, narrowest tier first (order = precedence).
TIERS: List[tuple] = [
    ("NIFTY50", ["ind_nifty50list.csv"]),
    ("NEXT50", ["ind_niftynext50list.csv"]),
    ("MIDCAP150", ["ind_niftymidcap150list.csv"]),
    ("SMALLCAP250", ["ind_niftysmallcap250list.csv"]),
    ("MICROCAP250", ["ind_niftymicrocap250_list.csv", "ind_niftymicrocap250list.csv"]),
    ("TOTALMARKET", ["ind_niftytotalmarket_list.csv"]),
]
FIELDS = ["Symbol", "Company", "Industry", "Index"]

# --ci guards
MIN_SIZE_RATIO = 0.90   # a fetch shrinking the universe below this is treated as broken
# Unchanged universe: re-stamp the meta "checked" date through a PR at most this
# often. Kept below data.universe.STALE_AFTER_DAYS (45) so a healthy weekly job
# never trips the dashboard's staleness caption between NSE rebalances.
META_RECHECK_DAYS = 28


def _download(name: str) -> Optional[str]:
    for host in _HOSTS:
        try:
            req = urllib.request.Request(host + name, headers={"User-Agent": _UA, "Accept": "text/csv,*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8-sig", errors="replace")
            if "Symbol" in text.splitlines()[0]:
                return text
        except Exception as exc:  # noqa: BLE001 — try the next host
            print(f"  {host}{name}: {exc}", file=sys.stderr)
        time.sleep(1.5)
    return None


def parse_index_csv(text: str) -> List[Dict[str, str]]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("Symbol") or "").strip()
        # DUMMY* rows are NSE placeholders for a pending demerger leg, not tradable.
        series = (r.get("Series") or "EQ").strip()
        if not sym or sym.upper().startswith("DUMMY") or series not in ("EQ", "BE", "BZ", ""):
            continue
        rows.append({"Symbol": sym, "Company": (r.get("Company Name") or "").strip(),
                     "Industry": (r.get("Industry") or "").strip()})
    return rows


def fetch_all(download: Callable[[str], Optional[str]] = _download,
              pause: float = 1.5) -> Dict[str, List[Dict[str, str]]]:
    """Download + parse every tier. Raises RuntimeError naming the first tier
    that could not be fetched or parsed (callers must not write anything then)."""
    fetched: Dict[str, List[Dict[str, str]]] = {}
    for tier, names in TIERS:
        text = None
        for name in names:
            text = download(name)
            if text:
                break
        if not text:
            raise RuntimeError(f"could not fetch {tier} ({' / '.join(names)})")
        fetched[tier] = parse_index_csv(text)
        if not fetched[tier]:
            raise RuntimeError(f"{tier} CSV parsed to 0 rows")
        print(f"{tier:<12} {len(fetched[tier]):>4} rows")
        time.sleep(pause)
    return fetched


def build(fetched: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Merge per-tier rows; each symbol keeps its narrowest tier."""
    out: Dict[str, Dict[str, str]] = {}
    for tier, _ in TIERS:
        for r in fetched.get(tier, []):
            if r["Symbol"] not in out:
                out[r["Symbol"]] = {**r, "Index": tier}
    return list(out.values())


def load_existing(path: str = OUT_PATH) -> List[Dict[str, str]]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


_NAME_NOISE = {"ltd", "limited", "the", "co", "company", "corp", "corporation", "inc", "pvt", "private"}


def _norm_company(name: str) -> str:
    """'The Tata Power Company Ltd.' -> 'tata power' — for rename matching only."""
    words = re.sub(r"[^a-z0-9& ]+", " ", (name or "").lower()).split()
    return " ".join(w for w in words if w not in _NAME_NOISE)


def diff(old: List[Dict[str, str]], new: List[Dict[str, str]]) -> Dict[str, list]:
    """Symbol-level diff. ``renamed`` holds (old_sym, new_sym) pairs where a
    removed symbol's normalised company name matches exactly one added
    symbol's; both symbols are then left out of ``added`` / ``removed``."""
    o = {r["Symbol"]: r for r in old}
    n = {r["Symbol"]: r for r in new}
    added = set(n) - set(o)
    removed = set(o) - set(n)

    by_name: Dict[str, List[str]] = {}
    for s in added:
        key = _norm_company(n[s].get("Company", ""))
        if key:
            by_name.setdefault(key, []).append(s)
    renamed = []
    for s in sorted(removed):
        key = _norm_company(o[s].get("Company", ""))
        cands = by_name.get(key, []) if key else []
        if len(cands) == 1 and cands[0] in added:
            renamed.append((s, cands[0]))
            added.discard(cands[0])
    for old_sym, _ in renamed:
        removed.discard(old_sym)

    return {"added": sorted(added), "removed": sorted(removed), "renamed": renamed,
            "retiered": sorted((s, o[s]["Index"], n[s]["Index"])
                               for s in set(o) & set(n) if o[s]["Index"] != n[s]["Index"])}


def render_csv(rows: List[Dict[str, str]]) -> str:
    order = {t: i for i, (t, _) in enumerate(TIERS)}
    rows = sorted(rows, key=lambda r: (order.get(r["Index"], len(order)), r["Symbol"]))
    buf = io.StringIO(newline="")
    # LF endings: the committed CSV is LF (no .gitattributes), so a Linux CI
    # write must not turn every line into a CRLF diff.
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def load_meta(path: str = META_PATH) -> Dict[str, object]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(count: int, refreshed: Optional[str] = None, path: str = META_PATH,
               today: Optional[dt.date] = None) -> None:
    """Stamp the sidecar. ``refreshed`` = last date the CSV content changed
    (kept from the old meta when None); ``checked`` = today."""
    day = (today or dt.date.today()).isoformat()
    meta = {"refreshed": refreshed or str(load_meta(path).get("refreshed") or day),
            "checked": day, "count": count,
            "source": "NSE index constituent CSVs (tools/refresh_universe.py)"}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")


def write(rows: List[Dict[str, str]], path: str = OUT_PATH, meta_path: Optional[str] = None,
          today: Optional[dt.date] = None) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(render_csv(rows))
    if meta_path is None and path == OUT_PATH:
        meta_path = META_PATH
    if meta_path:
        write_meta(len(rows), refreshed=(today or dt.date.today()).isoformat(), path=meta_path, today=today)


# ── --ci mode ────────────────────────────────────────────────────────────────

def _names(syms: List[str], limit: int = 12) -> str:
    shown = ", ".join(syms[:limit])
    return shown + (f" +{len(syms) - limit} more" if len(syms) > limit else "")


def summary_line(d: Dict[str, list], pr: Optional[str]) -> str:
    """'Universe check: +2 added (A, B), −1 removed (C), 1 renamed (X→Y), PR #12'."""
    parts = [f"+{len(d['added'])} added" + (f" ({_names(d['added'])})" if d["added"] else ""),
             f"−{len(d['removed'])} removed" + (f" ({_names(d['removed'])})" if d["removed"] else "")]
    if d.get("renamed"):
        parts.append(f"{len(d['renamed'])} renamed ({_names([f'{a}→{b}' for a, b in d['renamed']])})")
    if d.get("retiered"):
        parts.append(f"{len(d['retiered'])} re-tiered")
    if pr:
        parts.append(f"PR #{pr}")
    return "Universe check: " + ", ".join(parts)


def pr_body(d: Dict[str, list], old: List[Dict[str, str]], new: List[Dict[str, str]]) -> str:
    o = {r["Symbol"]: r for r in old}
    n = {r["Symbol"]: r for r in new}
    out = ["Automated weekly refresh of `data/nse_index_constituents.csv` from NSE's official index "
           "constituent CSVs (`tools/refresh_universe.py --ci`, workflow `refresh_universe.yml`).",
           "", f"Universe size: {len(old)} → {len(new)}", ""]

    def table(title: str, cols: List[str], rows: List[str]) -> None:
        if rows:
            out.extend([f"### {title} ({len(rows)})", "", "| " + " | ".join(cols) + " |",
                        "|" + "---|" * len(cols), *rows, ""])

    table("Added", ["Symbol", "Company", "Index"],
          [f"| {s} | {n[s].get('Company', '')} | {n[s]['Index']} |" for s in d["added"]])
    table("Removed", ["Symbol", "Company", "Was in"],
          [f"| {s} | {o[s].get('Company', '')} | {o[s]['Index']} |" for s in d["removed"]])
    table("Renamed (same company name, new symbol)", ["Old", "New", "Company"],
          [f"| {a} | {b} | {n[b].get('Company', '')} |" for a, b in d.get("renamed", [])])
    table("Re-tiered", ["Symbol", "From", "To"],
          [f"| {s} | {a} | {b} |" for s, a, b in d.get("retiered", [])])
    if not any(d[k] for k in ("added", "removed", "renamed", "retiered")):
        out.append("No symbol changes: either company / industry text changed, or this only re-stamps "
                   "the `checked` date in the meta file so the dashboard's staleness caption stays quiet.")
    out += ["", "After merge: renamed symbols may need their `_SECTOR_ASSIGNMENTS` / `STOCK_SEARCH_MAP` "
            "entries moved (`data/universe.py`, `dashboard/shared/cache.py`)."]
    return "\n".join(out)


def notify(text: str) -> None:
    """Telegram summary; never raises (prints to console without secrets)."""
    print(text)
    try:
        from utils.telegram import TelegramAlerter
        alerter = TelegramAlerter()
        alerter.send_text(alerter._escape_md(text))
    except Exception as exc:  # noqa: BLE001 — a missing/broken Telegram must not fail the job
        print(f"  [Telegram] unavailable: {exc}", file=sys.stderr)


def _run(cmd: List[str]) -> str:
    print("$ " + " ".join(cmd))
    res = subprocess.run(cmd, cwd=_ROOT, check=True, capture_output=True, text=True)
    return res.stdout.strip()


def publish(branch: str, title: str, body: str, paths: List[str]) -> str:
    """Branch, commit, push, open (or reuse) the automerge PR. Returns the PR number."""
    _run(["git", "checkout", "-B", branch])
    _run(["git", "add", "--", *paths])
    _run(["git", "commit", "-m", title, "-m", "Automated by tools/refresh_universe.py --ci."])
    _run(["git", "push", "--force", "origin", branch])  # auto/ branch: a same-day re-run replaces it
    try:
        existing = _run(["gh", "pr", "view", branch, "--json", "number,state", "--jq",
                         'select(.state == "OPEN") | .number'])
    except subprocess.CalledProcessError:
        existing = ""
    if existing:
        return existing
    body_file = os.path.join(_ROOT, ".universe_pr_body.md")
    with open(body_file, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        url = _run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title,
                    "--body-file", body_file, "--label", "automerge"])
    finally:
        os.remove(body_file)
    m = re.search(r"/pull/(\d+)", url)
    return m.group(1) if m else url


def run_ci(today: Optional[dt.date] = None, fetch: Callable[[], dict] = fetch_all,
           publish_fn: Callable[..., str] = publish,
           out_path: str = OUT_PATH, meta_path: str = META_PATH) -> int:
    today = today or dt.date.today()
    old = load_existing(out_path)
    try:
        new = build(fetch())
    except Exception as exc:  # noqa: BLE001 — any fetch/parse error aborts before writing
        notify(f"Universe check FAILED: {exc} (nothing written)")
        return 1
    floor = int(len(old) * MIN_SIZE_RATIO)
    if not new or len(new) < floor:
        notify(f"Universe check FAILED: fetched {len(new)} symbols, below 90% of the current "
               f"{len(old)} (min {floor}); suspicious, nothing written")
        return 1

    d = diff(old, new)
    content_changed = render_csv(new) != render_csv(old)
    meta = load_meta(meta_path)
    try:
        meta_age: Optional[int] = (today - dt.date.fromisoformat(
            str(meta.get("checked") or meta.get("refreshed") or ""))).days
    except ValueError:
        meta_age = None
    restamp = meta_age is None or meta_age >= META_RECHECK_DAYS
    print(f"total {len(new)} symbols | added {len(d['added'])} | removed {len(d['removed'])} "
          f"| renamed {len(d['renamed'])} | re-tiered {len(d['retiered'])}")

    if not content_changed and not restamp:
        notify("Universe check: unchanged")
        print("universe unchanged")
        return 0

    if content_changed:
        write(new, path=out_path, meta_path=meta_path, today=today)
        title = f"data · universe refresh {today.isoformat()} (+{len(d['added'])} / −{len(d['removed'])})"
    else:
        write_meta(len(new), path=meta_path, today=today)
        title = f"data · universe unchanged, re-stamp checked date {today.isoformat()}"
    try:
        pr = publish_fn(f"auto/universe-{today.isoformat()}", title, pr_body(d, old, new),
                        [os.path.relpath(out_path, _ROOT), os.path.relpath(meta_path, _ROOT)])
    except Exception as exc:  # noqa: BLE001
        err = getattr(exc, "stderr", "") or exc
        notify(f"Universe check FAILED: could not open the PR: {str(err).strip()[:300]}")
        return 1
    if content_changed:
        notify(summary_line(d, pr))
    else:
        notify(f"Universe check: unchanged (checked date re-stamped, PR #{pr})")
        print("universe unchanged")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="rewrite the CSV (default: dry run)")
    ap.add_argument("--ci", action="store_true", help="CI: write + open an automerge PR when changed")
    args = ap.parse_args(argv)
    if args.ci:
        return run_ci()

    try:
        fetched = fetch_all()
    except RuntimeError as exc:
        print(f"FAILED: {exc}; aborting (nothing written).", file=sys.stderr)
        return 1

    new = build(fetched)
    d = diff(load_existing(), new)
    print(f"total {len(new)} symbols | added {len(d['added'])} | removed {len(d['removed'])} "
          f"| renamed {len(d['renamed'])} | re-tiered {len(d['retiered'])}")
    for k in ("added", "removed", "renamed", "retiered"):
        if d[k]:
            print(f"{k}: {d[k]}")
    if args.apply:
        write(new)
        print(f"wrote {OUT_PATH}")
    else:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
