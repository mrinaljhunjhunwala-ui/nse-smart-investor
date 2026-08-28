# P3 — `globals().update()` Removal Report

Removed the dynamic shared-namespace injection from **all 17 dashboard pages**, replaced with
**explicit imports**. Behaviour-preserving, pollution-eliminating, verified.

## What was wrong
Every page ran:
```python
from dashboard.shared import design as _dz, cache as _cache, trade_utils as _tu, chart_helpers as _ch
for _m in (_dz, _cache, _tu, _ch):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})
```
This injected **all** public names from 4 shared modules into each page's globals — **including
re-exported libraries** (`st`, `pd`, `np`, `go`, `px`, `datetime`, `json`, `math`, …). Pages
silently depended on the injection (e.g. used `st`/`pd` without importing them), so the names a page
actually relied on were invisible — the core risk of a blind removal.

## The safe transform
An AST-driven generator computed, per page, the exact set of injected names the page **references**
(`ast.Name` Load nodes), then emitted explicit imports:
- re-exported library modules → canonical `import numpy as np` / `import streamlit as st` / … (resolved via the object's real `__name__`)
- shared helpers/constants → `from dashboard.shared.<module> import (…)`

Only the **used** names are imported (6–24 per page vs ~50 injected) — real pollution reduction. The
generator was a **superset over referenced shared names**, giving a static no-NameError guarantee.

## Verification (3 layers)
1. **Static — generator:** every page reported `missing=[]` (each referenced shared name is covered) and `parse=OK`.
2. **Static — independent re-check:** an AST pass over the post-transform pages found **0 pages with any unresolved shared name** (referenced-but-not-imported-and-not-locally-assigned).
3. **Compile + tests + runtime:** all 17 pages `py_compile` clean; **full suite 245 passing**; AppTest of transformed pages (`13_position_sizer`, `14_swing_checklist`) executed with **exception = None**.

Confirmed `0` actual `globals().update()` calls and `0` `for _m in (...)` loops remain.

## Files modified
All 17 `dashboard/pages/*.py` (01–17). Each: the 3-line inject block replaced by an explicit import
block. No page-body logic changed.

## Edge cases handled
- `01_market_live.py` reuses `_ch` as a **local variable** (`_ch = _row["chg_pct"]`) — unaffected (it is self-assigned before use; the removed alias was unrelated).
- A few pages keep a redundant `import streamlit as st` / `apply_design` (they imported it explicitly already) — harmless duplicates, behaviour-identical.

## Result
Namespace pollution eliminated; every page's dependencies are now explicit and greppable; behaviour
preserved (245 tests green + runtime smoke). The shared modules can later trim their re-exports
without silently breaking pages.
