import re
from datetime import datetime, timezone
from typing import Any

from pandas import DataFrame, Timestamp, to_numeric, cut, to_datetime


def dig(obj: Any, *path: str | int, default: Any = None) -> Any:
    """Safe nested lookup: _dig(d, 'price', 'priceToPay', 'price')."""
    cur = obj
    for key in path:
        if isinstance(key, int):
            if not isinstance(cur, list) or len(cur) <= key:
                return default
            cur = cur[key]
        else:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
    return cur if cur is not None else default


def fragment_text(badge_part: Any) -> str:
    """Join a badge's text fragments ('30% off', 'Ends in ')."""
    fragments = dig(badge_part, "content", "fragments", default=[]) or []
    return "".join(f.get("text", "") for f in fragments if isinstance(f, dict)).strip()


def to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def countdown_target(badge: Any) -> str | None:
    for fragment in dig(badge, "messaging", "content", "fragments", default=[]) or []:
        target = dig(fragment, "countdownTimer", "targetTime")
        if target:
            return target
    return None


def flatten(product: dict[str, Any], brands: dict[str, str], currency: str) -> dict[str, Any]:
    """One raw Amazon product dict -> one flat, analysis-ready record."""
    badge_label = fragment_text(dig(product, "dealBadge", "label"))
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", badge_label)
    deal_price = to_float(dig(product, "price", "priceToPay", "price"))
    list_price = to_float(dig(product, "price", "basisPrice", "price"))
    link = product.get("link") or ""
    brand_id = dig(product, "meta", "brandId")

    return {
        "asin": product.get("asin"),
        "title": product.get("title"),
        "brand": brands.get(str(brand_id)) or dig(product, "brandLogo", "altText"),
        "brand_id": brand_id,
        "product_url": f"https://www.amazon.com{link}" if link.startswith("/") else link,
        "image_url": dig(product, "image", "lowRes", "baseUrl"),
        "currency": currency,
        "deal_price": deal_price,
        "list_price": list_price,
        "badge_discount_pct": float(percent_match.group(1)) if percent_match else None,
        "badge_label": badge_label or None,
        "deal_type": dig(product, "dealDetails", "type"),
        "deal_state": dig(product, "dealDetails", "state"),
        "deal_id": dig(product, "dealDetails", "id"),
        "percent_claimed": dig(product, "dealDetails", "percentClaimed"),
        "deal_ends_at": countdown_target(product.get("dealBadge")),
        "rating": to_float(dig(product, "customerReviews", "rating", "shortDisplayString")),
        "review_count": dig(product, "customerReviews", "count", "value"),
        "pct_5_star": dig(product, "customerReviews", "histogram", "fiveStar", "percentage"),
        "pct_1_star": dig(product, "customerReviews", "histogram", "oneStar", "percentage"),
        "category": dig(product, "productCategory", "symbol"),
        "product_type": dig(product, "productCategory", "productType"),
        "department_ids": ",".join(dig(product, "meta", "departmentIds", default=[]) or []),
        "has_variations": bool(product.get("twisterVariations")),
        "is_pinned": bool(dig(product, "meta", "isPinned", default=False)),
        "source_filter": product.get("_source_filter"),
    }


def add_derived_columns(df: DataFrame, scraped_at: str | None = None) -> DataFrame:
    """Add the business-facing metrics the BI team actually slices on."""
    df = df.copy()
    now =Timestamp(scraped_at or datetime.now(timezone.utc).isoformat())

    for column in ("deal_price", "list_price", "badge_discount_pct", "rating",
                   "review_count", "percent_claimed", "pct_5_star", "pct_1_star"):
        df[column] = to_numeric(df[column], errors="coerce")

    computed = (1 - df["deal_price"] / df["list_price"]) * 100
    df["discount_pct"] = df["badge_discount_pct"].fillna(computed.round(1))
    df["discount_pct"] = df["discount_pct"].clip(lower=0, upper=100)
    df["savings_abs"] = (df["list_price"] - df["deal_price"]).round(2)

    df["deal_ends_at"] = to_datetime(df["deal_ends_at"], errors="coerce", utc=True)
    df["hours_remaining"] = ((df["deal_ends_at"] - now).dt.total_seconds() / 3600).round(1)
    df["is_time_limited"] = df["deal_ends_at"].notna()

    df["price_band"] = cut(
        df["deal_price"],
        bins=[0, 10, 25, 50, 100, 250, float("inf")],
        labels=["<$10", "$10–25", "$25–50", "$50–100", "$100–250", "$250+"],
    )
    df["discount_band"] = cut(
        df["discount_pct"],
        bins=[-0.01, 10, 20, 30, 40, 50, 100],
        labels=["0–10%", "10–20%", "20–30%", "30–40%", "40–50%", "50%+"],
    )
    df["review_band"] = cut(
        df["review_count"],
        bins=[-1, 100, 1_000, 10_000, 100_000, float("inf")],
        labels=["<100", "100–1k", "1k–10k", "10k–100k", "100k+"],
    )
    df["deal_score"] = (
        df["discount_pct"].fillna(0) * 0.6
        + df["rating"].fillna(0) * 4
        + df["review_count"].fillna(0).clip(upper=100_000) / 100_000 * 20
    ).round(1)
    df["scraped_at"] = now
    return df


def normalize_deals(raw: dict[str, Any], derived: bool = True) -> DataFrame:
    """Turn a `scrape_deals` payload into a tidy, typed DataFrame."""
    brands, currency = raw.get("brands", {}), raw.get("currency", "USD")
    rows = [flatten(p, brands, currency) for p in raw["deals"]]
    df = DataFrame(rows).drop_duplicates(subset="asin").reset_index(drop=True)
    if derived:
        df = add_derived_columns(df, raw.get("scraped_at"))
    return df


def data_quality_report(df: DataFrame) -> DataFrame:
    """Per-column fill rate — the first thing to show a BI stakeholder."""
    return (
        DataFrame(
            {
                "non_null": df.notna().sum(),
                "fill_rate": (df.notna().mean() * 100).round(1),
                "dtype": df.dtypes.astype(str),
            }
        )
        .sort_values("fill_rate")
        .rename_axis("column")
        .reset_index()
    )
