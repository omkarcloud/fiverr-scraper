"""Configuration for the Fiverr Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT           port the API listens on (default 8000)
    FIVERR_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                   (default: none, requests go out from your own connection).
                   Your own connection is enough to start. Fiverr can block one
                   IP for a few hours after about 150 calls: for volume, set a
                   proxy.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

FIVERR_PROXY = os.environ.get("FIVERR_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
FIVERR_BLOCK_HOLD_S = 600
FIVERR_EXIT = FIVERR_PROXY      # the exit every session leaves through: your proxy, or direct
FIVERR_FALLBACK_EXITS = ()
FIVERR_HOLD_AFTER_REFUSALS = 3
FIVERR_LISTING_EXIT = FIVERR_PROXY      # search and category pages: your proxy too, or direct
FIVERR_LISTING_FALLBACK_EXITS = ()
FIVERR_RETURN_FULL_NAME = True
MAX_RETRIES = 3
RETRY_BACKOFF = 2
def gateway_exit(exit=None):
    return None

