"""Loading and shaping the scraped Amazon deals feed for the dashboard.

The scrape returns two kinds of rows and the dashboard keeps both:

* **Live deals** — rows carrying a deal badge, so a discount percentage is known.
* **Listings** — rows the deals page surfaced without any price or badge. They
  still identify a brand, a category and a product, so they are kept and used to
  measure how much of the feed actually exposes discount information.

Nothing is dropped for being NA; the NA pattern *is* one of the signals.
"""

from pathlib import Path
from typing import Final

import pandas as pd
import streamlit as st

DATA_FILE: Final[Path] = Path(__file__).resolve().parent.parent / "amazon_deals.csv"

#: Amazon's internal ``gl_*`` category symbols, in shopper-facing wording.
CATEGORY_LABELS: Final[dict[str, str]] = {
    "gl_apparel": "Apparel",
    "gl_audible": "Audible",
    "gl_automotive": "Automotive",
    "gl_beauty": "Beauty",
    "gl_biss": "Industrial & scientific",
    "gl_digital_devices_4": "Amazon devices",
    "gl_digital_text_2": "Kindle & books",
    "gl_drugstore": "Health & household",
    "gl_electronics": "Electronics",
    "gl_furniture": "Furniture",
    "gl_grocery": "Grocery",
    "gl_home": "Home",
    "gl_home_entertainment": "Home entertainment",
    "gl_home_improvement": "Home improvement",
    "gl_jewelry": "Jewelry",
    "gl_kitchen": "Kitchen",
    "gl_lawn_and_garden": "Lawn & garden",
    "gl_luggage": "Luggage",
    "gl_luxury_beauty": "Luxury beauty",
    "gl_major_appliances": "Appliances",
    "gl_office_product": "Office",
    "gl_pc": "Computers",
    "gl_pet_products": "Pet supplies",
    "gl_shoes": "Shoes",
    "gl_sports": "Sports & outdoors",
    "gl_tools": "Tools",
    "gl_toy": "Toys & games",
    "gl_wireless": "Phones & wireless",
}

DEAL_KIND_LABELS: Final[dict[str, str]] = {
    "LIGHTNING_DEAL": "Lightning deal",
    "BEST_DEAL": "Best deal",
}

LISTING_KIND: Final[str] = "Listing (no discount info)"

UNKNOWN_BRAND: Final[str] = "Unbranded / not mapped"

RANKINGS: Final[dict[str, tuple[str, bool]]] = {
    "Biggest % off": ("discount_pct", False),
    "Biggest $ saved": ("savings_abs", False),
    "Lowest price": ("deal_price", True),
    "Best deal score": ("deal_score", False),
}


def prettify_category(symbol: str) -> str:
    """``gl_home_improvement`` -> ``Home improvement``, with a sane fallback."""
    if symbol in CATEGORY_LABELS:
        return CATEGORY_LABELS[symbol]
    return symbol.removeprefix("gl_").replace("_", " ").capitalize()


@st.cache_data(ttl="30m")
def load_deals(path: str | Path = DATA_FILE) -> pd.DataFrame:
    """Read the scraped feed and add the columns the dashboard slices on."""
    df = pd.read_csv(path)

    for column in ("deal_ends_at", "scraped_at"):
        df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)

    df["category_label"] = df["category"].map(prettify_category)

    # NA prices are kept: a missing brand still gets a bucket so every row is
    # attributable to something on the brand views.
    df["brand"] = df["brand"].fillna(UNKNOWN_BRAND)

    df["has_price"] = df["deal_price"].notna()
    df["has_discount_info"] = df["discount_pct"].notna()
    df["deal_kind"] = df["deal_type"].map(DEAL_KIND_LABELS).fillna(LISTING_KIND)
    df["info_state"] = df["has_discount_info"].map(
        {True: "Discount info", False: "No discount info"}
    )

    # `hours_remaining` was computed against the scrape timestamp, so a deal that
    # already expired at scrape time is not a live countdown.
    df["ends_soon"] = df["hours_remaining"].le(6) & df["hours_remaining"].ge(0)

    return df


def snapshot_time(df: pd.DataFrame) -> pd.Timestamp | None:
    """When the feed was scraped — every 'remaining' figure is relative to this."""
    stamps = df["scraped_at"].dropna()
    return stamps.max() if not stamps.empty else None


def apply_filters(
    df: pd.DataFrame,
    categories: list[str],
    kinds: list[str],
    min_discount: float,
    price_range: tuple[float, float] | None,
    search: str,
) -> pd.DataFrame:
    """Cheap, non-cached filtering applied on top of the cached load."""
    out = df
    if categories:
        out = out[out["category_label"].isin(categories)]
    if kinds:
        out = out[out["deal_kind"].isin(kinds)]
    if min_discount > 0:
        # Rows without discount info cannot satisfy a discount floor.
        out = out[out["discount_pct"].fillna(-1) >= min_discount]
    if price_range is not None:
        low, high = price_range
        priced = out["deal_price"].between(low, high)
        # Keep unpriced rows visible; a price slider should not silently erase
        # the part of the feed the dashboard is meant to call out.
        out = out[priced | out["deal_price"].isna()]
    if search:
        needle = search.strip().lower()
        hits = (
            out["title"].str.lower().str.contains(needle, na=False)
            | out["brand"].str.lower().str.contains(needle, na=False)
        )
        out = out[hits]
    return out


def deals_of_the_day(df: pd.DataFrame, limit: int = 9) -> pd.DataFrame:
    """The headline deals: discounted, still available, best score first."""
    live = df[df["has_discount_info"] & df["deal_state"].eq("AVAILABLE")]
    return live.sort_values(
        ["ends_soon", "deal_score", "discount_pct"], ascending=[False, False, False]
    ).head(limit)


def best_per_category(df: pd.DataFrame, ranking: str) -> pd.DataFrame:
    """One winning product per category under the chosen ranking."""
    column, ascending = RANKINGS[ranking]
    pool = df[df["has_price"]] if column == "deal_price" else df[df["has_discount_info"]]
    pool = pool[pool[column].notna()]
    if pool.empty:
        return pool
    winners = pool.sort_values(column, ascending=ascending).groupby(
        "category_label", as_index=False, sort=False
    ).head(1)
    return winners.sort_values(column, ascending=ascending)


def category_distribution(df: pd.DataFrame, top_n: int = 7) -> pd.DataFrame:
    """Share of today's deals per category, tail folded into 'Other'.

    Categorical hues are assigned in a fixed order and never cycled, so the tail
    beyond `top_n` folds into a single neutral bucket rather than inventing hues.
    """
    live = df[df["has_discount_info"]]
    counts = live["category_label"].value_counts()
    head = counts.head(top_n)
    tail_total = int(counts.iloc[top_n:].sum())

    rows = [{"category": name, "deals": int(value)} for name, value in head.items()]
    if tail_total:
        rows.append({"category": "Other", "deals": tail_total})

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["share"] = out["deals"] / out["deals"].sum()
    return out


def discount_info_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per category: how many rows carry discount info vs. how many do not."""
    grouped = (
        df.groupby(["category_label", "info_state"], observed=True)
        .size()
        .reset_index(name="products")
    )
    totals = grouped.groupby("category_label")["products"].transform("sum")
    grouped["total"] = totals
    return grouped.sort_values(["total", "category_label"], ascending=[False, True])


def brand_coverage(df: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    """Brands ranked by footprint, showing which ones expose discount info.

    This is the view the NA-price rows pay for: they contribute the brand's
    presence on the deals page even when no price was published.
    """
    grouped = (
        df.groupby("brand", observed=True)
        .agg(
            products=("asin", "size"),
            with_discount=("has_discount_info", "sum"),
            avg_discount=("discount_pct", "mean"),
            best_discount=("discount_pct", "max"),
            categories=("category_label", "nunique"),
        )
        .reset_index()
    )
    grouped["coverage"] = grouped["with_discount"] / grouped["products"]
    grouped["no_discount"] = grouped["products"] - grouped["with_discount"]
    return grouped.sort_values(
        ["products", "with_discount"], ascending=[False, False]
    ).head(limit)
