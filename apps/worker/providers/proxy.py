from urllib.parse import urlparse

from app.core.config import get_settings


def outbound_proxy_kwargs(target_url: str | None = None) -> dict[str, object]:
    settings = get_settings()
    proxy_url = settings.outbound_proxy_url
    if not proxy_url:
        return {}
    if target_url and _matches_no_proxy(target_url=target_url, no_proxy=settings.no_proxy):
        return {}
    return {"proxy": proxy_url, "trust_env": False}


def _matches_no_proxy(*, target_url: str, no_proxy: str) -> bool:
    host = urlparse(target_url).hostname
    if not host:
        return False

    normalized_host = host.lower().strip("[]")
    for raw_token in no_proxy.split(","):
        token = raw_token.strip().lower().strip("[]")
        if not token:
            continue
        if token == "*":
            return True
        if token.startswith(".") and normalized_host.endswith(token):
            return True
        if normalized_host == token or normalized_host.endswith(f".{token}"):
            return True
    return False
