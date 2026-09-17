# otter-use-case
otter use case example

## Deals dashboard

A Streamlit dashboard over `amazon_deals.csv`: deals of the day, the best-priced
product in each category, the category mix as a donut, and — from the rows the
scrape returns without a price — which brands and categories show up on the deals
page without publishing a discount at all.

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Refresh the data with `python main.py` (re-scrapes and rewrites `amazon_deals.csv`).

Layout:

- `streamlit_app.py` — the page.
- `dashboard/data.py` — loading, category labels, the deal/listing split, rankings.
- `dashboard/charts.py` — the Altair charts.
- `.streamlit/config.toml` — theme and the chart palette (light and dark).

To deploy on Streamlit Community Cloud, point it at this repo with
`streamlit_app.py` as the entry point; `requirements.txt` covers the dependencies.
