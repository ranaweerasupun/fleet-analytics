"""
config.py
---------
Central configuration — reads from environment variables or .env file.
All scripts import from here instead of hardcoding credentials.

Usage:
    from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
"""

import os
from pathlib import Path

# Load .env file if it exists (development convenience)
# In production (Pi, cloud) set environment variables directly
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# InfluxDB
INFLUX_URL    = os.environ.get("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.environ.get("INFLUX_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUX_ORG",    "fleet-org")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "fleet-telemetry")

# Validate on import — fail loud if token is missing
if not INFLUX_TOKEN:
    raise EnvironmentError(
        "INFLUX_TOKEN is not set.\n"
        "Copy .env.example to .env and fill in your values.\n"
        "See README.md → Configuration."
    )
