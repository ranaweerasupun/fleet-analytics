"""
export_for_powerbi.py
---------------------
Pulls fleet telemetry from InfluxDB and exports four clean CSV files
ready for direct import into Power BI Desktop.

Output files (written to ./data/):
  telemetry.csv   — per-device sensor readings (CPU, RAM, temp, signal)
  status.csv      — per-device operational metrics (queue, reconnects)
  events.csv      — discrete device events (boot, alerts)
  summary.csv     — pre-aggregated fleet KPIs for KPI cards in Power BI

Run:
  python export_for_powerbi.py
  python export_for_powerbi.py --hours 6 --output ./data
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


def generate_sample_data(output_dir: str):
    """
    Generate realistic sample CSV files for use when InfluxDB is not running.
    This is what you commit to GitHub so clients can download and open
    the Power BI file without needing a live data source.
    """
    import numpy as np
    import random

    print("\n  Generating sample data (no InfluxDB needed)...")
    random.seed(42)
    np.random.seed(42)

    device_types = {
        "sensor":     {"cpu": 8,  "ram": 35, "temp": 42, "signal": -62},
        "gateway":    {"cpu": 28, "ram": 55, "temp": 52, "signal": -55},
        "camera":     {"cpu": 65, "ram": 70, "temp": 61, "signal": -58},
        "controller": {"cpu": 18, "ram": 45, "temp": 48, "signal": -60},
    }
    locations = ["warehouse_a","warehouse_b","factory_floor_1",
                 "factory_floor_2","office_block","server_room",
                 "loading_bay","outdoor_yard"]

    devices = []
    for i in range(1, 16):
        dtype = random.choices(
            list(device_types.keys()), weights=[45,20,20,15]
        )[0]
        devices.append({
            "id": f"device_{i:03d}",
            "type": dtype,
            "location": random.choice(locations),
            "profile": device_types[dtype],
        })

    # Telemetry — 6 hours, one reading per device per interval
    rows = []
    now = datetime.now()
    for minutes_ago in range(360, 0, -1):
        ts = pd.Timestamp(now) - pd.Timedelta(minutes=minutes_ago)
        for dev in devices:
            p = dev["profile"]
            is_anomaly = random.random() < 0.02
            cpu = min(99, max(1, np.random.normal(p["cpu"], 5) + (30 if is_anomaly else 0)))
            temp = min(95, max(20, np.random.normal(p["temp"], 3) + (20 if is_anomaly else 0)))
            signal = int(p["signal"] + random.randint(-8, 8))
            rows.append({
                "Timestamp":       ts,
                "Device ID":       dev["id"],
                "Device Type":     dev["type"],
                "Location":        dev["location"],
                "CPU %":           round(cpu, 1),
                "RAM %":           round(max(5, min(99, np.random.normal(p["ram"], 4))), 1),
                "Temperature (°C)":round(temp, 2),
                "Signal (dBm)":    signal,
                "Uptime (s)":      minutes_ago * 60,
                "Is Anomaly":      str(is_anomaly),
                "Hour":            ts.hour,
                "Date":            ts.date(),
                "Weekday":         ts.day_name(),
                "Signal Quality":  "Excellent" if signal>=-60 else ("Good" if signal>=-70 else ("Fair" if signal>=-80 else "Poor")),
                "Temp Status":     "Critical" if temp>=80 else ("Warning" if temp>=70 else "Normal"),
                "CPU Status":      "Critical" if cpu>=85 else ("High" if cpu>=70 else "Normal"),
            })

    telemetry_df = pd.DataFrame(rows)
    telemetry_df.to_csv(os.path.join(output_dir, "telemetry.csv"), index=False)
    print(f"    telemetry.csv — {len(telemetry_df):,} rows")

    # Status
    status_rows = []
    for dev in devices:
        status_rows.append({
            "Device ID":         dev["id"],
            "Device Type":       dev["type"],
            "Location":          dev["location"],
            "Uptime (s)":        random.randint(3600, 86400),
            "Uptime (hours)":    round(random.uniform(1, 24), 2),
            "Messages Published":random.randint(200, 2000),
            "Error Count":       random.randint(0, 15),
            "Queue Depth":       random.randint(0, 50),
            "Reconnect Count":   random.randint(0, 12),
            "Connection Status": random.choice(["Online","Online","Online","Offline"]),
        })
    status_df = pd.DataFrame(status_rows)
    status_df.to_csv(os.path.join(output_dir, "status.csv"), index=False)
    print(f"    status.csv — {len(status_df)} rows")

    # Events
    event_rows = []
    for dev in devices:
        event_rows.append({
            "Device ID":       dev["id"],
            "Device Type":     dev["type"],
            "Location":        dev["location"],
            "Event Type":      "boot",
            "Firmware Version":"1.4.2",
            "Timestamp":       pd.Timestamp(now) - pd.Timedelta(hours=6),
        })
        for _ in range(random.randint(0, 3)):
            event_rows.append({
                "Device ID":       dev["id"],
                "Device Type":     dev["type"],
                "Location":        dev["location"],
                "Event Type":      random.choice(["reconnect","alert","watchdog_reset"]),
                "Firmware Version":"1.4.2",
                "Timestamp":       pd.Timestamp(now) - pd.Timedelta(minutes=random.randint(0,359)),
            })
    events_df = pd.DataFrame(event_rows)
    events_df.to_csv(os.path.join(output_dir, "events.csv"), index=False)
    print(f"    events.csv — {len(events_df)} rows")

    print(f"\n  Sample data written to {output_dir}/")
    print("  Use these CSVs to build the Power BI report without a live stack.\n")


def main():
    parser = argparse.ArgumentParser(description="Export InfluxDB fleet data to Power BI CSVs")
    parser.add_argument("--hours",  type=int, default=6)
    parser.add_argument("--influx-url", default=INFLUX_URL)
    parser.add_argument("--output", default="./data")
    parser.add_argument("--sample", action="store_true",
                        help="Generate sample data without InfluxDB")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if args.sample:
        generate_sample_data(args.output)
        return

    print(f"\nConnecting to InfluxDB at {args.influx_url}...")
    client = InfluxDBClient(url=args.influx_url, token=INFLUX_TOKEN, org=INFLUX_ORG)

    print(f"Exporting last {args.hours}h of data...\n")
    telemetry = export_telemetry(client, args.hours)
    status    = export_status(client, args.hours)
    events    = export_events(client, args.hours)
    summary   = build_summary(telemetry, status)

    if telemetry.empty:
        print("\nNo data in InfluxDB. Run with --sample to generate sample CSVs instead.")
        client.close()
        return

    telemetry.to_csv(os.path.join(args.output, "telemetry.csv"), index=False)
    status.to_csv(   os.path.join(args.output, "status.csv"),    index=False)
    events.to_csv(   os.path.join(args.output, "events.csv"),    index=False)
    summary.to_csv(  os.path.join(args.output, "summary.csv"),   index=False)

    print(f"\nAll CSVs written to {args.output}/")
    print("Open Power BI Desktop → Get Data → Text/CSV → import each file.")
    client.close()



if __name__ == "__main__":
    main()
