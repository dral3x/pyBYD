"""Internal constants shared across the library."""

BASE_URL = "https://dilinkappoversea-eu.byd.auto"
USER_AGENT = "okhttp/4.12.0"
SESSION_EXPIRED_CODES: frozenset[str] = frozenset({"1002", "1005", "1010"})
