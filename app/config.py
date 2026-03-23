from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class ServerSettings:
    host: str
    port: int


@dataclass
class CrawlerSettings:
    worker_count: int
    request_timeout: float
    crawl_delay: float
    max_connections: int
    default_max_pages: int
    default_max_depth: int
    max_pages_limit: int


@dataclass
class RetrySettings:
    max_retries: int
    backoff_base: float
    retry_after_default: float


@dataclass
class CacheSettings:
    ttl_seconds: int


@dataclass
class Settings:
    server: ServerSettings
    crawler: CrawlerSettings
    retry: RetrySettings
    cache: CacheSettings


def _load() -> Settings:
    with open(_CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    return Settings(
        server=ServerSettings(**data["server"]),
        crawler=CrawlerSettings(**data["crawler"]),
        retry=RetrySettings(**data["retry"]),
        cache=CacheSettings(**data["cache"]),
    )


settings: Settings = _load()
