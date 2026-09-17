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
}
# `deal_score` is deliberately absent. The scrape captured no ratings or review
# counts, so the score collapses to 0.6 x discount_pct and would only duplicate
# "Biggest % off". See `data_gaps`.


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
    """The headline deals: discounted, still available, expiring ones first.

    Ranked on discount depth, then cash saved. The `deal_score` column is not
    used: with ratings and review counts absent from this scrape it carries no
    information that `discount_pct` does not already carry.
    """
    live = df[df["has_discount_info"] & df["deal_state"].eq("AVAILABLE")]
    return live.sort_values(
        ["ends_soon", "discount_pct", "savings_abs"], ascending=[False, False, False]
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


def data_gaps(df: pd.DataFrame) -> list[str]:
    """Columns the scrape did not populate, stated plainly.

    Surfaced in the app so an empty column reads as a known limitation of the
    capture rather than as an analysis that quietly ignored it.
    """
    total = len(df)
    gaps: list[str] = []

    rated = int(df["rating"].notna().sum())
    if rated == 0 and total:
        gaps.append(
            f"**Ratings and review counts: 0 of {total:,} rows captured.** The deals "
            "page renders them client-side, so the scrape never saw them. Every "
            "quality signal below is therefore price-based only, and the "
            "`deal_score` column collapses to 0.6 x discount — it is not used for "
            "ranking anywhere in this app."
        )

    countdowns = int(df["deal_ends_at"].notna().sum())
    if countdowns < total:
        gaps.append(
            f"**Countdowns: {countdowns} of {total:,} deals carry an end time.** Only "
            "lightning deals publish one, so 'ends soon' covers that slice alone — "
            "the rest may still expire without warning."
        )

    claimed = int(df["percent_claimed"].notna().sum())
    if claimed < total:
        gaps.append(
            f"**Stock claimed: {claimed} of {total:,} rows report it.** Inventory "
            "pressure can only be read for lightning deals."
        )

    return gaps


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """``3 brands`` / ``1 brand`` — findings are read by people, not parsed."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count:,} {word}"


def headline_findings(df: pd.DataFrame) -> list[str]:
    """The conclusions, stated — not left for the reader to derive from charts.

    Recomputed against whatever is currently filtered, so the wording always
    matches the numbers on screen.
    """
    findings: list[str] = []
    total = len(df)
    if not total:
        return findings

    live = df[df["has_discount_info"]]
    dark = df[~df["has_discount_info"]]

    # 1. How much of the "deals" page is actually a deal.
    if len(dark):
        overstatement = total / len(live) if len(live) else None
        inflation = (
            f"Counting every row as a deal overstates the real offer by {overstatement:.1f}x."
            if overstatement
            else "Not one row here carries a measurable offer."
        )
        findings.append(
            f"**{len(dark)/total:.0%} of the deals page quotes no discount at all.** "
            f"{_plural(len(dark), 'product')} of {total:,} "
            f"{'is' if len(dark) == 1 else 'are'} surfaced with no price "
            f"and no badge; {_plural(len(live), 'product')} "
            f"{'carries' if len(live) == 1 else 'carry'} a measurable offer. {inflation}"
        )

    if live.empty:
        return findings

    # 2. Brands present in volume that never publish a discount.
    silent = (
        dark.groupby("brand", observed=True)
        .agg(listings=("asin", "size"))
        .join(
            live.groupby("brand", observed=True).size().rename("deals"), how="left"
        )
        .fillna({"deals": 0})
    )
    silent = silent[(silent["deals"] == 0) & (silent.index != UNKNOWN_BRAND)]
    silent = silent.sort_values("listings", ascending=False)
    if not silent.empty:
        top = silent.head(4)
        named = ", ".join(top.index.tolist())
        listings = int(top["listings"].sum())
        findings.append(
            f"**{_plural(len(silent), 'brand')} "
            f"{'appears' if len(silent) == 1 else 'appear'} only without a price.** "
            f"{named} {'accounts' if len(top) == 1 else 'account'} for "
            f"{_plural(listings, 'listing')} and "
            f"{'has' if len(top) == 1 else 'have'} not published a single discount "
            "today. They hold shelf placement without a published price cut — a "
            "different competitive posture than a discounter, and worth tracking "
            "apart from them."
        )

    # 3. Whether one category is distorting the page-wide discount figure. The
    # distorter is the category whose removal moves the median most — not
    # simply the largest one, which may sit right on the median and shift
    # nothing.
    by_category = live.groupby("category_label", observed=True)["discount_pct"]
    sizes = by_category.size()
    overall = live["discount_pct"].median()

    shifts: dict[str, float] = {}
    for name in sizes.index:
        without = live[live["category_label"] != name]["discount_pct"]
        if not without.empty:
            shifts[name] = overall - without.median()

    if shifts:
        culprit = max(shifts, key=lambda name: abs(shifts[name]))
        delta = shifts[culprit]
        if abs(delta) >= 1:
            findings.append(
                f"**{culprit} alone moves the page-wide discount figure by "
                f"{delta:+.0f} points.** It is {sizes[culprit] / len(live):.0%} of "
                f"today's deals at a {by_category.mean()[culprit]:.0f}% average "
                f"discount; drop it and the median falls from {overall:.0f}% to "
                f"{overall - delta:.0f}%. Quote the median per category, never "
                "across the page."
            )

    # 4. Where the deep discounts actually are (categories with enough deals to trust).
    credible = sizes[sizes >= 5].index
    if len(credible) >= 2:
        means = by_category.mean().loc[credible].sort_values(ascending=False)
        top, bottom = means.index[0], means.index[-1]
        findings.append(
            f"**Discount depth is category-bound, not page-wide: {top} averages "
            f"{means.iloc[0]:.0f}% off while {bottom} averages {means.iloc[-1]:.0f}%.** "
            f"Across categories with 5+ deals the spread is {means.iloc[0] - means.iloc[-1]:.0f} "
            "points, so a single 'today's discount' figure hides more than it shows."
        )

    # 5. What the shelf actually costs.
    priced = df[df["has_price"]]
    if not priced.empty:
        cheap = (priced["deal_price"] < 50).mean()
        findings.append(
            f"**This is a low-ticket shelf: {cheap:.0%} of priced products are under "
            f"$50, median ${priced['deal_price'].median():,.2f}.** Total advertised "
            f"saving across every discounted item is only "
            f"${live['savings_abs'].sum():,.0f} — volume plays, not margin plays."
        )

    return findings
