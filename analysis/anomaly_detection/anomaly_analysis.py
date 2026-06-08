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
        
        pass

def print_method_explanation():
        pass

def print_top_anomalies(result: pd.DataFrame):
        pass

def make_charts(result: pd.DataFrame, summary: pd.DataFrame, output_dir: str):
        pass

def main():
        pass

if __name__ == "__main__":
    main()