"""
export_for_powerbi.py
---------------------
Pulls fleet telemetry from InfluxDB and exports four clean CSV files
ready for direct import into Power BI Desktop.
"""

import argparse
import os
from datetime import datetime, timezone

import pandas as pd
from influxdb_client import InfluxDBClient

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
except EnvironmentError:
    # Allow --sample flag to work without credentials
    INFLUX_URL = "http://localhost:8086"
    INFLUX_TOKEN = ""
    INFLUX_ORG = "fleet-org"
    INFLUX_BUCKET = "fleet-telemetry"

