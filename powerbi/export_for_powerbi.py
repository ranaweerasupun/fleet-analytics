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

def query(client: InfluxDBClient, flux: str) -> pd.DataFrame:
    tables = client.query_api().query_data_frame(flux, org=INFLUX_ORG)
    if isinstance(tables, list):
        if not tables:
            return pd.DataFrame()
        df = pd.concat(tables, ignore_index=True)
    else:
        df = tables

    drop = [c for c in df.columns if c.startswith("result") or c == "table"]
    df = df.drop(columns=drop, errors="ignore")
    if "_time" in df.columns:
        df = df.rename(columns={"_time": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    return df

def main():
    pass


if __name__ == "__main__":
    main()
