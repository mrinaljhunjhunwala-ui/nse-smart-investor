"""dashboard/shared/design.py - NSE Pro CSS theme, Plotly template, UI helpers.

── DESIGN TOKENS (NSE Pro v2 — "Dealing Room") ───────────────────────────────
Reference point: the black-and-phosphor heritage of Bloomberg/Reuters terminals
rather than a generic dark-mode SaaS dashboard. One accent (India saffron) carries
all interactive/brand chrome; green and red are reserved strictly for
buy/sell semantics so they never compete with the UI for attention.

  Surface   ink #09090b · surface #131316 · sunken #0e0e10 · hairline rgba(255,255,255,.08)
  Text      primary #edeef0 · dim #8b8d93 · faint #55575e
  Signal    bull #16c784 · bear #ff4d4d · caution #f2a93b · accent #ff9500
  Type      display/UI: IBM Plex Sans · data/numeric: IBM Plex Mono
  Radius    sharp 6px (tables/inputs/tape) · base 10px (cards/metrics) · soft 18px (hero panels)

Public API (function names + CSS class names) is unchanged from v1 — 13 page
files reference these directly. Only the tokens/values inside change.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.subplots import make_subplots
import streamlit as st
# FIX WARN1 — narrowed from a blanket `filterwarnings("ignore")` so numpy's
# RuntimeWarnings (invalid value / divide by zero / all-NaN slice) stay visible.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def apply_design():
    """Register Plotly template + inject CSS. Idempotent across pages."""
    if "nse_pro" not in pio.templates:
        pio.templates["nse_pro"] = go.layout.Template(
            layout=dict(
                paper_bgcolor="#09090b",
                plot_bgcolor="#0c0c0f",
                font=dict(family="IBM Plex Sans, -apple-system, sans-serif", color="#8b8d93", size=12),
                title=dict(font=dict(size=15, color="#edeef0")),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.07)",
                           tickfont=dict(color="#55575e", size=11), zeroline=False),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.07)",
                           tickfont=dict(color="#55575e", size=11), zeroline=False),
                legend=dict(bgcolor="rgba(14,14,16,0.9)", bordercolor="rgba(255,255,255,0.07)",
                            borderwidth=1, font=dict(color="#8b8d93", size=11)),
                hoverlabel=dict(bgcolor="#131316", bordercolor="rgba(255,255,255,0.14)",
                                font=dict(color="#edeef0", family="IBM Plex Mono", size=12)),
                colorway=["#ff9500", "#16c784", "#f2a93b", "#ff4d4d", "#8b8d93", "#5a8fd6",
                          "#c77dff", "#edeef0"],
            )
        )
        pio.templates.default = "nse_pro"

    # ── NSE Pro Design System v2 — "Dealing Room" ──────────────────────────────
    st.markdown(
        """<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap');

    /* ── SPRINT 1.1: Design tokens as CSS custom properties ─────────────────
       Single source of truth for palette, radius, and shadow. Every rule
       below and every page-level inline style SHOULD source colour from
       these vars — audit found ~8 parallel greens (#16c784, #26a69a,
       #00d4aa, #3ddc84 …) drifting page-to-page. New rule: no raw hex in
       page files. See docs/UI_AUDIT_2026-09.md → Cluster B. ─────────────── */
    :root {
      /* Surfaces — §9.2 texture layers (docs/UI_UX_DESIGN_2026-09.md).
         Pure #0a0a0a ground lets saffron / bull / bear pop with real
         chromatic weight; cards float above it as a 2% white overlay
         (borrowed from NSVisualEffectView) instead of a heavier tinted
         rectangle. Cyan was in an earlier draft; #103 explicitly rejected
         it for saffron as the single interactive hue. */
      --ground:    #0a0a0a;
      --surface:   #131316;                    /* legacy card bg — pages migrating to --card-lift */
      --card-lift: rgba(255,255,255,.02);      /* §9.2.2 — floated card fill on ground */
      --sunken:    #0e0e10;
      --rail:      #0a0a0c;

      /* Hairline system — §9.2.3 three widths.
         Semantic mapping: -soft for section dividers (barely there),
         -base for interactive borders (buttons, chips), -strong for
         active-focus (inputs, active nav). Old --hairline stays as an
         alias on -base for callers not yet migrated. */
      --hairline-soft:   rgba(255,255,255,.04);
      --hairline:        rgba(255,255,255,.08);
      --hairline-strong: rgba(255,255,255,.16);

      /* Ink — four densities, §9.3 colour table. */
      --ink:       #edeef0;
      --ink-mid:   #c8cad0;
      --dim:       #8b8d93;
      --faint:     #55575e;

      /* Signal — reserved strictly for buy/sell/warn semantics */
      --bull:      #16c784;
      --bear:      #ff4d4d;
      --amber:     #f2a93b;

      /* Accent — one hue for all interactive/brand chrome */
      --accent:    #ff9500;
      --accent-hi: #ffb340;

      /* Purple/blue kept for categorical fills only (charts, sector tags) */
      --violet:    #c77dff;
      --azure:     #5a8fd6;

      /* Semantic aliases (map onto signal, so pages read intent, not hue) */
      --pos:       var(--bull);
      --neg:       var(--bear);
      --warn:      var(--amber);
      --info:      var(--accent);

      /* Regime colours — same three severities, aliased for narrative */
      --regime-good:  var(--bull);
      --regime-mixed: var(--amber);
      --regime-bad:   var(--bear);
      --regime-none:  var(--faint);

      /* Tinted backgrounds (12% overlays, used on cards + pills) */
      --tint-bull:   rgba(22,199,132,.12);
      --tint-bear:   rgba(255,77,77,.12);
      --tint-amber:  rgba(242,169,59,.12);
      --tint-accent: rgba(255,149,0,.12);
      --tint-violet: rgba(199,125,255,.12);

      /* Radius */
      --r-sharp:  6px;   /* tables, inputs, ticker tape */
      --r-base:   10px;  /* cards, metrics */
      --r-soft:   18px;  /* hero / glass panels */

      /* Type */
      --font-sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      --font-mono: 'IBM Plex Mono', 'Courier New', monospace;
      --font-serif: 'Instrument Serif', 'Iowan Old Style', Georgia, serif;

      /* F4 · Motion policy (docs/UI_UX_BACKLOG.md)
         One motion vocabulary for the whole app:
           - ≤180 ms so nothing feels "waited on"
           - ease-out for enter states (fast start, gentle land)
           - prefers-reduced-motion honoured: durations collapse to 0
             via the media query below, so no caller has to guard. */
      --motion-fast:  120ms;   /* hover, chip flip, chevron rotate */
      --motion-base:  180ms;   /* card fade-in, sheet enter */
      --motion-slow:  260ms;   /* hero verdict entry, large panels */
      --ease-out:     cubic-bezier(0.16, 1, 0.3, 1);   /* enter */
      --ease-in-out:  cubic-bezier(0.65, 0, 0.35, 1);  /* toggles */
    }

    /* F4 · reduced-motion guard -- flattens every duration to 0. Applies
       to app CSS, inline styles that use var(--motion-*), and the
       .motion-fade-in / .motion-slide-up utility classes below. Users
       who prefer reduced motion get instant states, no animation. */
    @media (prefers-reduced-motion: reduce) {
      :root {
        --motion-fast: 0ms;
        --motion-base: 0ms;
        --motion-slow: 0ms;
      }
      * {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
    }

    /* F4 · utility classes. Deliberately small surface -- most UI should
       not animate at all. Reserve these for entry moments where a soft
       reveal reads more polished than a hard cut. */
    @keyframes motion-fade-in-kf {
      from { opacity: 0; }
      to   { opacity: 1; }
    }
    @keyframes motion-slide-up-kf {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    .motion-fade-in {
      animation: motion-fade-in-kf var(--motion-base) var(--ease-out) both;
    }
    .motion-slide-up {
      animation: motion-slide-up-kf var(--motion-slow) var(--ease-out) both;
    }

    /* ── §9.4 · Typography scale (docs/UI_UX_DESIGN_2026-09.md) ─────────────
       One axis, formalised. Every card / heading / label picks from here so
       Command Centre's 11 px caption stack, Investor Guide's flat 14 px,
       and Analyze Stock's 20 px hero can't drift apart again. */
    .t-display  { font-family: var(--font-sans); font-size: 32px; font-weight: 700;
                  letter-spacing: -0.02em; line-height: 1.05; color: var(--ink); }
    .t-h1       { font-family: var(--font-sans); font-size: 22px; font-weight: 700;
                  letter-spacing: -0.01em; line-height: 1.15; color: var(--ink); }
    .t-h2       { font-family: var(--font-sans); font-size: 16px; font-weight: 600;
                  line-height: 1.3;  color: var(--ink); }
    .t-body     { font-family: var(--font-sans); font-size: 14px; font-weight: 400;
                  line-height: 1.5;  color: var(--ink-mid); }
    .t-label    { font-family: var(--font-sans); font-size: 11px; font-weight: 600;
                  letter-spacing: 0.12em; text-transform: uppercase; color: var(--dim); }
    .t-value    { font-family: var(--font-mono); font-size: 20px; font-weight: 700;
                  letter-spacing: -0.01em; color: var(--ink); font-variant-numeric: tabular-nums; }
    .t-value-sm { font-family: var(--font-mono); font-size: 14px; font-weight: 600;
                  color: var(--ink); font-variant-numeric: tabular-nums; }
    .t-caption  { font-family: var(--font-sans); font-size: 12px; font-weight: 400;
                  line-height: 1.3;  color: var(--dim); }

    /* ── §9.2.4 · Grain overlay (SVG noise at 3% opacity on the body).
       Imperceptible in isolation; stops the "empty dark rectangle" flatness
       that reads as amateur on pure black. Bloomberg terminals had physical
       CRT grain; this is the digital equivalent. Zero runtime cost —
       inline SVG data-URI, single background-image. */

    /* ── Editorial serif · used SPARINGLY on hero moments only ─────────────
       - Page-title-serif on the H1 of anchor pages (Command Centre,
         Analyze Stock, Portfolio, Investor Guide).
       - Verdict-posture-serif on the descriptive posture line inside a
         hero card ("Constructive, with reservations.").
       - Never on data, buttons, or body copy — that's what Plex Sans is
         for. See docs/UI_UX_DESIGN_2026-09.md §4 (cross-cutting rules). */
    .page-title-serif {
        font-family: var(--font-serif) !important;
        font-weight: 400 !important;
        font-size: clamp(32px, 4vw, 44px) !important;
        line-height: 1.05 !important;
        letter-spacing: -0.02em !important;
        color: var(--ink) !important;
        margin: 0 0 6px 0 !important;
        text-wrap: balance;
    }
    .page-title-serif em {
        font-style: italic;
        color: var(--accent);
    }
    .page-subtitle {
        font-size: 13px !important;
        color: var(--dim) !important;
        margin: 0 0 20px 0 !important;
        max-width: 62ch;
        line-height: 1.55;
    }
    .verdict-posture-serif {
        font-family: var(--font-serif) !important;
        font-weight: 400 !important;
        font-size: 32px !important;
        line-height: 1.1 !important;
        letter-spacing: -0.015em !important;
        color: var(--ink) !important;
        margin: 4px 0 8px 0 !important;
    }
    .verdict-posture-serif em {
        font-style: italic;
        color: var(--accent);
    }

    /* ── Hide Streamlit's auto-generated pages/ nav (custom nav lives in
          render_sidebar). Belt-and-suspenders with showSidebarNavigation=false. ── */
    [data-testid="stSidebarNav"] { display: none !important; }

    /* ── Global ──────────────────────────────────────────────────────────────── */
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        -webkit-font-smoothing: antialiased;
    }
    .stApp {
        background: var(--ground);
        /* §9.2.1 pure-black ground + §9.2.4 SVG noise grain at 3% opacity +
           the existing saffron aurora at the top-centre. Stacked in a
           single background: shorthand so it stays as one paint pass. */
        background-image:
          radial-gradient(ellipse 90% 40% at 50% -10%, rgba(255,149,0,0.05) 0%, transparent 60%),
          url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.03 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
        background-attachment: fixed;
        background-size: auto, 160px 160px;
    }
    .mono { font-family:'IBM Plex Mono','Courier New',monospace !important; font-variant-numeric: tabular-nums; }

    /* ── Cards ───────────────────────────────────────────────────────────────
       Flat tinted surface + solid left rail, not a diagonal two-stop gradient —
       calmer and denser at a glance, closer to a real order-flow ticket. ─────── */
    .card-green, .card-yellow, .card-red, .card-blue, .card-purple, .card-orange {
        border-radius:10px; padding:14px 18px; margin:6px 0;
        transition: border-color .15s ease, background .15s ease;
    }
    .card-green:hover, .card-yellow:hover, .card-red:hover,
    .card-blue:hover, .card-purple:hover, .card-orange:hover {
        background-position: right center;
    }
    .card-green  { background:rgba(22,199,132,.07);  border-left:3px solid #16c784; }
    .card-yellow { background:rgba(242,169,59,.07);  border-left:3px solid #f2a93b; }
    .card-red    { background:rgba(255,77,77,.07);   border-left:3px solid #ff4d4d; }
    .card-blue   { background:rgba(255,149,0,.06);  border-left:3px solid #ff9500; }
    .card-purple { background:rgba(199,125,255,.06); border-left:3px solid #c77dff; }
    .card-orange { background:rgba(242,169,59,.07);  border-left:3px solid #f2a93b; }

    /* ── Score & typography ───────────────────────────────────────────────────── */
    .score-big    { font-family:'IBM Plex Mono',monospace; font-size:54px; font-weight:700; letter-spacing:-1px; font-variant-numeric: tabular-nums; }
    .signal-big   { font-size:21px; font-weight:700; letter-spacing:.6px; text-transform:uppercase; }
    .narrative    { font-size:14px; line-height:1.75; color:#8b8d93; }
    .ticker-label { font-size:23px; font-weight:700; color:#edeef0; letter-spacing:-.2px; }

    /* ── Pills ───────────────────────────────────────────────────────────────── */
    .pill-green  { display:inline-block; background:rgba(22,199,132,.12); color:#16c784; border:1px solid rgba(22,199,132,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-red    { display:inline-block; background:rgba(255,77,77,.12);  color:#ff4d4d; border:1px solid rgba(255,77,77,.4);  border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-yellow { display:inline-block; background:rgba(242,169,59,.12); color:#f2a93b; border:1px solid rgba(242,169,59,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-gray   { display:inline-block; background:rgba(255,255,255,.06); color:#8b8d93; border:1px solid rgba(255,255,255,.14); border-radius:20px; padding:3px 14px; font-size:12px; }
    .pill-blue   { display:inline-block; background:rgba(255,149,0,.12);  color:#ff9500; border:1px solid rgba(255,149,0,.4);  border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }

    /* ── Signal badges ───────────────────────────────────────────────────────── */
    .badge-buy   { background:rgba(22,199,132,.14); color:#16c784; border:1px solid #16c784; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-sell  { background:rgba(255,77,77,.14);  color:#ff4d4d; border:1px solid #ff4d4d; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-hold  { background:rgba(242,169,59,.14); color:#f2a93b; border:1px solid #f2a93b; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-watch { background:rgba(255,149,0,.14); color:#ff9500; border:1px solid #ff9500; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }

    /* ── Angel One badges ────────────────────────────────────────────────────── */
    .ao-badge-on  { background:rgba(22,199,132,.08); border:1px solid rgba(22,199,132,.4); border-radius:8px; padding:10px 14px; font-size:12px; color:#16c784; margin:4px 0; display:flex; align-items:center; gap:8px; }
    .ao-badge-off { background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:10px 14px; font-size:12px; color:#55575e; margin:4px 0; display:block; }

    /* ── Streamlit metric override ─────────────────────────────────────────────
       §9.2 · sits on the pure-black ground as a 2% white lift instead of
       a heavier tinted rectangle. Reads as a floated card without the
       chrome. */
    [data-testid="stMetric"] {
        background: var(--card-lift);
        border: 1px solid var(--hairline);
        border-radius: var(--r-base); padding: 14px 18px;
    }
    [data-testid="stMetricValue"] { font-family:'IBM Plex Mono',monospace; font-weight:700; letter-spacing:-.3px; font-size:20px; }
    [data-testid="stMetricLabel"] { font-size:11px; color:#55575e; text-transform:uppercase; letter-spacing:1px; font-weight:600; }
    /* Never clip/ellipsis metric text — always show the full value, label and delta */
    [data-testid="stMetric"] { overflow: visible !important; }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *,
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
        white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; max-width: none !important;
    }

    /* ── Buttons ─────────────────────────────────────────────────────────────── */
    .stButton > button {
        border-radius:6px; font-weight:600; letter-spacing:.2px;
        border: 1px solid rgba(255,255,255,.1); transition: all .15s ease;
        background: rgba(255,255,255,.04);
    }
    .stButton > button:hover { border-color: rgba(255,149,0,.5); color:#ff9500; }
    /* F7 · keyboard focus ring — matches the saffron halo used on inputs so
       "you can act here" reads the same on click, tab-through, and hover.
       :focus-visible fires only on keyboard nav (never on mouse click), so
       pointer users don't see the ring unless they Tab to a button. */
    .stButton > button:focus-visible {
        outline: none !important;
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px rgba(255,149,0,.20) !important;
    }
    .stButton > button[kind="primary"] {
        background: #ff9500; border:none; color:#09090b; font-weight:700;
    }
    .stButton > button[kind="primary"]:hover { background:#ffb340; color:#09090b; }
    .stButton > button[kind="primary"]:focus-visible {
        outline: none !important;
        box-shadow: 0 0 0 3px rgba(255,149,0,.30) !important;
    }

    /* ── Tabs ────────────────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px; background: rgba(255,255,255,.02);
        border-radius: 8px; padding: 4px;
        border: 1px solid rgba(255,255,255,.05);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px; padding: 8px 18px; font-weight: 500;
        color: #55575e; transition: all .15s;
    }
    .stTabs [aria-selected="true"] {
        background: #131316; font-weight: 700; color: #ff9500;
    }
    /* F7 · focus-visible ring on tab buttons — keyboard nav only. */
    .stTabs [data-baseweb="tab"]:focus-visible {
        outline: none;
        box-shadow: 0 0 0 2px rgba(255,149,0,.35) inset;
    }

    /* ── Sidebar ─────────────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: #0a0a0c;
        border-right: 1px solid rgba(255,255,255,.06);
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        font-size: 13px; color: #8b8d93;
    }

    /* ── SLICE 1 + POLISH · UI/UX 2026-09 · sidebar group headers + nav ──
       Structural polish for the 6-group nav. Group headers flatten to
       hairline dividers with an uppercase eyebrow label. Nav buttons
       drop their default borders + backgrounds to read as list items.
       The active page gets a leading-edge accent pill so it reads at a
       glance. Sourced from --accent (saffron #ff9500). See
       docs/UI_UX_DESIGN_2026-09.md §3. */
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background: transparent !important;
        border: 0 !important;
        border-bottom: 1px solid rgba(255,255,255,.06) !important;
        border-radius: 0 !important;
        margin: 0 !important;
    }
    /* Kill Streamlit's expanded-state purple tint on the summary/details */
    [data-testid="stSidebar"] [data-testid="stExpander"] details,
    [data-testid="stSidebar"] [data-testid="stExpander"] details[open],
    [data-testid="stSidebar"] [data-testid="stExpander"] summary,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:focus {
        background: transparent !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        padding: 10px 12px 8px !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary p,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary span {
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: .14em;
        color: #8b8d93 !important;
        font-weight: 600 !important;
    }
    /* Nav buttons — flatten to list-item feel, keep only left padding */
    [data-testid="stSidebar"] .stButton > button {
        background: transparent !important;
        border: 0 !important;
        border-left: 3px solid transparent !important;
        border-radius: 0 4px 4px 0 !important;
        padding-left: 13px !important;
        text-align: left !important;
        color: #c8cad0 !important;
        font-weight: 500 !important;
        transition: background .12s ease, color .12s ease, border-color .12s ease !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(255,149,0,.06) !important;
        color: #edeef0 !important;
        border-left-color: rgba(255,149,0,.35) !important;
    }
    /* Active page: leading-edge saffron pill on the disabled (current) button.
       §9.2 optional glow layer — 12 px soft saffron halo at 22% opacity so
       the active-page pill reads as lit rather than just tinted. Never on
       hover (would fire on every mouse move); only on the current page. */
    [data-testid="stSidebar"] .stButton > button:disabled {
        background: linear-gradient(90deg, rgba(255,149,0,.14), transparent 60%) !important;
        color: #edeef0 !important;
        border: 0 !important;
        border-left: 3px solid #ff9500 !important;
        border-radius: 0 4px 4px 0 !important;
        padding-left: 13px !important;
        text-align: left !important;
        opacity: 1 !important;
        cursor: default !important;
        box-shadow: 0 0 12px 0 rgba(255,149,0,.22) !important;
    }
    [data-testid="stSidebar"] .stButton > button:disabled:hover {
        color: #edeef0 !important;
        border-color: #ff9500 !important;
        background: linear-gradient(90deg, rgba(255,149,0,.14), transparent 60%) !important;
    }

    /* ── Selectbox / inputs ──────────────────────────────────────────────────── */
    [data-baseweb="select"] > div:first-child {
        background: #0e0e10; border-color: rgba(255,255,255,.1) !important;
        border-radius: 6px;
    }
    .stTextInput > div > div > input {
        background: #0e0e10; border-color: rgba(255,255,255,.1);
        border-radius: 6px; color: #edeef0; font-family:'IBM Plex Mono',monospace;
    }
    .stNumberInput > div > div > input {
        background: #0e0e10; border-color: rgba(255,255,255,.1);
        border-radius: 6px; color: #edeef0; font-family:'IBM Plex Mono',monospace;
    }
    /* §9.2 · focus-visible glow — only on the input actually being keyed,
       never on hover. Matches the active-nav pill's saffron halo so the
       whole app teaches the same "you can act here" affordance. */
    .stTextInput > div > div > input:focus-visible,
    .stNumberInput > div > div > input:focus-visible,
    [data-baseweb="select"] > div:first-child:focus-within {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px rgba(255,149,0,.15) !important;
        outline: none !important;
    }

    /* ── F3 · widget parity — Paper Trades / Intraday / Angel One ──────────────
       Streamlit ships default (light) chrome for the widgets below. Before F3
       those defaults bled through the dark ground on the three pages that use
       them heavily. Same vocabulary as stTextInput/stNumberInput above:
       card-lift fill, hairline border, saffron accent on focus/checked. */

    /* text_area — Intraday ORB ticker list. */
    .stTextArea textarea {
        background: #0e0e10 !important;
        border-color: rgba(255,255,255,.1) !important;
        border-radius: 6px;
        color: var(--ink) !important;
        font-family: var(--font-mono);
    }
    .stTextArea textarea:focus-visible {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px rgba(255,149,0,.15) !important;
        outline: none !important;
    }

    /* slider — Intraday scan range. */
    .stSlider [data-baseweb="slider"] [role="slider"] {
        background: var(--accent) !important;
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px rgba(255,149,0,.12);
    }
    .stSlider [data-baseweb="slider"] > div > div:first-child {
        background: var(--accent) !important;
    }
    .stSlider [data-baseweb="slider"] > div > div:last-child {
        background: rgba(255,255,255,.12) !important;
    }

    /* radio + checkbox + toggle — Paper Trades / Angel One controls. */
    .stRadio label, .stCheckbox label {
        color: var(--ink-mid) !important;
    }
    .stRadio [data-baseweb="radio"] [role="radio"][aria-checked="true"] > div,
    .stRadio [data-baseweb="radio"] [aria-checked="true"] {
        border-color: var(--accent) !important;
        background: var(--accent) !important;
    }
    .stCheckbox [data-baseweb="checkbox"] [aria-checked="true"] {
        background: var(--accent) !important;
        border-color: var(--accent) !important;
    }
    .stRadio [role="radio"]:focus-visible,
    .stCheckbox [role="checkbox"]:focus-visible {
        outline: 3px solid rgba(255,149,0,.25) !important;
        outline-offset: 2px;
    }
    /* toggle — Streamlit renders this as a BaseWeb switch. */
    [data-baseweb="switch"][aria-checked="true"] > div:first-child {
        background: var(--accent) !important;
    }
    [data-baseweb="switch"] > div:first-child > div {
        background: var(--ink) !important;
    }

    /* download_button — matches stButton chrome (Streamlit renders it as a
       separate testid otherwise the primary/secondary rules don't reach it). */
    [data-testid="stDownloadButton"] button {
        border-radius: 10px; font-weight: 600; letter-spacing: .2px;
        border: 1px solid rgba(255,255,255,.08);
        background: rgba(255,255,255,.04);
        color: var(--ink);
        transition: all .15s ease;
    }
    [data-testid="stDownloadButton"] button:hover {
        border-color: rgba(255,149,0,.5); color: var(--accent);
    }
    [data-testid="stDownloadButton"] button:focus-visible {
        outline: 3px solid rgba(255,149,0,.25) !important;
        outline-offset: 2px;
    }

    /* ── Expanders ─────────────────────────────────────────────────────────────
       §9.2 · same card-lift + hairline pairing as .glass-panel and stMetric,
       so a collapsed "Data health" tile reads as part of the same surface
       vocabulary rather than a Streamlit default. */
    [data-testid="stExpander"] {
        background: var(--card-lift);
        border: 1px solid var(--hairline) !important;
        border-radius: var(--r-base);
    }

    /* ── DataFrames ──────────────────────────────────────────────────────────── */
    [data-testid="stDataFrame"] { border-radius: 6px; overflow: hidden; }
    [data-testid="stDataFrame"] thead th {
        background: #0e0e10 !important; color: #55575e !important;
        font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
        font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.07) !important;
    }
    [data-testid="stDataFrame"] tbody td { color: #c8cad0 !important; font-family:'IBM Plex Mono',monospace; font-size:13px; }
    [data-testid="stDataFrame"] tbody tr:hover td { background: rgba(255,149,0,.05) !important; }

    /* ── Order form ──────────────────────────────────────────────────────────── */
    .order-buy  { background:rgba(22,199,132,.06); border:1px solid rgba(22,199,132,.3); border-radius:10px; padding:18px; }
    .order-sell { background:rgba(255,77,77,.06);  border:1px solid rgba(255,77,77,.3);  border-radius:10px; padding:18px; }

    /* ── Custom metric box ─────────────────────────────────────────────────────
       §9.2 · card-lift + hairline pairing. Label size / letter-spacing
       aligned with .t-label so the two vocabularies read as one. */
    .metric-box       { background: var(--card-lift); border-radius: var(--r-base); padding:16px; text-align:center; border:1px solid var(--hairline); }
    .metric-val       { font-family: var(--font-mono); font-size:27px; font-weight:700; margin:4px 0; letter-spacing:-.3px; color: var(--ink); }
    .metric-lbl       { font-size:11px; color: var(--dim); text-transform:uppercase; letter-spacing:.12em; font-weight:600; }
    .metric-delta-pos { color: var(--bull); font-size:13px; font-weight:600; font-family: var(--font-mono); }
    .metric-delta-neg { color: var(--bear); font-size:13px; font-weight:600; font-family: var(--font-mono); }

    /* ── Section divider ─────────────────────────────────────────────────────── */
    .sec-div { display:flex; align-items:center; gap:12px; margin:28px 0 18px; }
    .sec-div-label { font-size:11px; font-weight:700; color:#55575e; text-transform:uppercase; letter-spacing:1.5px; white-space:nowrap; }
    .sec-div-line  { flex:1; height:1px; background:linear-gradient(90deg,rgba(255,255,255,.09),transparent); }

    /* ── Glass panel — reserved for hero/summary panels only (soft radius tier).
       §9.2.2 — the "NSVisualEffectView" trick: a barely-visible 2 % white
       overlay on the pure-black ground gives depth without a heavier card
       fill, and the amber aurora at the top of the page shows through
       cleanly. Every subsequent hero, morning-brief, and posture card
       inherits this. */
    .glass-panel {
        background: var(--card-lift);
        border: 1px solid var(--hairline);
        border-radius: var(--r-soft); padding: 20px;
        backdrop-filter: blur(4px);
        -webkit-backdrop-filter: blur(4px);
    }

    /* ── Scrollbars ──────────────────────────────────────────────────────────── */
    ::-webkit-scrollbar { width:6px; height:6px; }
    ::-webkit-scrollbar-thumb { background:#1c1c20; border-radius:3px; }
    ::-webkit-scrollbar-thumb:hover { background:#2a2a30; }
    ::-webkit-scrollbar-track { background:transparent; }

    /* ── Alerts & info boxes ─────────────────────────────────────────────────── */
    [data-testid="stAlert"] { border-radius: 8px; }

    /* ── F7b · colour-blind pattern layer ──────────────────────────────────────
       --bull / --bear are the only signal on many delta surfaces; ~5% of men
       have red-green colour vision deficiency. These utility classes pair
       the colour with a shape signal (up/down triangle) via ::before so any
       new caller can get shape+colour just by adding the class — no need to
       remember to prefix the string with ▲/▼. The existing `.metric-delta-
       pos/neg` classes already had callers prefixing the arrow manually;
       these are the migration target for anything new. */
    .delta-pos, .delta-neg { font-variant-numeric: tabular-nums; }
    .delta-pos { color: var(--bull); }
    .delta-neg { color: var(--bear); }
    .delta-pos::before { content: "\25B2  "; font-size: 0.85em; }  /* ▲ */
    .delta-neg::before { content: "\25BC  "; font-size: 0.85em; }  /* ▼ */

    /* ── Animations — functional only (live-signal pulse), not decorative ──────── */
    @keyframes pulse-green { 0%,100%{box-shadow:0 0 0 0 rgba(22,199,132,.35)} 50%{box-shadow:0 0 0 8px rgba(22,199,132,0)} }
    @keyframes pulse-red   { 0%,100%{box-shadow:0 0 0 0 rgba(255,77,77,.35)}  50%{box-shadow:0 0 0 8px rgba(255,77,77,0)}  }
    .pulse-green { animation:pulse-green 2s infinite; }
    .pulse-red   { animation:pulse-red 2s infinite; }

    /* UX3 · live-tick one-shot pulse — fires once when a tracked value
       ticks up or down between reruns. Distinct from .pulse-green/red
       (which loop for card-state emphasis on Paper Trades). The tick
       variant is a single 1.4s pass so the eye catches the change
       without a permanent aura. Callers set the class conditionally
       based on session-state diff — the animation runs on the next
       paint and stops on its own. */
    @keyframes tick-pulse-up-kf {
        0%   { box-shadow: 0 0 0 0 rgba(22,199,132,.55); }
        60%  { box-shadow: 0 0 0 10px rgba(22,199,132,0); }
        100% { box-shadow: 0 0 0 0 rgba(22,199,132,0); }
    }
    @keyframes tick-pulse-down-kf {
        0%   { box-shadow: 0 0 0 0 rgba(255,77,77,.55); }
        60%  { box-shadow: 0 0 0 10px rgba(255,77,77,0); }
        100% { box-shadow: 0 0 0 0 rgba(255,77,77,0); }
    }
    .tick-pulse-up   { animation: tick-pulse-up-kf   1.4s ease-out 1; }
    .tick-pulse-down { animation: tick-pulse-down-kf 1.4s ease-out 1; }

    /* ── Ticker tape — the one signature element: a lit "dealing room" strip ──── */
    @keyframes ticker-scroll { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
    .ticker-wrap {
        overflow:hidden; padding:9px 0; margin:8px 0;
        border-top:1px solid rgba(255,149,0,.3);
        border-bottom:1px solid rgba(255,255,255,.05);
        background:linear-gradient(180deg, rgba(255,149,0,.04), transparent);
    }
    .ticker-content {
        display:inline-block; white-space:nowrap; animation:ticker-scroll 80s linear infinite;
        font-size:13px; font-family:'IBM Plex Mono','Courier New',monospace; letter-spacing:.2px;
    }
    .ticker-wrap:hover .ticker-content { animation-play-state:paused; }

    /* ── F6 · Loading skeletons — shimmer placeholders for slow surfaces ───── */
    @keyframes cc-skel-shimmer {
        0%   { background-position: -420px 0 }
        100% { background-position:  420px 0 }
    }
    .cc-skel {
        background: linear-gradient(90deg,
            rgba(255,255,255,0.02) 0%,
            rgba(255,255,255,0.06) 45%,
            rgba(255,255,255,0.12) 50%,
            rgba(255,255,255,0.06) 55%,
            rgba(255,255,255,0.02) 100%);
        background-size: 840px 100%;
        animation: cc-skel-shimmer 1.6s linear infinite;
        border-radius: 6px;
        display: block;
    }
    .cc-skel-card {
        background: var(--card-lift, rgba(255,255,255,0.02));
        border: 1px solid var(--hairline-soft, rgba(255,255,255,0.08));
        border-radius: 10px;
        padding: 14px 16px;
        margin: 8px 0;
    }
    @media (prefers-reduced-motion: reduce) {
        .cc-skel { animation: none; }
    }
    </style>""",
        unsafe_allow_html=True,
    )




# ── Design helper functions (NSE Pro — from trading-dashboard-design skill) ───
def _glass_metric(label: str, value: str, delta: str = "", delta_pos: bool = True) -> str:
    d_color = "#16c784" if delta_pos else "#ff4d4d"
    d_sym   = "▲" if delta_pos else "▼"
    d_html  = (f'<div style="font-size:12px;color:{d_color};margin-top:4px;font-weight:600;font-family:\'IBM Plex Mono\',monospace">'
               f'{d_sym} {delta}</div>') if delta else ""
    return (
        f'<div class="glass-panel" style="text-align:center;min-height:80px">'
        f'<div style="font-size:11px;color:#55575e;text-transform:uppercase;letter-spacing:1.2px;font-weight:600">{label}</div>'
        f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:23px;font-weight:700;color:#edeef0;margin-top:6px;letter-spacing:-.3px">{value}</div>'
        f'{d_html}</div>'
    )

def _section_div(label: str, icon: str = "") -> None:
    st.markdown(
        f'<div class="sec-div"><div class="sec-div-label">{icon}&nbsp;{label}</div>'
        f'<div class="sec-div-line"></div></div>',
        unsafe_allow_html=True,
    )

def _spacer(size: str = "md") -> None:
    px = {"sm": "12px", "md": "24px", "lg": "40px"}.get(size, "24px")
    st.markdown(f'<div style="height:{px}"></div>', unsafe_allow_html=True)

def _signal_card(ticker, action, price, entry, stop, target, reason, score=None, sector="") -> str:
    COLORS = {
        "BUY":  ("#16c784", "rgba(22,199,132,.12)"),
        "SELL": ("#ff4d4d", "rgba(255,77,77,.12)"),
        "HOLD": ("#f2a93b", "rgba(242,169,59,.12)"),
        "WATCH":("#ff9500", "rgba(255,149,0,.12)"),
    }
    tc, bc = COLORS.get(action, COLORS["HOLD"])
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0.01 else 0
    sc_html = (f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:28px;font-weight:700;color:{tc}">{score}</div>'
               f'<div style="font-size:10px;color:#55575e">SCORE</div>') if score is not None else ""
    sect_html = (f'<span style="font-size:11px;color:#55575e;font-weight:400;margin-left:8px">{sector}</span>'
                 if sector else "")
    return (
        f'<div style="background:{bc};border:1px solid {tc}44;'
        f'border-left:3px solid {tc};border-radius:10px;padding:16px 20px;margin:8px 0;'
        f'display:flex;align-items:flex-start;gap:16px">'
        f'<div style="min-width:60px;text-align:center">{sc_html}'
        f'<div style="background:{bc};color:{tc};border:1px solid {tc};border-radius:6px;'
        f'padding:4px 10px;font-size:13px;font-weight:700;letter-spacing:1px;margin-top:4px">{action}</div></div>'
        f'<div style="flex:1">'
        f'<div style="font-size:18px;font-weight:700;color:#edeef0">{ticker}{sect_html}</div>'
        f'<div style="font-size:12px;color:#55575e;margin:4px 0">{reason}</div>'
        f'<div style="display:flex;gap:20px;margin-top:10px;font-size:13px;font-family:\'IBM Plex Mono\',monospace">'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">LTP</span><br><b style="color:#c8cad0">₹{price:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">ENTRY</span><br><b style="color:#c8cad0">₹{entry:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">STOP</span><br><b style="color:#ff4d4d">₹{stop:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">TARGET</span><br><b style="color:#16c784">₹{target:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">R:R</span><br><b style="color:{tc}">{rr:.1f}x</b></div>'
        f'</div></div></div>'
    )
