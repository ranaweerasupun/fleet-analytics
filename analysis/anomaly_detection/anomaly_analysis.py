"""
anomaly_analysis.py
-------------------
Runs all three anomaly detection methods on the fleet telemetry,
compares their results, and produces:

  1. Terminal report    — per-device anomaly counts by method
  2. Comparison chart   — side-by-side visual of what each method flagged
  3. anomaly_report.csv — full results table for Power BI import

This script is the portfolio showpiece for statistical anomaly detection.
It shows you understand not just HOW to detect anomalies but WHICH method
to use for different data characteristics and WHY.

Run:
  python anomaly_analysis.py
  python anomaly_analysis.py --data ../../powerbi/sample_data --output ./output
"""

import argparse
import os
import sys

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch

sys.path.insert(0, os.path.dirname(__file__))
from detector import AnomalyDetector


# ── Load data ─────────────────────────────────────────────────────────────────

def load(data_dir: str) -> pd.DataFrame:
    path = os.path.join(data_dir, "telemetry.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"telemetry.csv not found at {path}")
    df = pd.read_csv(path, parse_dates=["Timestamp"])
    df["Is Anomaly"] = df["Is Anomaly"].astype(str).str.lower() == "true"
    print(f"Loaded {len(df):,} rows from {df['Device ID'].nunique()} devices\n")
    return df


# ── Terminal report ───────────────────────────────────────────────────────────

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
    consensus = result[result["consensus_anomaly"]].copy()
    if consensus.empty:
        print("  No consensus anomalies detected.\n")
        return

    print(f"  TOP CONSENSUS ANOMALIES ({len(consensus)} events)")
    print("  " + "-" * 68)
    cols = ["Timestamp","Device ID","Location","CPU %","Temperature (°C)","Signal (dBm)","max_zscore","iforest_score"]
    cols = [c for c in cols if c in consensus.columns]
    top = consensus.sort_values("iforest_score", ascending=False).head(10)
    for _, row in top.iterrows():
        ts  = str(row.get("Timestamp",""))[:16]
        dev = row.get("Device ID","")
        loc = row.get("Location","")
        cpu = row.get("CPU %", 0)
        tmp = row.get("Temperature (°C)", 0)
        zscore = row.get("max_zscore", 0)
        print(f"  {ts}  {dev:<14} {loc:<18}  CPU={cpu:.1f}%  Temp={tmp:.1f}°C  Z={zscore:.1f}")
    print()


# ── Charts ────────────────────────────────────────────────────────────────────

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

    # ── Panel 3: Method agreement heatmap ─────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.set_title("Method agreement per device", fontsize=11)
    if not summary.empty:
        heat_data = summary[["zscore_anomalies","iqr_anomalies","iforest_anomalies"]].astype(float).values
        # Normalise by total readings for fair comparison
        totals = summary["total_readings"].astype(float).values[:, None]
        heat_norm = (heat_data / totals * 100).T.astype(float)

        im = ax3.imshow(heat_norm, aspect="auto", cmap="YlOrRd", vmin=0, vmax=5)
        ax3.set_yticks([0,1,2])
        ax3.set_yticklabels(["Z-score","IQR","IForest"], fontsize=9)
        ax3.set_xticks(range(len(summary)))
        ax3.set_xticklabels(summary["Device ID"], rotation=45, ha="right", fontsize=7)
        plt.colorbar(im, ax=ax3, label="Anomaly rate (%)")

    # ── Panel 4: Z-score distribution ─────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.set_title("Z-score distribution (all devices)", fontsize=11)
    if "max_zscore" in result.columns:
        zscores = result["max_zscore"].dropna()
        ax4.hist(zscores[zscores < 8], bins=40, color=TEAL, alpha=0.7, edgecolor="white")
        ax4.axvline(3.0, color="red", linestyle="--", linewidth=1.5, label="Threshold (z=3)")
        ax4.set_xlabel("Max Z-score")
        ax4.set_ylabel("Count")
        ax4.legend(fontsize=9)

    # ── Panel 5: Temperature with IQR bounds ──────────────────────────────
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_title(f"Temperature + IQR bounds — {top_device}", fontsize=11)
    if "Timestamp" in dev_data.columns and "Temperature (°C)" in dev_data.columns:
        ax5.plot(dev_data["Timestamp"], dev_data["Temperature (°C)"],
                 color=CORAL, linewidth=0.9, alpha=0.7)

        lo_col = "iqr_lo_Temperature (°C)"
        hi_col = "iqr_hi_Temperature (°C)"
        if lo_col in dev_data.columns and hi_col in dev_data.columns:
            lo = dev_data[lo_col].iloc[0]
            hi = dev_data[hi_col].iloc[0]
            ax5.axhline(hi, color=AMBER, linestyle="--", linewidth=1.2, label=f"IQR upper {hi:.1f}°C")
            ax5.axhline(lo, color=PURPLE, linestyle="--", linewidth=1.2, label=f"IQR lower {lo:.1f}°C")
            iqr_flags = dev_data[dev_data["iqr_anomaly"] == True]
            if not iqr_flags.empty:
                ax5.scatter(iqr_flags["Timestamp"], iqr_flags["Temperature (°C)"],
                            color=AMBER, s=50, zorder=3, label="IQR flagged")
        ax5.set_ylabel("Temperature (°C)")
        ax5.legend(fontsize=8)
        ax5.tick_params(axis="x", rotation=30)

    # ── Panel 6: Isolation Forest scores ──────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.set_title(f"Isolation Forest anomaly score — {top_device}", fontsize=11)
    if "Timestamp" in dev_data.columns and "iforest_score" in dev_data.columns:
        scores = dev_data["iforest_score"].dropna()
        ts     = dev_data.loc[scores.index, "Timestamp"]
        ax6.plot(ts, scores, color=CORAL, linewidth=0.8, alpha=0.7)
        threshold = scores.quantile(0.98)
        ax6.axhline(threshold, color="red", linestyle="--", linewidth=1.2,
                    label=f"98th pct ({threshold:.3f})")
        ax6.fill_between(ts, scores, threshold,
                         where=(scores >= threshold), color=CORAL, alpha=0.4, label="Anomaly")
        ax6.set_ylabel("Anomaly score (higher = more anomalous)")
        ax6.legend(fontsize=8)
        ax6.tick_params(axis="x", rotation=30)

    # ── Panel 7: Consensus summary ─────────────────────────────────────────
    ax7 = fig.add_subplot(gs[2, 2])
    ax7.set_title("Consensus anomalies by device type", fontsize=11)
    if not summary.empty and "Device Type" in summary.columns:
        by_type = summary.groupby("Device Type")["consensus_anomalies"].sum().sort_values(ascending=True)
        colors_list = [TEAL, PURPLE, CORAL, AMBER][:len(by_type)]
        ax7.barh(by_type.index, by_type.values, color=colors_list, alpha=0.8)
        ax7.set_xlabel("Consensus anomaly count")
        for i, (val, name) in enumerate(zip(by_type.values, by_type.index)):
            ax7.text(val + 0.2, i, str(int(val)), va="center", fontsize=9)

    chart_path = os.path.join(output_dir, "anomaly_detection_comparison.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Chart saved → {chart_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Statistical anomaly detection on fleet telemetry")
    parser.add_argument("--data",   default="../../powerbi/sample_data")
    parser.add_argument("--output", default="./output")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    df = load(args.data)

    det    = AnomalyDetector(df)
    result = det.run_all()

    summary = AnomalyDetector.summarise(result)

    print_method_comparison(summary, n_rows=len(df))
    print_method_explanation()
    print_top_anomalies(result)

    make_charts(result, summary, args.output)

    # Export full results for Power BI
    out_cols = [
        "Timestamp","Device ID","Device Type","Location",
        "CPU %","RAM %","Temperature (°C)","Signal (dBm)",
        "zscore_anomaly","max_zscore","zscore_trigger",
        "iqr_anomaly","iqr_trigger",
        "iforest_anomaly","iforest_score",
        "method_count","consensus_anomaly",
    ]
    out_cols = [c for c in out_cols if c in result.columns]
    csv_path = os.path.join(args.output, "anomaly_report.csv")
    result[out_cols].to_csv(csv_path, index=False)
    print(f"  Full results → {csv_path}")

    # Summary CSV
    summary_path = os.path.join(args.output, "anomaly_summary.csv")
    summary.to_csv(summary_path, index=False)
    print(f"  Summary CSV  → {summary_path}\n")

    # Quick stats
    n_consensus = result["consensus_anomaly"].sum()
    n_total     = len(result)
    print(f"  Consensus anomalies detected: {int(n_consensus)} / {n_total:,} readings")
    print(f"  Fleet anomaly rate: {n_consensus/n_total*100:.2f}%\n")


if __name__ == "__main__":
    main()
