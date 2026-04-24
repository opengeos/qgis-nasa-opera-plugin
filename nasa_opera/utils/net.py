"""Shared networking helpers for the NASA OPERA plugin."""


def require_https(url: str) -> None:
    """Reject any URL that does not use the https scheme.

    Args:
        url: URL string to validate.

    Raises:
        ValueError: If the URL is not https.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"Refusing non-https URL: {url!r}")
