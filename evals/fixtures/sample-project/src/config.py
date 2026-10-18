"""Settings, read from environment variables with these defaults."""

import os

MAX_RETRIES = int(os.environ.get("SENTINEL_MAX_RETRIES", "3"))
REPORT_FORMAT = os.environ.get("SENTINEL_REPORT_FORMAT", "markdown")
