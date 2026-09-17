import logging
import random

from datetime import datetime, timezone

from typing import Any

from constants import DEALS_URL

from scraper.deals.amazon.client import DealsClient
from scraper.deals.amazon.scraper_config import ScrapeConfig

from utils.utils import brand_lookup, refinement_url, bubble_url

logger = logging.getLogger(__name__)


def scrape_deals(
    target: int = 300,
    config: ScrapeConfig | None = None,
    client: DealsClient | None = None,
) -> dict[str, Any]:
    """Collect at least `target` unique Amazon deals.

    Returns {"deals": [raw deal dicts], "brands": {id: name},
             "scraped_at": iso8601, "currency": str, "requests": int}
    """
    config = config or ScrapeConfig(target_deals=target)
    config.target_deals = target
    client = client or DealsClient(config=config)

    landing = client.fetch_widget(DEALS_URL)
    if landing is None:
        raise RuntimeError(
            "Could not read the Amazon deals payload. This is usually a bot check: "
            "retry in a minute, restart the Colab runtime for a fresh IP, or set "
            "ScrapeConfig(proxies=...)."
        )

    currency = landing.get("currencyIsoCode", config.currency)
    brands = brand_lookup(landing)
    deals: dict[str, dict[str, Any]] = {}
    requests_made = 1

    def absorb(state: dict[str, Any], source: str) -> int:
        new = 0
        for product in state.get("productSearchResponse", {}).get("products", []):
            asin = product.get("asin")
            if not asin:
                continue
            if asin not in deals:
                product["_source_filter"] = source
                deals[asin] = product
                new += 1
        brands.update(brand_lookup(state))
        return new

    absorb(landing, "landing")
    filters = client.discover_filters(landing)
    random.shuffle(filters)
    logger.info("Discovered %d filter slices; collecting up to %d deals…", len(filters), target)

    for kind, value in filters:
        if len(deals) >= target:
            break
        client.sleep()
        url = bubble_url(value) if kind == "bubble" else refinement_url(kind, value)
        state = client.fetch_widget(url)
        requests_made += 1
        if state is None:
            continue
        new = absorb(state, f"{kind}:{value}")
        logger.info("  %-28s +%-3d unique total=%d", f"{kind}:{value}"[:28], new, len(deals))

    if len(deals) < target:
        logger.warning("Collected %d deals (target %d) — Amazon's catalog ran out of "
                    "distinct slices. Lower the target or add filter kinds.",
                    len(deals), target)

    collected = list(deals.values())
    for optional in ("price", "customerReviews", "dealDetails"):
        coverage = sum(optional in d for d in collected) / max(len(collected), 1)
        if coverage < 0.5:
            logger.warning("Heads-up: only %.0f%% of deals carry `%s` in this run "
                        "(Amazon ships that block intermittently).", coverage * 100, optional)

    return {
        "deals": collected,
        "brands": brands,
        "currency": currency,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "requests": requests_made,
    }
