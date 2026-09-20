import os
from pathlib import Path


Path("data").mkdir(parents=True, exist_ok=True)

# Test-only bootstrap so session module can import without a Neon connection.
os.environ["STOCK_SAGE_IGNORE_DOTENV"] = "1"
os.environ["STOCK_SAGE_ALLOW_TEST_SQLITE"] = "1"
os.environ["STOCK_SAGE_AUTH_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_default_for_imports.db"
