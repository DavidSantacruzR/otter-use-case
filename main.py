import logging

from normalization.normalization_utils import normalize_deals
from scraper.deals.amazon.scrapper import scrape_deals

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    payload = scrape_deals(target=300)
    frame = normalize_deals(payload)
    frame.to_csv("amazon_deals.csv", index=False)
    logger.info(f"\n{len(frame)} deals -> amazon_deals.csv")
    logger.info(frame[["asin", "title", "deal_price", "discount_pct", "rating"]].head(10).to_string())
