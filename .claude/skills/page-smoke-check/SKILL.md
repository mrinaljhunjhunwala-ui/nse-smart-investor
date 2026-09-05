---
name: page-smoke-check
description: Run the matching Streamlit page-smoke test after editing any file under dashboard/pages/ or dashboard/shared/. The project's test_pages_smoke.py catches page-render regressions with mocked I/O; this skill makes sure that safety net gets exercised before an edit is called done.
user-invocable: false
---

# Page Smoke Check

## When to invoke

Automatically, at the end of any turn that edited or created files matching:

- `dashboard/pages/*.py`
- `dashboard/shared/*.py`
- `dashboard/app.py`

Skip if the edit was only to comments, docstrings, or type hints (no runtime behaviour change).

## What to run

The full page-smoke suite is at `tests/test_pages_smoke.py`. It stubs network I/O and imports each page module to catch AttributeErrors, missing imports, `st.set_page_config` duplication, and broken layouts.

**Fast (default)** — after editing one page, run only that page's smoke test:

```bash
py -m pytest tests/test_pages_smoke.py -k "<page_stem>" -q
```

Where `<page_stem>` is the page filename without extension, e.g. `04_analyze_stock` when the edit touched `dashboard/pages/04_analyze_stock.py`.

**Full** — after editing anything in `dashboard/shared/` (shared code touches every page):

```bash
py -m pytest tests/test_pages_smoke.py -q
```

## Interpretation

- **Pass silently**: continue as normal.
- **Fail on the smoked page**: read the traceback, fix the regression, re-run before declaring the edit done. Do not proceed to unrelated work while a page is broken.
- **Fail on an unrelated page after a `dashboard/shared/` edit**: the shared change had wider blast radius than expected. Either revert the shared change, or extend it to be backward-compatible with the pages that broke.

## Rationale

The offline page-smoke suite is the cheapest possible regression test for this app — mocked I/O keeps it under 30 seconds. Skipping it because "the change looked small" is the exact failure mode that produced the last two dashboard-broken commits. Making it a mandatory tail step of every dashboard edit closes that loop.

## When to update the smoke test itself

If the smoke suite doesn't cover a page you're editing (rare — it currently covers all 18), add a smoke case *before* the feature work, not after. Follow the pattern in existing cases (`test_pages_smoke.py` — pick any working case as the template).
