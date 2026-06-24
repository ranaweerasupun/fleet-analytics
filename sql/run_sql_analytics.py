"""
run_sql_analytics.py
--------------------
Loads fleet and AI4I data into DuckDB, runs all analytical queries,
prints results to terminal, and exports charts + CSVs.

DuckDB executes identical SQL to PostgreSQL for all queries in
analytics_queries.sql — window functions, CTEs, subqueries all work.

Run:
  python run_sql_analytics.py
  python run_sql_analytics.py --queries all
  python run_sql_analytics.py --queries fleet
  python run_sql_analytics.py --queries machines
"""

import argparse
import os
import textwrap
import duckdb
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

import sys
BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
except Exception:
    pass  # SQL runner uses CSV files, not InfluxDB directly
POWERBI_DATA = os.path.join(BASE, "powerbi", "sample_data")
AI4I_DATA    = os.path.join(BASE, "notebooks", "data")
OUTPUT_DIR   = os.path.join(os.path.dirname(__file__), "output")

TEAL   = "#1D9E75"
PURPLE = "#7F77DD"
CORAL  = "#D85A30"
AMBER  = "#BA7517"
GRAY   = "#888780"


# ── Database setup ────────────────────────────────────────────────────────────

def build_db(con: duckdb.DuckDBPyConnection):
    """Load all CSV data into DuckDB tables."""

    print("Loading fleet telemetry...")
    tel_path = os.path.join(POWERBI_DATA, "telemetry.csv")
    con.execute(f"""
        CREATE OR REPLACE TABLE fleet_telemetry AS
        SELECT
            ROW_NUMBER() OVER ()                        AS id,
            CAST(Timestamp AS TIMESTAMP)                AS timestamp,
            "Device ID"                                 AS device_id,
            "Device Type"                               AS device_type,
            Location                                    AS location,
            "CPU %"                                     AS cpu_pct,
            "RAM %"                                     AS ram_pct,
            "Temperature (°C)"                          AS temperature_c,
            "Signal (dBm)"                              AS signal_dbm,
            "Uptime (s)"                                AS uptime_s,
            CAST("Is Anomaly" AS BOOLEAN)               AS is_anomaly,
            "Signal Quality"                            AS signal_quality,
            "Temp Status"                               AS temp_status,
            "CPU Status"                                AS cpu_status
        FROM read_csv_auto('{tel_path}', header=True)
    """)

    print("Loading fleet status...")
    sta_path = os.path.join(POWERBI_DATA, "status.csv")
    con.execute(f"""
        CREATE OR REPLACE TABLE fleet_status AS
        SELECT
            "Device ID"             AS device_id,
            "Device Type"           AS device_type,
            Location                AS location,
            "Uptime (s)"            AS uptime_s,
            "Uptime (hours)"        AS uptime_hours,
            "Messages Published"    AS messages_published,
            "Error Count"           AS error_count,
            "Queue Depth"           AS queue_depth,
            "Reconnect Count"       AS reconnect_count,
            "Connection Status"     AS connection_status
        FROM read_csv_auto('{sta_path}', header=True)
    """)

    print("Loading fleet events...")
    evt_path = os.path.join(POWERBI_DATA, "events.csv")
    con.execute(f"""
        CREATE OR REPLACE TABLE fleet_events AS
        SELECT
            ROW_NUMBER() OVER ()    AS id,
            "Device ID"             AS device_id,
            "Device Type"           AS device_type,
            Location                AS location,
            "Event Type"            AS event_type,
            "Firmware Version"      AS firmware_version,
            CAST(Timestamp AS TIMESTAMP) AS event_timestamp
        FROM read_csv_auto('{evt_path}', header=True)
    """)

    print("Loading AI4I machine data...")
    ai4i_path = os.path.join(AI4I_DATA, "ai4i2020_clean.csv")
    con.execute(f"""
        CREATE OR REPLACE TABLE machines AS
        SELECT
            UDI                             AS udi,
            "Product ID"                    AS product_id,
            Type                            AS machine_type,
            "Air temperature [K]"           AS air_temp_k,
            "Process temperature [K]"       AS process_temp_k,
            "Rotational speed [rpm]"        AS rotational_speed_rpm,
            "Torque [Nm]"                   AS torque_nm,
            CAST("Tool wear [min]" AS INTEGER) AS tool_wear_min,
            CAST("Machine failure" AS BOOLEAN) AS machine_failure,
            CAST(TWF AS BOOLEAN)            AS failure_twf,
            CAST(HDF AS BOOLEAN)            AS failure_hdf,
            CAST(PWF AS BOOLEAN)            AS failure_pwf,
            CAST(OSF AS BOOLEAN)            AS failure_osf,
            CAST(RNF AS BOOLEAN)            AS failure_rnf,
            "Power [W]"                     AS power_w,
            "Temp diff [K]"                 AS temp_diff_k,
            "Wear-torque product"           AS wear_torque_product,
            "Speed-torque product"          AS speed_torque_product,
            "Wear stage"                    AS wear_stage
        FROM read_csv_auto('{ai4i_path}', header=True)
    """)

    rows = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ["fleet_telemetry","fleet_status","fleet_events","machines"]
    }
    print("\nTables loaded:")
    for t, n in rows.items():
        print(f"  {t:<20} {n:>7,} rows")
    print()


# ── Query definitions ─────────────────────────────────────────────────────────

FLEET_QUERIES = {
    "1.1_fleet_health_summary": (
        "Fleet health summary",
        """
        SELECT
            COUNT(DISTINCT t.device_id)                          AS total_devices,
            COUNT(DISTINCT CASE WHEN s.connection_status = 'Online'
                                THEN t.device_id END)            AS online_devices,
            COUNT(DISTINCT CASE WHEN s.connection_status = 'Offline'
                                THEN t.device_id END)            AS offline_devices,
            ROUND(COUNT(DISTINCT CASE WHEN s.connection_status = 'Online'
                                      THEN t.device_id END) * 100.0
                  / COUNT(DISTINCT t.device_id), 1)              AS fleet_uptime_pct,
            ROUND(AVG(t.cpu_pct), 1)                             AS avg_cpu_pct,
            ROUND(AVG(t.temperature_c), 1)                       AS avg_temp_c,
            ROUND(MAX(t.temperature_c), 1)                       AS max_temp_c,
            SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END)        AS total_anomalies,
            ROUND(SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END) * 100.0
                  / COUNT(*), 2)                                 AS anomaly_rate_pct
        FROM fleet_telemetry t
        LEFT JOIN fleet_status s ON t.device_id = s.device_id
        """
    ),
    "1.2_per_device_summary": (
        "Per-device performance summary",
        """
        SELECT
            t.device_id,
            t.device_type,
            t.location,
            s.connection_status,
            COUNT(*)                                             AS reading_count,
            ROUND(AVG(t.cpu_pct), 1)                             AS avg_cpu_pct,
            ROUND(MAX(t.cpu_pct), 1)                             AS max_cpu_pct,
            ROUND(AVG(t.temperature_c), 1)                       AS avg_temp_c,
            ROUND(MAX(t.temperature_c), 1)                       AS max_temp_c,
            ROUND(AVG(t.signal_dbm), 0)                          AS avg_signal_dbm,
            SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END)        AS anomaly_count,
            s.reconnect_count,
            s.queue_depth
        FROM fleet_telemetry t
        LEFT JOIN fleet_status s ON t.device_id = s.device_id
        GROUP BY t.device_id, t.device_type, t.location,
                 s.connection_status, s.reconnect_count, s.queue_depth
        ORDER BY anomaly_count DESC, avg_cpu_pct DESC
        """
    ),
    "1.3_cpu_ranking": (
        "CPU load ranking with RANK() window function",
        """
        SELECT
            device_id, device_type, location,
            ROUND(AVG(cpu_pct), 1)                               AS avg_cpu_pct,
            RANK() OVER (PARTITION BY location
                         ORDER BY AVG(cpu_pct) DESC)             AS rank_in_location,
            RANK() OVER (ORDER BY AVG(cpu_pct) DESC)             AS fleet_rank
        FROM fleet_telemetry
        GROUP BY device_id, device_type, location
        ORDER BY location, rank_in_location
        """
    ),
    "1.4_hourly_patterns": (
        "Hourly telemetry patterns",
        """
        SELECT
            EXTRACT(HOUR FROM timestamp)                         AS hour_of_day,
            COUNT(*)                                             AS reading_count,
            ROUND(AVG(cpu_pct), 1)                               AS avg_cpu_pct,
            ROUND(AVG(temperature_c), 1)                         AS avg_temp_c,
            ROUND(MAX(cpu_pct), 1)                               AS peak_cpu_pct,
            SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)          AS anomaly_count
        FROM fleet_telemetry
        GROUP BY EXTRACT(HOUR FROM timestamp)
        ORDER BY hour_of_day
        """
    ),
    "1.5_anomaly_by_location": (
        "Anomaly rate by location and device type",
        """
        SELECT
            location, device_type,
            COUNT(*)                                             AS total_readings,
            SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)          AS anomaly_count,
            ROUND(SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) * 100.0
                  / COUNT(*), 2)                                 AS anomaly_rate_pct
        FROM fleet_telemetry
        GROUP BY location, device_type
        HAVING COUNT(*) > 50
        ORDER BY anomaly_rate_pct DESC
        """
    ),
    "1.8_spike_detection": (
        "Sudden spikes detected with LAG() window function",
        """
        WITH readings_with_prev AS (
            SELECT device_id, device_type, location, timestamp, cpu_pct, temperature_c,
                   LAG(cpu_pct) OVER (PARTITION BY device_id ORDER BY timestamp)       AS prev_cpu,
                   LAG(temperature_c) OVER (PARTITION BY device_id ORDER BY timestamp) AS prev_temp
            FROM fleet_telemetry
        )
        SELECT
            device_id, device_type, location, timestamp,
            cpu_pct, prev_cpu,
            ROUND(cpu_pct - prev_cpu, 1)                         AS cpu_delta,
            temperature_c,
            ROUND(temperature_c - prev_temp, 2)                  AS temp_delta,
            CASE WHEN cpu_pct - prev_cpu > 25 THEN 'CPU spike'
                 WHEN temperature_c - prev_temp > 5 THEN 'Temp spike'
                 ELSE 'Normal' END                               AS spike_type
        FROM readings_with_prev
        WHERE prev_cpu IS NOT NULL
          AND (cpu_pct - prev_cpu > 25 OR temperature_c - prev_temp > 5)
        ORDER BY ABS(cpu_pct - prev_cpu) DESC
        LIMIT 15
        """
    ),
    "1.9_reliability_tiers": (
        "Device reliability tier classification (CTE chain)",
        """
        WITH device_metrics AS (
            SELECT t.device_id, t.device_type, t.location, s.connection_status,
                   ROUND(AVG(t.cpu_pct), 1)                      AS avg_cpu,
                   ROUND(MAX(t.cpu_pct), 1)                      AS max_cpu,
                   ROUND(AVG(t.temperature_c), 1)                AS avg_temp,
                   SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END) AS anomaly_count,
                   COUNT(*)                                      AS total_readings,
                   s.reconnect_count, s.queue_depth
            FROM fleet_telemetry t
            LEFT JOIN fleet_status s ON t.device_id = s.device_id
            GROUP BY t.device_id, t.device_type, t.location,
                     s.connection_status, s.reconnect_count, s.queue_depth
        ),
        scored AS (
            SELECT *,
                   ROUND(anomaly_count * 100.0 / total_readings, 2) AS anomaly_rate_pct,
                   ROUND(100.0
                         - (CASE WHEN max_cpu >= 85 THEN 15 ELSE 0 END)
                         - (CASE WHEN avg_temp >= 70 THEN 10 ELSE 0 END)
                         - (LEAST(reconnect_count, 10) * 2.0)
                         - (CASE WHEN connection_status = 'Offline' THEN 20 ELSE 0 END)
                         - (anomaly_count * 1.5)
                   , 1)                                            AS health_score
            FROM device_metrics
        )
        SELECT device_id, device_type, location, connection_status,
               avg_cpu, max_cpu, avg_temp, anomaly_count, reconnect_count,
               health_score,
               CASE WHEN health_score >= 85 THEN 'Tier 1 — Healthy'
                    WHEN health_score >= 70 THEN 'Tier 2 — Monitor'
                    WHEN health_score >= 50 THEN 'Tier 3 — At Risk'
                    ELSE                         'Tier 4 — Critical' END AS reliability_tier,
               RANK() OVER (ORDER BY health_score DESC)            AS health_rank
        FROM scored
        ORDER BY health_rank
        """
    ),
}

MACHINE_QUERIES = {
    "2.1_failure_by_type": (
        "Machine failure rate by type",
        """
        SELECT machine_type,
               COUNT(*)                                              AS total_readings,
               SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)     AS failure_count,
               ROUND(SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
                     / COUNT(*), 2)                                  AS failure_rate_pct,
               ROUND(AVG(torque_nm), 1)                              AS avg_torque_nm,
               ROUND(AVG(rotational_speed_rpm), 0)                   AS avg_speed_rpm,
               ROUND(AVG(tool_wear_min), 0)                          AS avg_tool_wear_min
        FROM machines
        GROUP BY machine_type
        ORDER BY failure_rate_pct DESC
        """
    ),
    "2.3_wear_stage_risk": (
        "Failure rate by tool wear stage",
        """
        SELECT wear_stage,
               COUNT(*)                                              AS readings,
               SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)     AS failures,
               ROUND(SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
                     / COUNT(*), 2)                                  AS failure_rate_pct,
               ROUND(AVG(torque_nm), 1)                              AS avg_torque,
               ROUND(AVG(tool_wear_min), 0)                          AS avg_wear_min
        FROM machines
        GROUP BY wear_stage
        ORDER BY CASE wear_stage WHEN 'early' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END
        """
    ),
    "2.4_operating_envelope": (
        "Failure zones by torque and speed bands",
        """
        WITH bucketed AS (
            SELECT machine_failure,
                   CASE WHEN torque_nm < 30          THEN 'Low (<30 Nm)'
                        WHEN torque_nm <= 50          THEN 'Normal (30–50 Nm)'
                        ELSE                               'High (>50 Nm)' END AS torque_band,
                   CASE WHEN rotational_speed_rpm < 1400    THEN 'Low (<1400)'
                        WHEN rotational_speed_rpm <= 1700   THEN 'Normal (1400–1700)'
                        ELSE                                     'High (>1700)' END AS speed_band
            FROM machines
        )
        SELECT torque_band, speed_band,
               COUNT(*)                                              AS reading_count,
               SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)     AS failure_count,
               ROUND(SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
                     / COUNT(*), 2)                                  AS failure_rate_pct
        FROM bucketed
        GROUP BY torque_band, speed_band
        ORDER BY failure_rate_pct DESC
        """
    ),
    "2.6_risk_ranking": (
        "Top 15 highest-risk machines (composite score)",
        """
        WITH risk_scored AS (
            SELECT udi, product_id, machine_type, tool_wear_min,
                   torque_nm, rotational_speed_rpm, power_w, temp_diff_k,
                   ROUND((tool_wear_min / 253.0 * 40)
                         + CASE WHEN torque_nm > 50 THEN 30
                                WHEN torque_nm > 40 THEN 15
                                ELSE 0 END
                         + CASE WHEN temp_diff_k < 8.6 THEN 20 ELSE 0 END
                         + CASE WHEN power_w > 8000 OR power_w < 3500 THEN 10 ELSE 0 END
                   , 1)                                              AS risk_score
            FROM machines
            WHERE NOT machine_failure
        )
        SELECT RANK() OVER (ORDER BY risk_score DESC)                AS risk_rank,
               udi, product_id, machine_type,
               tool_wear_min, ROUND(torque_nm,1)                     AS torque_nm,
               ROUND(power_w,0)                                      AS power_w,
               ROUND(temp_diff_k,1)                                  AS temp_diff_k,
               risk_score,
               CASE WHEN risk_score >= 70 THEN 'Immediate attention'
                    WHEN risk_score >= 50 THEN 'Schedule maintenance'
                    WHEN risk_score >= 30 THEN 'Monitor closely'
                    ELSE                       'Normal operation' END AS recommendation
        FROM risk_scored
        QUALIFY RANK() OVER (ORDER BY risk_score DESC) <= 15
        ORDER BY risk_rank
        """
    ),
}


# ── Runner ────────────────────────────────────────────────────────────────────

def run_query(con, key: str, label: str, sql: str, output_dir: str) -> pd.DataFrame:
    print(f"\n{'─'*60}")
    print(f"  Query {key}: {label}")
    print(f"{'─'*60}")
    df = con.execute(textwrap.dedent(sql)).df()
    print(df.to_string(index=False))
    csv_path = os.path.join(output_dir, f"{key}.csv")
    df.to_csv(csv_path, index=False)
    return df


def make_charts(results: dict, output_dir: str):
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(18, 14))
    fig.suptitle("SQL Analytics Results — Fleet + Industrial Machines", fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.50, wspace=0.38)

    # 1 — Fleet uptime bar
    ax1 = fig.add_subplot(gs[0, 0])
    if "1.2_per_device_summary" in results:
        df = results["1.2_per_device_summary"]
        colors = [TEAL if s == "Online" else CORAL
                  for s in df["connection_status"]]
        ax1.barh(df["device_id"], df["avg_cpu_pct"], color=colors, alpha=0.8)
        from matplotlib.patches import Patch
        ax1.legend(handles=[Patch(color=TEAL,label="Online"),
                             Patch(color=CORAL,label="Offline")], fontsize=8)
        ax1.set_xlabel("Avg CPU %")
        ax1.set_title("Avg CPU by device (SQL query 1.2)", fontsize=10)

    # 2 — Hourly patterns
    ax2 = fig.add_subplot(gs[0, 1])
    if "1.4_hourly_patterns" in results:
        df = results["1.4_hourly_patterns"]
        ax2.plot(df["hour_of_day"], df["avg_cpu_pct"],
                 color=TEAL, linewidth=2, marker="o", markersize=4, label="Avg CPU %")
        ax2.plot(df["hour_of_day"], df["avg_temp_c"],
                 color=CORAL, linewidth=2, marker="s", markersize=4, label="Avg Temp °C")
        ax2.set_xlabel("Hour of day")
        ax2.set_title("Hourly patterns (SQL query 1.4)", fontsize=10)
        ax2.legend(fontsize=8)

    # 3 — Anomaly by location
    ax3 = fig.add_subplot(gs[0, 2])
    if "1.5_anomaly_by_location" in results:
        df = results["1.5_anomaly_by_location"].head(10)
        ax3.barh(df["location"] + " / " + df["device_type"],
                 df["anomaly_rate_pct"], color=AMBER, alpha=0.8)
        ax3.set_xlabel("Anomaly rate (%)")
        ax3.set_title("Anomaly rate by location+type (SQL 1.5)", fontsize=10)

    # 4 — Reliability tier
    ax4 = fig.add_subplot(gs[1, 0])
    if "1.9_reliability_tiers" in results:
        df = results["1.9_reliability_tiers"]
        tier_colors = {
            "Tier 1 — Healthy":  TEAL,
            "Tier 2 — Monitor":  AMBER,
            "Tier 3 — At Risk":  CORAL,
            "Tier 4 — Critical": "#A32D2D",
        }
        tier_counts = df["reliability_tier"].value_counts()
        ax4.bar(range(len(tier_counts)),
                tier_counts.values,
                color=[tier_colors.get(t, GRAY) for t in tier_counts.index],
                alpha=0.85)
        ax4.set_xticks(range(len(tier_counts)))
        ax4.set_xticklabels([t.split("—")[0].strip() for t in tier_counts.index],
                             rotation=20, ha="right", fontsize=8)
        ax4.set_ylabel("Device count")
        ax4.set_title("Device reliability tiers (SQL CTE 1.9)", fontsize=10)

    # 5 — Machine failure rate by type
    ax5 = fig.add_subplot(gs[1, 1])
    if "2.1_failure_by_type" in results:
        df = results["2.1_failure_by_type"]
        bars = ax5.bar(df["machine_type"], df["failure_rate_pct"],
                       color=[TEAL, PURPLE, CORAL], alpha=0.8)
        ax5.set_ylabel("Failure rate (%)")
        ax5.set_title("Machine failure by type (SQL 2.1)", fontsize=10)
        for bar, val in zip(bars, df["failure_rate_pct"]):
            ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                     f"{val:.1f}%", ha="center", va="bottom", fontsize=9)

    # 6 — Wear stage risk
    ax6 = fig.add_subplot(gs[1, 2])
    if "2.3_wear_stage_risk" in results:
        df = results["2.3_wear_stage_risk"].copy()
        stage_order = ["early","mid","late"]
        df["wear_stage"] = pd.Categorical(df["wear_stage"],
                                          categories=stage_order, ordered=True)
        df = df.sort_values("wear_stage")
        ax6.bar(df["wear_stage"].astype(str), df["failure_rate_pct"],
                color=[TEAL, AMBER, CORAL], alpha=0.8)
        ax6.set_ylabel("Failure rate (%)")
        ax6.set_title("Failure rate by wear stage (SQL 2.3)", fontsize=10)

    # 7 — Operating envelope heatmap
    ax7 = fig.add_subplot(gs[2, 0:2])
    if "2.4_operating_envelope" in results:
        df = results["2.4_operating_envelope"]
        pivot = df.pivot_table(
            values="failure_rate_pct",
            index="speed_band",
            columns="torque_band",
            aggfunc="mean"
        ).fillna(0)
        im = ax7.imshow(pivot.values.astype(float), cmap="YlOrRd",
                        aspect="auto", vmin=0)
        ax7.set_xticks(range(len(pivot.columns)))
        ax7.set_yticks(range(len(pivot.index)))
        ax7.set_xticklabels(pivot.columns, fontsize=8)
        ax7.set_yticklabels(pivot.index, fontsize=8)
        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                ax7.text(j, i, f"{pivot.values[i,j]:.1f}%",
                         ha="center", va="center", fontsize=9, fontweight="bold")
        plt.colorbar(im, ax=ax7, label="Failure rate (%)")
        ax7.set_title("Failure rate by operating envelope (SQL CTE 2.4)", fontsize=10)

    # 8 — Top risk machines
    ax8 = fig.add_subplot(gs[2, 2])
    if "2.6_risk_ranking" in results:
        df = results["2.6_risk_ranking"].head(10)
        rec_colors = {
            "Immediate attention":   "#A32D2D",
            "Schedule maintenance":  CORAL,
            "Monitor closely":       AMBER,
            "Normal operation":      TEAL,
        }
        bar_colors = [rec_colors.get(r, GRAY) for r in df["recommendation"]]
        ax8.barh(df["product_id"], df["risk_score"],
                 color=bar_colors, alpha=0.85)
        ax8.set_xlabel("Risk score")
        ax8.set_title("Top 10 highest-risk machines (SQL window 2.6)", fontsize=10)

    chart_path = os.path.join(output_dir, "sql_analytics_results.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  Charts saved → {chart_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", choices=["all","fleet","machines"], default="all")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    con = duckdb.connect()
    build_db(con)

    results = {}
    queries = {}
    if args.queries in ("all", "fleet"):
        queries.update(FLEET_QUERIES)
    if args.queries in ("all", "machines"):
        queries.update(MACHINE_QUERIES)

    for key, (label, sql) in queries.items():
        try:
            results[key] = run_query(con, key, label, sql, OUTPUT_DIR)
        except Exception as e:
            print(f"  ERROR in {key}: {e}")

    print(f"\n\nGenerating charts...")
    make_charts(results, OUTPUT_DIR)

    con.close()
    print(f"\nAll results saved to {OUTPUT_DIR}/")
    print(f"Query CSVs: {len(results)} files written")


if __name__ == "__main__":
    main()
