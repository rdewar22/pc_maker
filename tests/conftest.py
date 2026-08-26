"""Test configuration: neutralize all live pricing keys before app modules load.

Without this, app.main's module-level pricers pick up real keys from .env and
tests would make live API calls (slow, flaky, and burns free-tier credits).

We set keys to empty strings rather than popping them: load_dotenv() defaults
to override=False, so it will not clobber an already-set (empty) value when
app modules are imported during test collection.
"""

import os

for var in ["BESTBUY_API_KEY", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
            "SEARCHAPI_API_KEY"]:
    os.environ[var] = ""
