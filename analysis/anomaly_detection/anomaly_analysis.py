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
        pass

def main():
        pass

if __name__ == "__main__":
    main()