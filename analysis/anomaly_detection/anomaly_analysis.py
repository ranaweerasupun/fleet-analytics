"""
anomaly_analysis.py
-------------------
Runs all three anomaly detection methods on the fleet telemetry,
compares their results, and produces:

    1. Terminal report    — per-device anomaly counts by method
    2. Comparison chart   — side-by-side visual of what each method flagged
    3. anomaly_report.csv — full results table for Power BI import

"""
import argparse
import os
import sys

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Use non-interactive backend for plotting
import matplotlib.pyplot as plt 
import matplotlib.gridspec as gridspec
import matplotlib.patches as Patch

sys.path.insert(0, os.path.dirname(__file__))
from detector import AnomalyDetector

def load(data_dir: str) -> pd.DataFrame:
    path = os.path.join(data_dir, "telemetry.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"telemetry.csv not found at {path}")
    df = pd.read_csv(path, parse_dates=["Timestamp"])
    df["Is Anomaly"] = df["Is Anomaly"].astype(str).str.lower() == "true"
    print(f"Loaded {len(df):,} rows from {df['Device ID'].nunique()} devices\n")
    return df

def print_method_comparison(summary: pd.DataFrame, n_rows: int):
    print("═" * 72)
    print("  ANOMALY DETECTION — METHOD COMPARISON")
    print("═" * 72)
    print(f"  {'Device ID':<14} {'Type':<12} {'Location':<18} "
          f"{'Z-score':>8} {'IQR':>6} {'IForest':>8} {'Consensus':>10}")
    print("  " + "-" * 68)
    for _, row in summary.head(12).iterrows():
        print(
            f"  {row['Device ID']:<14} {row['Device Type']:<12} "
            f"{row['Location']:<18} "
            f"{int(row['zscore_anomalies']):>8} "
            f"{int(row['iqr_anomalies']):>6} "
            f"{int(row['iforest_anomalies']):>8} "
            f"{int(row['consensus_anomalies']):>10}"
        )
    print("═" * 72)

    # Rates
    z_rate  = summary["zscore_anomalies"].sum()  / summary["total_readings"].sum() * 100
    iq_rate = summary["iqr_anomalies"].sum()     / summary["total_readings"].sum() * 100
    if_rate = summary["iforest_anomalies"].sum() / summary["total_readings"].sum() * 100
    cs_rate = summary["consensus_anomalies"].sum()/ summary["total_readings"].sum()* 100

    print(f"\n  Fleet-wide anomaly rates:")
    print(f"    Z-score:          {z_rate:.2f}% of readings")
    print(f"    IQR:              {iq_rate:.2f}% of readings")
    print(f"    Isolation Forest: {if_rate:.2f}% of readings")
    print(f"    Consensus (2/3):  {cs_rate:.2f}% of readings  ← highest confidence")
    print()

def print_method_explanation():
    print("  METHOD GUIDE — when to use each one")
    print("  " + "-" * 68)
    methods = [
        ("Z-score",
         "Good for normally distributed sensor data (e.g. temperature).",
         "Sensitive — picks up small deviations. Can overfire on skewed data."),
        ("IQR",
         "Good for skewed or heavy-tailed data (e.g. CPU spikes).",
         "Robust — not thrown off by extreme values. Misses subtle drift."),
        ("Isolation Forest",
         "Good for catching multivariate anomalies — when the combination",
         "of features is unusual, not any single metric alone. Black-box."),
        ("Consensus (2/3)",
         "Use when you need high confidence. Only flags what multiple methods",
         "agree on. Fewer false positives — best for alerting a human."),
    ]
    for name, line1, line2 in methods:
        print(f"\n  {name}")
        print(f"    + {line1}")
        print(f"      {line2}")
    print()

def print_top_anomalies(result: pd.DataFrame):
        pass

def make_charts(result: pd.DataFrame, summary: pd.DataFrame, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle("IoT Fleet — Statistical Anomaly Detection Comparison",
                 fontsize=15, fontweight="bold", y=0.98)
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.50, wspace=0.35)

    TEAL   = "#1D9E75"
    PURPLE = "#7F77DD"
    CORAL  = "#D85A30"
    AMBER  = "#BA7517"
    GRAY   = "#888780"

    # Pick one representative device (highest consensus anomalies)
    top_device = summary.iloc[0]["Device ID"] if not summary.empty else result["Device ID"].iloc[0]
    dev_data   = result[result["Device ID"] == top_device].sort_values("Timestamp") if "Timestamp" in result.columns else result[result["Device ID"] == top_device]

    # ── Panel 1: CPU time series with anomaly overlays ─────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_title(f"CPU % over time — {top_device}  (all three methods shown)", fontsize=11)

    if "Timestamp" in dev_data.columns and "CPU %" in dev_data.columns:
        ax1.plot(dev_data["Timestamp"], dev_data["CPU %"],
                 color=GRAY, linewidth=0.8, alpha=0.7, label="CPU %", zorder=1)

        # Layer each method's flags
        for col, color, label, marker in [
            ("zscore_anomaly",  TEAL,   "Z-score",          "o"),
            ("iqr_anomaly",     AMBER,  "IQR",              "s"),
            ("iforest_anomaly", CORAL,  "Isolation Forest", "^"),
        ]:
            if col in dev_data.columns:
                flagged = dev_data[dev_data[col] == True]
                if not flagged.empty:
                    ax1.scatter(flagged["Timestamp"], flagged["CPU %"],
                                color=color, s=40, zorder=3, label=label,
                                marker=marker, alpha=0.85)

        # Consensus in bold
        if "consensus_anomaly" in dev_data.columns:
            consensus_pts = dev_data[dev_data["consensus_anomaly"] == True]
            if not consensus_pts.empty:
                ax1.scatter(consensus_pts["Timestamp"], consensus_pts["CPU %"],
                            color="black", s=120, zorder=4, marker="*",
                            label="Consensus (2/3 methods)", alpha=0.9)

        ax1.set_ylabel("CPU %")
        ax1.legend(loc="upper right", fontsize=8)
        ax1.tick_params(axis="x", rotation=30)

    # ── Panel 2: Anomaly count by device (bar chart) ──────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_title("Anomaly counts by device", fontsize=11)
    if not summary.empty:
        x  = range(len(summary))
        w  = 0.22
        ax2.bar([i - w for i in x], summary["zscore_anomalies"],  width=w, label="Z-score",  color=TEAL,   alpha=0.8)
        ax2.bar([i     for i in x], summary["iqr_anomalies"],     width=w, label="IQR",      color=AMBER,  alpha=0.8)
        ax2.bar([i + w for i in x], summary["iforest_anomalies"], width=w, label="IForest",  color=CORAL,  alpha=0.8)
        ax2.set_xticks(list(x))
        ax2.set_xticklabels(summary["Device ID"], rotation=45, ha="right", fontsize=7)
        ax2.set_ylabel("Anomaly count")
        ax2.legend(fontsize=8)

def main():
        pass

if __name__ == "__main__":
    main()