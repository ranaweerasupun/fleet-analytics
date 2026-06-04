"""
fleet_analysis.py
-----------------
Pulls fleet telemetry from InfluxDB and produces a data analyst-grade
insight report as both terminal output and PNG charts.

This demonstrates the analytics layer on top of the pipeline:
  - Fleet health summary
  - Per-device CPU / temperature / signal trends
  - Anomaly detection results
  - Offline queue behaviour analysis
  - Location-based performance comparison

Run after at least 5 minutes of fleet simulation:
  python fleet_analysis.py
  python fleet_analysis.py --hours 2 --output ./report
"""

import argparse
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from influxdb_client import InfluxDBClient

INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "fleet-super-secret-token-001"
INFLUX_ORG    = "fleet-org"
INFLUX_BUCKET = "fleet-telemetry"


# ── InfluxDB query helper ─────────────────────────────────────────────────────

def query_to_df(client: InfluxDBClient, flux: str) -> pd.DataFrame:
    """Run a Flux query and return a clean Pandas DataFrame."""
    tables = client.query_api().query_data_frame(flux, org=INFLUX_ORG)
    if isinstance(tables, list):
        if not tables:
            return pd.DataFrame()
        df = pd.concat(tables, ignore_index=True)
    else:
        df = tables

    # Drop InfluxDB internal columns
    drop_cols = [c for c in df.columns if c.startswith("_") and c not in ("_time", "_value", "_field", "_measurement")]
    df = df.drop(columns=drop_cols, errors="ignore")
    if "_time" in df.columns:
        df["_time"] = pd.to_datetime(df["_time"])
    return df


# ── Analysis functions ────────────────────────────────────────────────────────

def load_telemetry(client: InfluxDBClient, hours: int) -> pd.DataFrame:
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_telemetry")
  |> pivot(rowKey: ["_time", "device_id", "device_type", "location", "anomaly"],
           columnKey: ["_field"], valueColumn: "_value")
"""
    df = query_to_df(client, flux)
    return df


def load_status(client: InfluxDBClient, hours: int) -> pd.DataFrame:
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_status")
  |> pivot(rowKey: ["_time", "device_id", "device_type", "location"],
           columnKey: ["_field"], valueColumn: "_value")
"""
    return query_to_df(client, flux)


def print_fleet_summary(telemetry: pd.DataFrame, status: pd.DataFrame):
    print("\n" + "═" * 60)
    print("  FLEET HEALTH SUMMARY")
    print("═" * 60)

    device_count = telemetry["device_id"].nunique() if "device_id" in telemetry.columns else 0
    print(f"  Active devices:        {device_count}")

    if "cpu_percent" in telemetry.columns:
        print(f"  Avg CPU:               {telemetry['cpu_percent'].mean():.1f}%")
        print(f"  Max CPU (any device):  {telemetry['cpu_percent'].max():.1f}%")

    if "temperature_c" in telemetry.columns:
        print(f"  Avg temperature:       {telemetry['temperature_c'].mean():.1f}°C")
        high_temp = (telemetry["temperature_c"] > 75).sum()
        print(f"  High-temp readings:    {high_temp}")

    if "signal_dbm" in telemetry.columns:
        avg_signal = telemetry["signal_dbm"].mean()
        poor_signal = (telemetry["signal_dbm"] < -75).sum()
        print(f"  Avg signal strength:   {avg_signal:.0f} dBm")
        print(f"  Poor signal readings:  {poor_signal}")

    if "anomaly" in telemetry.columns:
        anomalies = (telemetry["anomaly"] == "True").sum()
        print(f"  Anomaly events:        {anomalies}")

    if not status.empty and "queue_depth" in status.columns:
        max_queue = status["queue_depth"].max()
        print(f"  Max offline queue:     {max_queue} messages")

    if not status.empty and "reconnect_count" in status.columns:
        total_reconnects = status.groupby("device_id")["reconnect_count"].max().sum()
        print(f"  Total reconnections:   {int(total_reconnects)}")

    print("═" * 60 + "\n")


def print_device_league_table(telemetry: pd.DataFrame):
    if telemetry.empty or "device_id" not in telemetry.columns:
        return

    print("  TOP 5 DEVICES BY CPU LOAD")
    print("  " + "-" * 44)
    if "cpu_percent" in telemetry.columns:
        top = (
            telemetry.groupby("device_id")["cpu_percent"]
            .mean()
            .sort_values(ascending=False)
            .head(5)
        )
        for device_id, cpu in top.items():
            bar = "█" * int(cpu / 5)
            print(f"  {device_id:<15} {cpu:5.1f}%  {bar}")

    print()
    print("  TOP 5 HOTTEST DEVICES")
    print("  " + "-" * 44)
    if "temperature_c" in telemetry.columns:
        top_temp = (
            telemetry.groupby("device_id")["temperature_c"]
            .mean()
            .sort_values(ascending=False)
            .head(5)
        )
        for device_id, temp in top_temp.items():
            bar = "█" * int(temp / 10)
            print(f"  {device_id:<15} {temp:5.1f}°C  {bar}")
    print()


def print_location_analysis(telemetry: pd.DataFrame):
    if telemetry.empty or "location" not in telemetry.columns:
        return

    print("  PERFORMANCE BY LOCATION")
    print("  " + "-" * 52)
    metrics = {}
    for col in ["cpu_percent", "temperature_c", "signal_dbm"]:
        if col in telemetry.columns:
            metrics[col] = telemetry.groupby("location")[col].mean()

    if metrics:
        loc_df = pd.DataFrame(metrics).round(1)
        for loc, row in loc_df.iterrows():
            parts = [f"{k.split('_')[0]}={v}" for k, v in row.items() if not pd.isna(v)]
            print(f"  {loc:<20} {',  '.join(parts)}")
    print()


# ── Chart generation ──────────────────────────────────────────────────────────

def make_charts(telemetry: pd.DataFrame, status: pd.DataFrame, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    if telemetry.empty:
        print("  No telemetry data available for charts yet.")
        return

    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle("Fleet IoT Analytics Report", fontsize=16, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

    # 1 — CPU distribution by device type
    ax1 = fig.add_subplot(gs[0, 0])
    if "device_type" in telemetry.columns and "cpu_percent" in telemetry.columns:
        groups = [
            telemetry[telemetry["device_type"] == t]["cpu_percent"].dropna().values
            for t in telemetry["device_type"].unique()
        ]
        labels = list(telemetry["device_type"].unique())
        ax1.boxplot(groups, labels=labels, patch_artist=True,
                    boxprops=dict(facecolor="#5DCAA5", alpha=0.7))
        ax1.set_title("CPU load by device type", fontsize=11)
        ax1.set_ylabel("CPU (%)")
        ax1.set_xlabel("Device type")

    # 2 — Temperature over time (sampled devices)
    ax2 = fig.add_subplot(gs[0, 1])
    if "_time" in telemetry.columns and "temperature_c" in telemetry.columns:
        sample_devices = telemetry["device_id"].unique()[:5]
        for dev in sample_devices:
            sub = telemetry[telemetry["device_id"] == dev].sort_values("_time")
            ax2.plot(sub["_time"], sub["temperature_c"], alpha=0.7, linewidth=1, label=dev)
        ax2.set_title("Temperature trends (sample devices)", fontsize=11)
        ax2.set_ylabel("Temperature (°C)")
        ax2.tick_params(axis="x", rotation=30)
        ax2.legend(fontsize=7, loc="upper right")

    # 3 — Signal strength distribution
    ax3 = fig.add_subplot(gs[1, 0])
    if "signal_dbm" in telemetry.columns:
        ax3.hist(telemetry["signal_dbm"], bins=20, color="#7F77DD", alpha=0.8, edgecolor="white")
        ax3.axvline(-75, color="red", linestyle="--", linewidth=1.5, label="Poor signal threshold")
        ax3.set_title("Signal strength distribution", fontsize=11)
        ax3.set_xlabel("Signal (dBm)")
        ax3.set_ylabel("Count")
        ax3.legend(fontsize=9)

    # 4 — Anomaly count by location
    ax4 = fig.add_subplot(gs[1, 1])
    if "anomaly" in telemetry.columns and "location" in telemetry.columns:
        anomaly_counts = (
            telemetry[telemetry["anomaly"] == "True"]
            .groupby("location")
            .size()
            .sort_values(ascending=True)
        )
        if not anomaly_counts.empty:
            bars = ax4.barh(anomaly_counts.index, anomaly_counts.values, color="#D85A30", alpha=0.8)
            ax4.set_title("Anomaly events by location", fontsize=11)
            ax4.set_xlabel("Anomaly count")
        else:
            ax4.text(0.5, 0.5, "No anomalies detected", ha="center", va="center",
                     transform=ax4.transAxes, fontsize=12, color="gray")
            ax4.set_title("Anomaly events by location", fontsize=11)

    # 5 — Offline queue depth over time
    ax5 = fig.add_subplot(gs[2, 0])
    if not status.empty and "_time" in status.columns and "queue_depth" in status.columns:
        queue_trend = status.groupby("_time")["queue_depth"].max().reset_index()
        ax5.fill_between(queue_trend["_time"], queue_trend["queue_depth"], alpha=0.4, color="#BA7517")
        ax5.plot(queue_trend["_time"], queue_trend["queue_depth"], color="#BA7517", linewidth=1.5)
        ax5.set_title("Max offline queue depth over time", fontsize=11)
        ax5.set_ylabel("Queue depth (messages)")
        ax5.tick_params(axis="x", rotation=30)

    # 6 — RAM usage heatmap by device type and location
    ax6 = fig.add_subplot(gs[2, 1])
    if "device_type" in telemetry.columns and "location" in telemetry.columns and "ram_percent" in telemetry.columns:
        pivot = telemetry.pivot_table(
            values="ram_percent", index="location", columns="device_type", aggfunc="mean"
        ).round(1)
        if not pivot.empty:
            im = ax6.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
            ax6.set_xticks(range(len(pivot.columns)))
            ax6.set_yticks(range(len(pivot.index)))
            ax6.set_xticklabels(pivot.columns, fontsize=8)
            ax6.set_yticklabels(pivot.index, fontsize=8)
            plt.colorbar(im, ax=ax6, label="RAM %")
            for i in range(len(pivot.index)):
                for j in range(len(pivot.columns)):
                    val = pivot.values[i, j]
                    if not pd.isna(val):
                        ax6.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color="black")
            ax6.set_title("Avg RAM usage (location × type)", fontsize=11)

    chart_path = os.path.join(output_dir, "fleet_analytics_report.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Charts saved → {chart_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fleet analytics report from InfluxDB")
    parser.add_argument("--hours", type=int, default=1, help="How many hours of data to analyse")
    parser.add_argument("--influx-url", default=INFLUX_URL)
    parser.add_argument("--output", default="./report", help="Directory for chart output")
    args = parser.parse_args()

    print(f"\nConnecting to InfluxDB at {args.influx_url}...")
    client = InfluxDBClient(url=args.influx_url, token=INFLUX_TOKEN, org=INFLUX_ORG)

    print(f"Loading last {args.hours}h of data...")
    telemetry = load_telemetry(client, args.hours)
    status = load_status(client, args.hours)

    if telemetry.empty:
        print("\n  No data found. Make sure the fleet simulator and bridge are running.")
        print("  Wait at least 60 seconds before running the analysis.\n")
        client.close()
        return

    print(f"  Loaded {len(telemetry):,} telemetry rows from {telemetry['device_id'].nunique()} devices")

    print_fleet_summary(telemetry, status)
    print_device_league_table(telemetry)
    print_location_analysis(telemetry)
    make_charts(telemetry, status, args.output)

    client.close()
    print("\nAnalysis complete.\n")


if __name__ == "__main__":
    main()
