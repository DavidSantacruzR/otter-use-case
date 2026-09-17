"""Amazon deals of the day — a read of one scrape of amazon.com/deals."""

import pandas as pd
import streamlit as st

from dashboard.charts import best_price_bars, category_donut, coverage_bars
from dashboard.data import (
    LISTING_KIND,
    RANKINGS,
    apply_filters,
    best_per_category,
    brand_coverage,
    category_distribution,
    data_gaps,
    deals_of_the_day,
    discount_info_coverage,
    headline_findings,
    load_deals,
    snapshot_time,
)

st.set_page_config(
    page_title="Amazon deals of the day",
    page_icon=":material/local_offer:",
    layout="wide",
)

deals = load_deals()
scraped = snapshot_time(deals)

st.title("Amazon deals of the day", icon=":material/local_offer:")
st.caption(
    f"{len(deals)} products captured from amazon.com/deals on "
    f"{scraped:%b %d, %Y at %H:%M UTC}. Countdowns are relative to that moment."
    if scraped is not None
    else f"{len(deals)} products captured from amazon.com/deals."
)

# --- Filters -----------------------------------------------------------------

categories = sorted(deals["category_label"].unique())
kinds = [k for k in deals["deal_kind"].unique() if k != LISTING_KIND] + [LISTING_KIND]
price_floor = float(deals["deal_price"].min())
price_ceiling = float(deals["deal_price"].max())

with st.sidebar:
    st.subheader("Filters", divider=False)
    picked_categories = st.multiselect("Categories", categories, placeholder="All categories")
    picked_kinds = st.multiselect("Deal type", kinds, placeholder="All types")
    min_discount = st.slider("Minimum discount (%)", 0, 80, 0, step=5)
    price_range = st.slider(
        "Deal price ($)",
        min_value=price_floor,
        max_value=price_ceiling,
        value=(price_floor, price_ceiling),
        step=1.0,
    )
    search = st.text_input("Search title or brand", placeholder="e.g. pillow, Beats")
    st.caption(
        "Products listed without a price are always kept — they are what the "
        "discount-coverage views measure."
    )

view = apply_filters(deals, picked_categories, picked_kinds, min_discount, price_range, search)

if view.empty:
    st.warning("No products match these filters.", icon=":material/filter_alt_off:")
    st.stop()

# --- Headline numbers --------------------------------------------------------

live = view[view["has_discount_info"]]
coverage_pct = len(live) / len(view) * 100
brands_total = view["brand"].nunique()
brands_with_discount = live["brand"].nunique()

with st.container(horizontal=True):
    st.metric("Products on the page", f"{len(view):,}", border=True)
    st.metric(
        "Discounted deals",
        f"{len(live):,}",
        f"{coverage_pct:.0f}% of the page",
        delta_color="off",
        border=True,
    )
    st.metric(
        "Median discount",
        f"{live['discount_pct'].median():.0f}%" if not live.empty else "—",
        f"best {live['discount_pct'].max():.0f}%" if not live.empty else None,
        delta_color="off",
        border=True,
    )
    st.metric(
        "Total savings on offer",
        f"${live['savings_abs'].sum():,.0f}" if not live.empty else "—",
        border=True,
    )
    st.metric(
        "Brands represented",
        f"{brands_total:,}",
        f"{brands_with_discount:,} publish a discount",
        delta_color="off",
        border=True,
    )

# --- The read ----------------------------------------------------------------

st.header("What the data says", icon=":material/lightbulb:")
st.caption("Recomputed against the current filters.")

findings = headline_findings(view)
if not findings:
    st.caption("Not enough matching data to draw conclusions from.")
else:
    for row_start in range(0, len(findings), 2):
        with st.container(horizontal=True):
            for finding in findings[row_start : row_start + 2]:
                with st.container(border=True):
                    st.markdown(finding)

gaps = data_gaps(view)
if gaps:
    with st.expander("What this data cannot tell you", icon=":material/help:"):
        for gap in gaps:
            st.markdown(f"- {gap}")

# --- Deals of the day --------------------------------------------------------

st.header("Today's picks", icon=":material/bolt:")
st.caption(
    "Discounted, still available, deepest discount first — with expiring "
    "lightning deals promoted to the front."
)

picks = deals_of_the_day(view, limit=6)
if picks.empty:
    st.caption("No discounted, available deals match these filters.")
else:
    for row_start in range(0, len(picks), 3):
        chunk = picks.iloc[row_start : row_start + 3]
        columns = st.columns(3, border=True)
        for column, (_, deal) in zip(columns, chunk.iterrows()):
            with column:
                st.image(deal["image_url"], width="stretch")
                st.markdown(f"**{deal['title'][:72]}**")
                st.caption(f"{deal['brand']} · {deal['category_label']}")

                badges = [f":blue-badge[{deal['discount_pct']:.0f}% off]"]
                if deal["deal_kind"] == "Lightning deal":
                    badges.append(":orange-badge[:material/bolt: Lightning]")
                if bool(deal["ends_soon"]):
                    badges.append(
                        f":red-badge[ends in {deal['hours_remaining']:.0f}h]"
                    )
                st.markdown(" ".join(badges))

                st.metric(
                    "Deal price",
                    f"${deal['deal_price']:,.2f}",
                    f"save ${deal['savings_abs']:,.2f}"
                    if pd.notna(deal["savings_abs"])
                    else None,
                    delta_color="inverse",
                    label_visibility="collapsed",
                )
                st.link_button(
                    "View on Amazon", deal["product_url"], icon=":material/open_in_new:"
                )

# --- Mix and per-category winners -------------------------------------------

st.header("Where the deals are", icon=":material/donut_large:")

mix_column, winners_column = st.columns([2, 3])

with mix_column:
    with st.container(border=True):
        st.subheader("Deal mix by category")
        distribution = category_distribution(view)
        if distribution.empty:
            st.caption("No discounted deals to chart.")
        else:
            st.altair_chart(category_donut(distribution))
            st.dataframe(
                distribution,
                hide_index=True,
                column_config={
                    "category": st.column_config.TextColumn("Category"),
                    "deals": st.column_config.NumberColumn("Deals"),
                    "share": st.column_config.NumberColumn("Share", format="percent"),
                },
            )

with winners_column:
    with st.container(border=True):
        st.subheader("Best in price per category")
        ranking = st.segmented_control(
            "Rank by",
            list(RANKINGS),
            default="Biggest % off",
            label_visibility="collapsed",
        ) or "Biggest % off"
        column, _ = RANKINGS[ranking]
        winners = best_per_category(view, ranking)

        if winners.empty:
            st.caption("No priced products match these filters.")
        else:
            st.altair_chart(best_price_bars(winners, column, ranking))
            st.dataframe(
                winners[
                    [
                        "category_label",
                        "title",
                        "brand",
                        "deal_price",
                        "list_price",
                        "discount_pct",
                        "savings_abs",
                        "product_url",
                    ]
                ],
                hide_index=True,
                column_config={
                    "category_label": st.column_config.TextColumn("Category"),
                    "title": st.column_config.TextColumn("Product", width="medium"),
                    "brand": st.column_config.TextColumn("Brand"),
                    "deal_price": st.column_config.NumberColumn("Deal", format="$%.2f"),
                    "list_price": st.column_config.NumberColumn("List", format="$%.2f"),
                    "discount_pct": st.column_config.ProgressColumn(
                        "Discount", min_value=0, max_value=100, format="%.0f%%"
                    ),
                    "savings_abs": st.column_config.NumberColumn("Saved", format="$%.2f"),
                    "product_url": st.column_config.LinkColumn("Link", display_text="Open"),
                },
            )

# --- What the missing prices tell us -----------------------------------------

st.header("Who actually publishes a discount", icon=":material/price_check:")
st.caption(
    f"{int((~view['has_discount_info']).sum())} of {len(view)} products are surfaced on "
    "the deals page with no price or badge at all. They are kept here: they still "
    "name a brand and a category, and they show where the page advertises a deal "
    "without quantifying one."
)

coverage_column, brand_column = st.columns([3, 2])

with coverage_column:
    with st.container(border=True):
        st.subheader("Discount info by category")
        st.altair_chart(coverage_bars(discount_info_coverage(view)))

with brand_column:
    with st.container(border=True):
        st.subheader("Brand footprint")
        st.dataframe(
            brand_coverage(view),
            hide_index=True,
            column_config={
                "brand": st.column_config.TextColumn("Brand"),
                "products": st.column_config.NumberColumn("Products"),
                "coverage": st.column_config.ProgressColumn(
                    "Discount info", min_value=0, max_value=1, format="percent"
                ),
                "avg_discount": st.column_config.NumberColumn("Avg off", format="%.0f%%"),
                "best_discount": st.column_config.NumberColumn("Best off", format="%.0f%%"),
                "categories": st.column_config.NumberColumn("Categories"),
                "with_discount": None,
                "no_discount": None,
            },
        )
        st.caption(
            "A brand at 0% is on the deals page today without a single published "
            "discount."
        )

# --- Raw feed ----------------------------------------------------------------

with st.expander("Browse the full feed", icon=":material/table_rows:"):
    st.dataframe(
        view[
            [
                "title",
                "brand",
                "category_label",
                "deal_kind",
                "deal_price",
                "list_price",
                "discount_pct",
                "hours_remaining",
                "product_url",
            ]
        ],
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn("Product", width="large"),
            "brand": st.column_config.TextColumn("Brand"),
            "category_label": st.column_config.TextColumn("Category"),
            "deal_kind": st.column_config.TextColumn("Type"),
            "deal_price": st.column_config.NumberColumn("Deal", format="$%.2f"),
            "list_price": st.column_config.NumberColumn("List", format="$%.2f"),
            "discount_pct": st.column_config.NumberColumn("Discount", format="%.0f%%"),
            "hours_remaining": st.column_config.NumberColumn("Hours left", format="%.1f"),
            "product_url": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )
    st.download_button(
        "Download this view",
        view.to_csv(index=False),
        file_name="amazon_deals_filtered.csv",
        mime="text/csv",
        icon=":material/download:",
    )
