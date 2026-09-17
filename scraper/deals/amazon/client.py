import logging
import random
import time
from dataclasses import field, dataclass
from typing import Any

import requests

from constants import DEFAULT_HEADERS
from scraper.deals.amazon.scraper_config import ScrapeConfig
from utils.utils import extract_widget_state


logger = logging.getLogger(__name__)


@dataclass
class DealsClient:
    """HTTP client for the Amazon deals page."""

    config: ScrapeConfig = field(default_factory=ScrapeConfig)
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.cookies.set("i18n-prefs", self.config.currency, domain=".amazon.com")
        self.session.cookies.set("lc-main", "en_US", domain=".amazon.com")
        if self.config.proxies:
            self.session.proxies.update(self.config.proxies)

    def sleep(self) -> None:
        time.sleep(random.uniform(self.config.min_delay, self.config.max_delay))

    def fetch_widget(self, url: str) -> dict[str, Any] | None:
        """GET a deals' URL and return its parsed widget state (None on failure)."""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.config.timeout)
                if resp.status_code == 200:
                    state = extract_widget_state(resp.text)
                    if state is not None:
                        return state
                    logger.warning("No deal payload (bot check?) for %s", url)
                else:
                    logger.warning("HTTP %s for %s", resp.status_code, url)
            except requests.RequestException as exc:
                logger.warning("Request error (%s/%s): %s", attempt, self.config.max_retries, exc)
            time.sleep(2 ** attempt + random.random())   # exponential backoff
        return None

    @staticmethod
    def discover_filters( state: dict[str, Any]) -> list[tuple[str, str]]:
        """Return (kind, value) filter targets found on the landing page.

        Each one re-runs the deals' grid over a different slice of the
        catalog, which is how we page past the 30 deals in the initial payload.
        """
        targets: list[tuple[str, str]] = []
        for bubble in state.get("symphonyConfig", {}).get("bubbles", []):
            if bubble.get("id"):
                targets.append(("bubble", bubble["id"]))
        for refinement in state.get("productSearchResponse", {}).get("refinements", []):
            if refinement.get("id") == "departments":
                for option in refinement.get("options", []):
                    targets.append(("departments", option["value"]))
        return targets
