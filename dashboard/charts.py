"""Altair charts for the deals dashboard.

Categorical hues come from the app theme (`chartCategoricalColors` in
`.streamlit/config.toml`) so they stay identical across every chart. Only the
two-state and neutral colors are resolved here, because they carry meaning
("this row has no discount info") rather than identity.
"""

from typing import Final

import altair as alt
import pandas as pd
import streamlit as st

# Chart surface + neutral ink per theme. The series hues live in config.toml.
_TOKENS: Final[dict[str, dict[str, str]]] = {
    "light": {"surface": "#fcfcfb", "accent": "#2a78d6", "muted": "#7d7b74"},
    "dark": {"surface": "#1a1a19", "accent": "#3987e5", "muted": "#8a8880"},
}


def tokens() -> dict[str, str]:
    """Colors for the active theme, defaulting to light when unknown."""
    theme = getattr(st.context, "theme", None)
    mode = getattr(theme, "type", "light") or "light"
    return _TOKENS.get(mode, _TOKENS["light"])


def category_donut(distribution: pd.DataFrame) -> alt.LayerChart:
    """Share of today's deals by category.

    A donut is the form the deal mix is usually read in, so slices are ordered
    by size, capped at eight, and every slice carries a direct label — identity
    never rests on color alone.
    """
    palette = tokens()
    order = distribution["category"].tolist()

    base = alt.Chart(distribution).encode(
        theta=alt.Theta("deals:Q", stack=True),
        color=alt.Color(
            "category:N",
            sort=order,
            title="Category",
            legend=alt.Legend(orient="right", labelLimit=180),
        ),
        order=alt.Order("deals:Q", sort="descending"),
        tooltip=[
            alt.Tooltip("category:N", title="Category"),
            alt.Tooltip("deals:Q", title="Deals"),
            alt.Tooltip("share:Q", title="Share", format=".1%"),
        ],
    )

    arcs = base.mark_arc(
        innerRadius=72,
        outerRadius=126,
        stroke=palette["surface"],
        strokeWidth=2,
        cornerRadius=2,
    )

    labels = base.mark_text(radius=150, fontSize=12, fontWeight=500).encode(
        text=alt.condition(
            alt.datum.share >= 0.05, alt.Text("share:Q", format=".0%"), alt.value("")
        ),
        color=alt.value(palette["muted"]),
    )

    return (arcs + labels).properties(height=320)


def best_price_bars(winners: pd.DataFrame, column: str, label: str) -> alt.Chart:
    """The winning product per category on a single measure, biggest first."""
    palette = tokens()
    axis_format = "$,.2f" if column in {"deal_price", "savings_abs"} else ".0f"
    tooltip_format = "$,.2f" if column in {"deal_price", "savings_abs"} else ".1f"

    return (
        alt.Chart(winners)
        .mark_bar(cornerRadiusEnd=4, height={"band": 0.7}, color=palette["accent"])
        .encode(
            x=alt.X(f"{column}:Q", title=label, axis=alt.Axis(format=axis_format)),
            y=alt.Y("category_label:N", title=None, sort="-x" if column != "deal_price" else "x"),
            tooltip=[
                alt.Tooltip("category_label:N", title="Category"),
                alt.Tooltip("title:N", title="Product"),
                alt.Tooltip("brand:N", title="Brand"),
                alt.Tooltip("deal_price:Q", title="Deal price", format="$,.2f"),
                alt.Tooltip("list_price:Q", title="List price", format="$,.2f"),
                alt.Tooltip("discount_pct:Q", title="Discount", format=".1f"),
            ],
        )
        .properties(height=alt.Step(26))
    )


def coverage_bars(coverage: pd.DataFrame) -> alt.Chart:
    """Per category, how much of the feed publishes a discount at all."""
    palette = tokens()

    return (
        alt.Chart(coverage)
        .mark_bar(
            cornerRadiusEnd=4,
            height={"band": 0.7},
            stroke=palette["surface"],
            strokeWidth=1,
        )
        .encode(
            x=alt.X("products:Q", title="Products on the deals page", stack=True),
            y=alt.Y("category_label:N", title=None, sort=alt.EncodingSortField("total", order="descending")),
            color=alt.Color(
                "info_state:N",
                title=None,
                scale=alt.Scale(
                    domain=["Discount info", "No discount info"],
                    range=[palette["accent"], palette["muted"]],
                ),
                legend=alt.Legend(orient="top"),
            ),
            order=alt.Order("info_state:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("category_label:N", title="Category"),
                alt.Tooltip("info_state:N", title="State"),
                alt.Tooltip("products:Q", title="Products"),
            ],
        )
        .properties(height=alt.Step(24))
    )
