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


def export_telemetry(client: InfluxDBClient, hours: int) -> pd.DataFrame:
    print("  Exporting telemetry...")
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_telemetry")
  |> pivot(rowKey: ["_time","device_id","device_type","location","anomaly"],
           columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
    df = query(client, flux)
    if df.empty:
        return df

    # Clean and rename for Power BI readability
    rename = {
        "device_id":    "Device ID",
        "device_type":  "Device Type",
        "location":     "Location",
        "anomaly":      "Is Anomaly",
        "cpu_percent":  "CPU %",
        "ram_percent":  "RAM %",
        "temperature_c":"Temperature (°C)",
        "signal_dbm":   "Signal (dBm)",
        "uptime_s":     "Uptime (s)",
        "publish_count":"Publish Count",
        "timestamp":    "Timestamp",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # Derive extra columns Power BI can use for slicing
    if "Timestamp" in df.columns:
        df["Hour"]    = df["Timestamp"].dt.hour
        df["Date"]    = df["Timestamp"].dt.date
        df["Weekday"] = df["Timestamp"].dt.day_name()

    if "Signal (dBm)" in df.columns:
        df["Signal Quality"] = df["Signal (dBm)"].apply(
            lambda x: "Excellent" if x >= -60
            else ("Good" if x >= -70
            else ("Fair" if x >= -80
            else "Poor"))
        )

    if "Temperature (°C)" in df.columns:
        df["Temp Status"] = df["Temperature (°C)"].apply(
            lambda x: "Critical" if x >= 80
            else ("Warning" if x >= 70
            else "Normal")
        )

    if "CPU %" in df.columns:
        df["CPU Status"] = df["CPU %"].apply(
            lambda x: "Critical" if x >= 85
            else ("High" if x >= 70
            else "Normal")
        )

    print(f"    {len(df):,} rows, {df['Device ID'].nunique() if 'Device ID' in df.columns else '?'} devices")
    return df


def export_status(client: InfluxDBClient, hours: int) -> pd.DataFrame:
    print("  Exporting device status...")
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_status")
  |> pivot(rowKey: ["_time","device_id","device_type","location"],
           columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
    df = query(client, flux)
    if df.empty:
        return df

    rename = {
        "device_id":       "Device ID",
        "device_type":     "Device Type",
        "location":        "Location",
        "uptime_s":        "Uptime (s)",
        "publish_count":   "Messages Published",
        "error_count":     "Error Count",
        "queue_depth":     "Queue Depth",
        "inflight_count":  "Inflight Messages",
        "is_connected":    "Is Connected",
        "reconnect_count": "Reconnect Count",
        "timestamp":       "Timestamp",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "Uptime (s)" in df.columns:
        df["Uptime (hours)"] = (df["Uptime (s)"] / 3600).round(2)

    if "Is Connected" in df.columns:
        df["Connection Status"] = df["Is Connected"].apply(
            lambda x: "Online" if x == 1 else "Offline"
        )

    print(f"    {len(df):,} rows")
    return df


def export_events(client: InfluxDBClient, hours: int) -> pd.DataFrame:
    print("  Exporting device events...")
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_events")
  |> pivot(rowKey: ["_time","device_id","device_type","location","event"],
           columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
    df = query(client, flux)
    if df.empty:
        return df

    rename = {
        "device_id":        "Device ID",
        "device_type":      "Device Type",
        "location":         "Location",
        "event":            "Event Type",
        "firmware_version": "Firmware Version",
        "event_count":      "Event Count",
        "timestamp":        "Timestamp",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    print(f"    {len(df):,} rows")
    return df




def main():
    pass


if __name__ == "__main__":
    main()
