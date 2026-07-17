from __future__ import annotations

import html
import json
import math
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .config import StudyConfig


def _hex_color(value: float, maximum: float, *, diverging: bool) -> str:
    if pd.isna(value) or maximum <= 0:
        return "#f3f4f6"
    normalized = min(1.0, abs(value) / maximum)
    if diverging:
        target = (42, 122, 76) if value >= 0 else (184, 52, 52)
    else:
        target = (31, 78, 121)
    base = (250, 250, 250)
    rgb = tuple(round(base[i] + normalized * (target[i] - base[i])) for i in range(3))
    return "#" + "".join(f"{component:02x}" for component in rgb)


def write_heatmap_svg(
    heatmap: pd.DataFrame,
    path: str | Path,
    *,
    value_column: str,
    title: str,
    diverging: bool,
) -> None:
    """Write a dependency-free, auditable SVG heatmap."""

    if heatmap.empty:
        Path(path).write_text("<svg xmlns='http://www.w3.org/2000/svg' width='640' height='80'><text x='20' y='40'>No eligible sessions</text></svg>", encoding="utf-8")
        return
    data = heatmap.copy()
    data["cohort"] = data["event_class"] + data["important_1000_release"].map(
        {True: " + D important 10:00", False: " + no important 10:00"}
    )
    pivot = data.pivot(index="cohort", columns="bucket_et", values=value_column)
    columns = list(pivot.columns)
    rows = list(pivot.index)
    cell_w, cell_h, left, top = 58, 34, 230, 72
    width = left + cell_w * len(columns) + 24
    height = top + cell_h * len(rows) + 56
    maximum = float(pivot.abs().max().max())
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<rect width='100%' height='100%' fill='#ffffff'/>",
        f"<text x='16' y='28' font-family='Arial' font-size='18' font-weight='700'>{html.escape(title)}</text>",
        "<text x='16' y='48' font-family='Arial' font-size='11' fill='#4b5563'>Five-minute buckets, America/New_York; cell labels are basis points</text>",
    ]
    for column_index, column in enumerate(columns):
        x = left + column_index * cell_w + cell_w / 2
        parts.append(
            f"<text x='{x}' y='{top - 10}' text-anchor='middle' font-family='Arial' font-size='10' fill='#374151'>{html.escape(str(column))}</text>"
        )
    for row_index, row_label in enumerate(rows):
        y = top + row_index * cell_h
        parts.append(
            f"<text x='{left - 8}' y='{y + 22}' text-anchor='end' font-family='Arial' font-size='11' fill='#111827'>{html.escape(str(row_label))}</text>"
        )
        for column_index, column in enumerate(columns):
            value = pivot.loc[row_label, column]
            x = left + column_index * cell_w
            color = _hex_color(float(value), maximum, diverging=diverging) if pd.notna(value) else "#f3f4f6"
            label = "" if pd.isna(value) else f"{float(value):.2f}"
            parts.extend(
                [
                    f"<rect x='{x}' y='{y}' width='{cell_w - 1}' height='{cell_h - 1}' rx='2' fill='{color}'/>",
                    f"<text x='{x + cell_w / 2}' y='{y + 22}' text-anchor='middle' font-family='Arial' font-size='10' fill='#111827'>{label}</text>",
                ]
            )
    parts.append("</svg>")
    Path(path).write_text("\n".join(parts), encoding="utf-8")


def write_quality_report(
    path: str | Path,
    prices: pd.DataFrame,
    features: pd.DataFrame,
    calendar: pd.DataFrame,
) -> None:
    complete = int(features["core_windows_complete"].sum()) if not features.empty else 0
    london_complete = int(features["london_0800_1200_local_complete"].sum()) if not features.empty else 0
    spread_status = "present" if "spread" in prices and prices["spread"].notna().any() else "absent"
    zero_spread = bool("spread" in prices and prices["spread"].fillna(0).eq(0).all())
    lines = [
        "# Event-Study Data Quality Report",
        "",
        f"- Price rows: {len(prices):,}",
        f"- ET coverage: {prices.index.min()} to {prices.index.max()}",
        f"- Sessions classified: {len(features):,}",
        f"- Sessions with all core 07:30–10:30 windows complete: {complete:,}",
        f"- Sessions with complete 08:00–12:00 Europe/London range: {london_complete:,}",
        f"- Calendar events loaded: {len(calendar):,}",
        f"- Spread field: {spread_status}",
        f"- Spread is identically zero: {zero_spread}",
        "",
        "A complete clock window does not establish feed quality. Broker/feed provenance, bid/ask construction, historical calendar vintage and surprise coverage must be reviewed separately.",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_metadata(
    path: str | Path,
    *,
    config: StudyConfig,
    price_path: str,
    calendar_path: str,
    strategies_run: bool,
) -> None:
    payload = {
        "config": asdict(config),
        "price_path": str(Path(price_path).resolve()),
        "calendar_path": str(Path(calendar_path).resolve()),
        "strategies_run": strategies_run,
        "timezone_policy": "IANA America/New_York; no fixed UTC offset",
        "lifecycle_warning": "Retrospective outcomes; prohibited as entry filters",
    }
    Path(path).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def write_event_study_report(
    path: str | Path,
    *,
    features: pd.DataFrame,
    performance: pd.DataFrame | None,
    bootstrap: pd.DataFrame | None,
    minimum_sample: int,
) -> None:
    """Write a compact result index; interpretation still requires preregistered tests."""

    classes = features["event_class"].value_counts().to_dict() if not features.empty else {}
    complete = int(features["core_windows_complete"].sum()) if not features.empty else 0
    lines = [
        "# XAUUSD 08:30–10:30 Event-Study Run",
        "",
        "This report describes the run; it does not infer manipulation or authorize production changes.",
        "",
        "## Sample",
        "",
        f"- Sessions: {len(features):,}",
        f"- Complete core-window sessions: {complete:,}",
        f"- Event-class counts: `{json.dumps(classes, sort_keys=True)}`",
        f"- Minimum filled-trade cell for an unqualified metric: {minimum_sample}",
        "",
        "## Required research questions",
        "",
        "The generated `heatmap_5m.csv`, `session_features.csv`, `strategy_performance.csv` and `bootstrap_confidence_intervals.csv` contain the registered evidence for the questions below. A question remains **not adjudicated** when the relevant controlled model, confidence interval, chronological holdout or stability cells are absent.",
        "",
        "1. Is 08:30 the primary displacement window? — compare class-conditioned heatmaps and H01–H04 tests.",
        "2. Does 09:30 have an independent edge? — requires H05/H06 controls; raw 09:30 movement is insufficient.",
        "3. When should 08:30 be followed? — H08 plus standalone family A after costs.",
        "4. When should 08:30 be faded? — H07/H09 plus standalone family B after costs.",
        "5. Where does continuation deteriorate? — continuous H10 analysis and chronological validation.",
        "6. Which entry geometry is best? — paired same-trigger comparison; do not rank unmatched setup counts.",
        "7. Separate news models? — H17 interaction and out-of-sample comparison.",
        "8. Close before 10:00? — paired exit policies on important-release days (H18).",
        "9. Stable enough for production research? — requires year/direction/category/cost/feed stability; aggregate performance cannot pass.",
    ]
    if performance is not None and not performance.empty:
        all_rows = performance[
            performance["breakdown"].eq(
                "cost_scenario_spread_price+cost_scenario_slippage_per_side+exit_policy+family+geometry+structure_scale"
            )
        ]
        if not all_rows.empty:
            row = all_rows.iloc[0]
            expectancy = row.get("expectancy_after_costs_r", math.nan)
            lines.extend(
                [
                    "",
                    "## One execution-scenario summary (not a decision)",
                    "",
                    f"- Unique setups: {int(row.get('setup_count', 0)):,}",
                    f"- Candidate orders: {int(row.get('candidate_order_count', 0)):,}",
                    f"- Filled: {int(row.get('filled_count', 0)):,}",
                    f"- Spread/slippage/exit policy: {row.get('cost_scenario_spread_price')} / {row.get('cost_scenario_slippage_per_side')} / {row.get('exit_policy')}",
                    f"- Variant: {row.get('family')} / {row.get('geometry')} / {row.get('structure_scale')}",
                    f"- Net expectancy: {float(expectancy):.4f} R" if pd.notna(expectancy) else "- Net expectancy: unavailable",
                    f"- Warning: {row.get('warning', '') or 'none at aggregate level; stability gates still apply'}",
                ]
            )
    if bootstrap is not None and not bootstrap.empty:
        lines.extend(["", "Bootstrap intervals are session-clustered; rare-event intervals can still be unreliable."])
    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            "No production recommendation may be made from this file alone. Apply the hypothesis, multiplicity, chronological-holdout and cross-feed gates in `hypothesis_register.md` and `research_gate_assessment.md`.",
        ]
    )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
