from dataclasses import dataclass


@dataclass
class ScrapeConfig:
    """Default configuration for a scraping collection run."""

    target_deals: int = 300
    min_delay: float = 0.8
    max_delay: float = 1.8
    timeout: int = 30
    max_retries: int = 3
    currency: str = "USD"
    proxies: dict[str, str] | None = None
