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


def build_summary(telemetry: pd.DataFrame, status: pd.DataFrame) -> pd.DataFrame:
    """Pre-aggregate KPIs for Power BI KPI cards — one row per device."""
    print("  Building fleet summary...")
    if telemetry.empty:
        return pd.DataFrame()

    agg = {}

    if "Device ID" in telemetry.columns:
        group = telemetry.groupby("Device ID")

        if "CPU %" in telemetry.columns:
            agg["Avg CPU %"]  = group["CPU %"].mean().round(1)
            agg["Max CPU %"]  = group["CPU %"].max().round(1)
            agg["P95 CPU %"]  = group["CPU %"].quantile(0.95).round(1)

        if "RAM %" in telemetry.columns:
            agg["Avg RAM %"]  = group["RAM %"].mean().round(1)

        if "Temperature (°C)" in telemetry.columns:
            agg["Avg Temp (°C)"] = group["Temperature (°C)"].mean().round(1)
            agg["Max Temp (°C)"] = group["Temperature (°C)"].max().round(1)

        if "Signal (dBm)" in telemetry.columns:
            agg["Avg Signal (dBm)"] = group["Signal (dBm)"].mean().round(0)

        if "Is Anomaly" in telemetry.columns:
            agg["Anomaly Count"] = group["Is Anomaly"].apply(
                lambda x: (x == "True").sum()
            )

        summary = pd.DataFrame(agg).reset_index()

        # Join device type and location from latest reading
        if "Device Type" in telemetry.columns and "Location" in telemetry.columns:
            latest = (
                telemetry.sort_values("Timestamp")
                .groupby("Device ID")[["Device Type", "Location"]]
                .last()
                .reset_index()
            )
            summary = summary.merge(latest, on="Device ID", how="left")

        # Join reconnect count from status
        if not status.empty and "Device ID" in status.columns and "Reconnect Count" in status.columns:
            reconnects = (
                status.groupby("Device ID")["Reconnect Count"]
                .max()
                .reset_index()
            )
            summary = summary.merge(reconnects, on="Device ID", how="left")

        # Health score: simple composite (lower is better problems)
        if "Max CPU %" in summary.columns and "Max Temp (°C)" in summary.columns:
            summary["Health Score"] = (
                100
                - (summary["Max CPU %"] * 0.3)
                - ((summary["Max Temp (°C)"] - 40) * 0.5)
                - (summary.get("Anomaly Count", 0) * 2)
            ).clip(0, 100).round(1)

        print(f"    {len(summary)} device summaries")
        return summary

    return pd.DataFrame()




def main():
    pass


if __name__ == "__main__":
    main()
