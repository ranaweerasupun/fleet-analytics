-- analytics_queries.sql
-- Fleet Analytics + AI4I Predictive Maintenance — Analytical SQL
--
-- Demonstrates:
--   GROUP BY + aggregations    — the foundation
--   Window functions           — ROW_NUMBER, RANK, LAG, LEAD, running totals
--   CTEs                       — readable multi-step logic
--   Subqueries                 — correlated and uncorrelated
--   CASE expressions           — conditional classification
--   JOINs                      — LEFT, INNER, self-join
--   Date/time functions        — hour bucketing, time differences
--
-- Each query has: what it does, why a client cares, and the SQL.
-- Compatible with PostgreSQL and DuckDB (minor notes where they differ).

-- ═══════════════════════════════════════════════════════════════════════════
-- SECTION 1 — FLEET ANALYTICS
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1.1  Fleet health summary ───────────────────────────────────────────────
-- Business question: "Give me one number — how healthy is the fleet right now?"
-- Technique: aggregation + CASE + subquery

SELECT
    COUNT(DISTINCT t.device_id)                          AS total_devices,
    COUNT(DISTINCT CASE WHEN s.connection_status = 'Online'
                        THEN t.device_id END)            AS online_devices,
    COUNT(DISTINCT CASE WHEN s.connection_status = 'Offline'
                        THEN t.device_id END)            AS offline_devices,
    ROUND(
        COUNT(DISTINCT CASE WHEN s.connection_status = 'Online'
                            THEN t.device_id END) * 100.0
        / COUNT(DISTINCT t.device_id), 1
    )                                                    AS fleet_uptime_pct,
    ROUND(AVG(t.cpu_pct), 1)                             AS avg_cpu_pct,
    ROUND(AVG(t.temperature_c), 1)                       AS avg_temp_c,
    ROUND(MAX(t.temperature_c), 1)                       AS max_temp_c,
    SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END)        AS total_anomalies,
    ROUND(
        SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS anomaly_rate_pct
FROM fleet_telemetry t
LEFT JOIN fleet_status s ON t.device_id = s.device_id;


-- ── 1.2  Per-device performance summary ─────────────────────────────────────
-- Business question: "Which specific devices need attention?"
-- Technique: GROUP BY + multiple aggregations + JOIN + ORDER BY

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
    s.queue_depth,
    s.messages_published
FROM fleet_telemetry t
LEFT JOIN fleet_status s ON t.device_id = s.device_id
GROUP BY
    t.device_id, t.device_type, t.location,
    s.connection_status, s.reconnect_count,
    s.queue_depth, s.messages_published
ORDER BY anomaly_count DESC, avg_cpu_pct DESC;


-- ── 1.3  CPU load ranking with window functions ──────────────────────────────
-- Business question: "Rank devices by CPU load within their location."
-- Technique: RANK() window function, partitioned by location

SELECT
    device_id,
    device_type,
    location,
    ROUND(AVG(cpu_pct), 1)                               AS avg_cpu_pct,
    RANK() OVER (
        PARTITION BY location
        ORDER BY AVG(cpu_pct) DESC
    )                                                    AS rank_in_location,
    RANK() OVER (
        ORDER BY AVG(cpu_pct) DESC
    )                                                    AS fleet_rank
FROM fleet_telemetry
GROUP BY device_id, device_type, location
ORDER BY location, rank_in_location;


-- ── 1.4  Hourly telemetry patterns ─────────────────────────────────────────
-- Business question: "When during the day do devices run hottest?"
-- Technique: date/time extraction, GROUP BY time bucket

SELECT
    EXTRACT(HOUR FROM timestamp)                         AS hour_of_day,
    COUNT(*)                                             AS reading_count,
    ROUND(AVG(cpu_pct), 1)                               AS avg_cpu_pct,
    ROUND(AVG(temperature_c), 1)                         AS avg_temp_c,
    ROUND(MAX(cpu_pct), 1)                               AS peak_cpu_pct,
    SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)          AS anomaly_count
FROM fleet_telemetry
GROUP BY EXTRACT(HOUR FROM timestamp)
ORDER BY hour_of_day;


-- ── 1.5  Anomaly rate by location and device type ──────────────────────────
-- Business question: "Which locations have the most problems?"
-- Technique: GROUP BY multiple columns, HAVING, percentage calculation

SELECT
    location,
    device_type,
    COUNT(*)                                             AS total_readings,
    SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)          AS anomaly_count,
    ROUND(
        SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS anomaly_rate_pct
FROM fleet_telemetry
GROUP BY location, device_type
HAVING COUNT(*) > 50
ORDER BY anomaly_rate_pct DESC;


-- ── 1.6  Signal quality classification pivot ────────────────────────────────
-- Business question: "How many devices have poor connectivity?"
-- Technique: CASE classification + conditional aggregation (manual pivot)

SELECT
    location,
    COUNT(DISTINCT device_id)                            AS device_count,
    COUNT(DISTINCT CASE WHEN signal_quality = 'Excellent'
                        THEN device_id END)              AS excellent,
    COUNT(DISTINCT CASE WHEN signal_quality = 'Good'
                        THEN device_id END)              AS good,
    COUNT(DISTINCT CASE WHEN signal_quality = 'Fair'
                        THEN device_id END)              AS fair,
    COUNT(DISTINCT CASE WHEN signal_quality = 'Poor'
                        THEN device_id END)              AS poor,
    ROUND(AVG(signal_dbm), 1)                            AS avg_signal_dbm
FROM fleet_telemetry
GROUP BY location
ORDER BY avg_signal_dbm ASC;


-- ── 1.7  Running cumulative message count per device ────────────────────────
-- Business question: "How fast is each device publishing data over time?"
-- Technique: SUM() OVER (PARTITION BY ... ORDER BY ...) — running total window

SELECT
    device_id,
    device_type,
    timestamp,
    cpu_pct,
    ROW_NUMBER() OVER (
        PARTITION BY device_id
        ORDER BY timestamp
    )                                                    AS reading_number,
    SUM(1) OVER (
        PARTITION BY device_id
        ORDER BY timestamp
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                    AS cumulative_readings,
    -- Rolling average CPU over last 5 readings per device
    ROUND(
        AVG(cpu_pct) OVER (
            PARTITION BY device_id
            ORDER BY timestamp
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 1
    )                                                    AS rolling_avg_cpu_5
FROM fleet_telemetry
ORDER BY device_id, timestamp;


-- ── 1.8  Previous reading comparison with LAG ───────────────────────────────
-- Business question: "Which readings show sudden spikes from the prior reading?"
-- Technique: LAG() window function for sequential comparison

WITH readings_with_prev AS (
    SELECT
        device_id,
        device_type,
        location,
        timestamp,
        cpu_pct,
        temperature_c,
        LAG(cpu_pct) OVER (
            PARTITION BY device_id
            ORDER BY timestamp
        )                                                AS prev_cpu_pct,
        LAG(temperature_c) OVER (
            PARTITION BY device_id
            ORDER BY timestamp
        )                                                AS prev_temp_c
    FROM fleet_telemetry
)
SELECT
    device_id,
    device_type,
    location,
    timestamp,
    cpu_pct,
    prev_cpu_pct,
    ROUND(cpu_pct - prev_cpu_pct, 1)                     AS cpu_delta,
    temperature_c,
    prev_temp_c,
    ROUND(temperature_c - prev_temp_c, 2)                AS temp_delta,
    CASE
        WHEN cpu_pct - prev_cpu_pct > 25 THEN 'CPU spike'
        WHEN temperature_c - prev_temp_c > 5 THEN 'Temp spike'
        ELSE 'Normal'
    END                                                  AS spike_type
FROM readings_with_prev
WHERE prev_cpu_pct IS NOT NULL
  AND (cpu_pct - prev_cpu_pct > 25
       OR temperature_c - prev_temp_c > 5)
ORDER BY ABS(cpu_pct - prev_cpu_pct) DESC
LIMIT 20;


-- ── 1.9  Device reliability tier classification (CTE chain) ─────────────────
-- Business question: "Classify every device into reliability tiers."
-- Technique: multi-step CTE chain — each step builds on the last

WITH
-- Step 1: compute raw metrics per device
device_metrics AS (
    SELECT
        t.device_id,
        t.device_type,
        t.location,
        s.connection_status,
        ROUND(AVG(t.cpu_pct), 1)                         AS avg_cpu,
        ROUND(MAX(t.cpu_pct), 1)                         AS max_cpu,
        ROUND(AVG(t.temperature_c), 1)                   AS avg_temp,
        SUM(CASE WHEN t.is_anomaly THEN 1 ELSE 0 END)    AS anomaly_count,
        COUNT(*)                                         AS total_readings,
        s.reconnect_count,
        s.queue_depth
    FROM fleet_telemetry t
    LEFT JOIN fleet_status s ON t.device_id = s.device_id
    GROUP BY
        t.device_id, t.device_type, t.location,
        s.connection_status, s.reconnect_count, s.queue_depth
),
-- Step 2: compute anomaly rate and health score
scored AS (
    SELECT
        *,
        ROUND(anomaly_count * 100.0 / total_readings, 2) AS anomaly_rate_pct,
        -- Health score: starts at 100, deductions for problems
        ROUND(
            100.0
            - (CASE WHEN max_cpu >= 85 THEN 15 ELSE 0 END)
            - (CASE WHEN avg_temp >= 70 THEN 10 ELSE 0 END)
            - (LEAST(reconnect_count, 10) * 2.0)
            - (CASE WHEN connection_status = 'Offline' THEN 20 ELSE 0 END)
            - (anomaly_count * 1.5)
        , 1)                                             AS health_score
    FROM device_metrics
),
-- Step 3: assign tier based on health score
tiered AS (
    SELECT
        *,
        CASE
            WHEN health_score >= 85                      THEN 'Tier 1 — Healthy'
            WHEN health_score >= 70                      THEN 'Tier 2 — Monitor'
            WHEN health_score >= 50                      THEN 'Tier 3 — At Risk'
            ELSE                                              'Tier 4 — Critical'
        END                                              AS reliability_tier,
        RANK() OVER (ORDER BY health_score DESC)         AS health_rank
    FROM scored
)
SELECT
    device_id,
    device_type,
    location,
    connection_status,
    avg_cpu,
    max_cpu,
    avg_temp,
    anomaly_count,
    reconnect_count,
    queue_depth,
    health_score,
    reliability_tier,
    health_rank
FROM tiered
ORDER BY health_rank;


-- ── 1.10  Devices with connectivity problems (correlated subquery) ───────────
-- Business question: "Which devices reconnect more than the fleet average?"
-- Technique: correlated subquery in WHERE clause

SELECT
    device_id,
    device_type,
    location,
    reconnect_count,
    queue_depth,
    connection_status,
    ROUND(
        reconnect_count - (SELECT AVG(reconnect_count) FROM fleet_status), 1
    )                                                    AS above_fleet_avg
FROM fleet_status
WHERE reconnect_count > (
    SELECT AVG(reconnect_count) FROM fleet_status
)
ORDER BY reconnect_count DESC;


-- ═══════════════════════════════════════════════════════════════════════════
-- SECTION 2 — INDUSTRIAL / PREDICTIVE MAINTENANCE
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 2.1  Overall failure rate by machine type ───────────────────────────────
-- Technique: GROUP BY + HAVING + CASE for conditional display

SELECT
    machine_type,
    COUNT(*)                                             AS total_readings,
    SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)     AS failure_count,
    ROUND(
        SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS failure_rate_pct,
    ROUND(AVG(torque_nm), 1)                             AS avg_torque_nm,
    ROUND(AVG(rotational_speed_rpm), 0)                  AS avg_speed_rpm,
    ROUND(AVG(tool_wear_min), 0)                         AS avg_tool_wear_min,
    CASE
        WHEN SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
             / COUNT(*) > 5 THEN 'High risk'
        WHEN SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
             / COUNT(*) > 2 THEN 'Medium risk'
        ELSE 'Low risk'
    END                                                  AS risk_category
FROM machines
GROUP BY machine_type
ORDER BY failure_rate_pct DESC;


-- ── 2.2  Failure mode breakdown ─────────────────────────────────────────────
-- Business question: "What's causing failures?"
-- Technique: UNION ALL to unpivot failure modes into rows

SELECT 'TWF — Tool Wear Failure'         AS failure_mode,
       SUM(CASE WHEN failure_twf THEN 1 ELSE 0 END)  AS event_count,
       ROUND(SUM(CASE WHEN failure_twf THEN 1 ELSE 0 END) * 100.0
             / COUNT(*), 3)                            AS rate_pct
FROM machines
UNION ALL
SELECT 'HDF — Heat Dissipation Failure',
       SUM(CASE WHEN failure_hdf THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN failure_hdf THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 3)
FROM machines
UNION ALL
SELECT 'PWF — Power Failure',
       SUM(CASE WHEN failure_pwf THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN failure_pwf THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 3)
FROM machines
UNION ALL
SELECT 'OSF — Overstrain Failure',
       SUM(CASE WHEN failure_osf THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN failure_osf THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 3)
FROM machines
UNION ALL
SELECT 'RNF — Random Failure',
       SUM(CASE WHEN failure_rnf THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN failure_rnf THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 3)
FROM machines
ORDER BY event_count DESC;


-- ── 2.3  Wear stage risk profile ────────────────────────────────────────────
-- Business question: "At what tool wear level do failures spike?"
-- Technique: GROUP BY + CASE bucketing + percentage

SELECT
    wear_stage,
    COUNT(*)                                             AS readings,
    SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)    AS failures,
    ROUND(
        SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS failure_rate_pct,
    ROUND(AVG(torque_nm), 1)                             AS avg_torque,
    ROUND(AVG(tool_wear_min), 0)                         AS avg_wear_min,
    ROUND(AVG(power_w), 1)                               AS avg_power_w
FROM machines
GROUP BY wear_stage
ORDER BY
    CASE wear_stage
        WHEN 'early' THEN 1
        WHEN 'mid'   THEN 2
        WHEN 'late'  THEN 3
        ELSE 4
    END;


-- ── 2.4  Operating envelope analysis — where do failures occur? ──────────────
-- Business question: "What combination of conditions causes failures?"
-- Technique: multi-dimensional bucketing, identifying the failure zone

WITH bucketed AS (
    SELECT
        machine_failure,
        CASE
            WHEN torque_nm < 30                          THEN 'Low (<30 Nm)'
            WHEN torque_nm BETWEEN 30 AND 50             THEN 'Normal (30–50 Nm)'
            ELSE                                              'High (>50 Nm)'
        END                                              AS torque_band,
        CASE
            WHEN rotational_speed_rpm < 1400             THEN 'Low (<1400 rpm)'
            WHEN rotational_speed_rpm BETWEEN 1400 AND 1700 THEN 'Normal (1400–1700)'
            ELSE                                              'High (>1700 rpm)'
        END                                              AS speed_band
    FROM machines
)
SELECT
    torque_band,
    speed_band,
    COUNT(*)                                             AS reading_count,
    SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)    AS failure_count,
    ROUND(
        SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS failure_rate_pct
FROM bucketed
GROUP BY torque_band, speed_band
ORDER BY failure_rate_pct DESC;


-- ── 2.5  Percentile analysis of failure conditions ──────────────────────────
-- Business question: "What are the threshold values above which failure risk jumps?"
-- Technique: window functions for percentile ranking

WITH ranked AS (
    SELECT
        udi,
        machine_failure,
        torque_nm,
        rotational_speed_rpm,
        tool_wear_min,
        power_w,
        temp_diff_k,
        NTILE(10) OVER (ORDER BY torque_nm)              AS torque_decile,
        NTILE(10) OVER (ORDER BY tool_wear_min)          AS wear_decile,
        NTILE(10) OVER (ORDER BY power_w)                AS power_decile
    FROM machines
)
SELECT
    torque_decile,
    COUNT(*)                                             AS reading_count,
    ROUND(MIN(torque_nm), 1)                             AS torque_min,
    ROUND(MAX(torque_nm), 1)                             AS torque_max,
    SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END)    AS failures,
    ROUND(
        SUM(CASE WHEN machine_failure THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2
    )                                                    AS failure_rate_pct
FROM ranked
GROUP BY torque_decile
ORDER BY torque_decile;


-- ── 2.6  Top failure risk machines (CTE + window function combo) ─────────────
-- Business question: "Which individual machines are closest to failing?"
-- Technique: CTE + composite risk score + LEAD to show next expected failure

WITH risk_scored AS (
    SELECT
        udi,
        product_id,
        machine_type,
        tool_wear_min,
        torque_nm,
        rotational_speed_rpm,
        power_w,
        temp_diff_k,
        machine_failure,
        wear_torque_product,
        -- Composite risk score (normalised 0–100)
        ROUND(
            (tool_wear_min / 253.0 * 40)          -- wear contributes 40 points
            + (CASE WHEN torque_nm > 50 THEN 30
                    WHEN torque_nm > 40 THEN 15
                    ELSE 0 END)                    -- high torque contributes 30
            + (CASE WHEN temp_diff_k < 8.6 THEN 20
                    ELSE 0 END)                    -- low temp diff contributes 20
            + (CASE WHEN power_w > 8000 OR power_w < 3500
                    THEN 10 ELSE 0 END)            -- power out of range: 10
        , 1)                                                 AS risk_score
    FROM machines
    WHERE NOT machine_failure  -- only look at machines still running
),
ranked AS (
    SELECT
        *,
        RANK() OVER (ORDER BY risk_score DESC)           AS risk_rank,
        -- How many machines have similar wear level
        COUNT(*) OVER (
            PARTITION BY machine_type
            ORDER BY tool_wear_min DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                AS cumulative_high_wear
    FROM risk_scored
)
SELECT
    risk_rank,
    udi,
    product_id,
    machine_type,
    tool_wear_min,
    ROUND(torque_nm, 1)                                  AS torque_nm,
    ROUND(power_w, 0)                                    AS power_w,
    ROUND(temp_diff_k, 1)                                AS temp_diff_k,
    risk_score,
    CASE
        WHEN risk_score >= 70                            THEN 'Immediate attention'
        WHEN risk_score >= 50                            THEN 'Schedule maintenance'
        WHEN risk_score >= 30                            THEN 'Monitor closely'
        ELSE                                                  'Normal operation'
    END                                                  AS recommendation
FROM ranked
WHERE risk_rank <= 15
ORDER BY risk_rank;


-- ── 2.7  Failure rate trend by UDI (time proxy) using moving average ─────────
-- Business question: "Is the failure rate getting better or worse over time?"
-- Technique: window function moving average over ordered sequence

SELECT
    udi,
    machine_failure,
    ROUND(
        AVG(CASE WHEN machine_failure THEN 1.0 ELSE 0.0 END) OVER (
            ORDER BY udi
            ROWS BETWEEN 499 PRECEDING AND CURRENT ROW
        ) * 100, 2
    )                                                    AS rolling_500_failure_rate_pct,
    ROUND(
        AVG(CASE WHEN machine_failure THEN 1.0 ELSE 0.0 END) OVER (
            ORDER BY udi
            ROWS BETWEEN 999 PRECEDING AND CURRENT ROW
        ) * 100, 2
    )                                                    AS rolling_1000_failure_rate_pct
FROM machines
WHERE udi % 50 = 0  -- sample every 50th row for readability
ORDER BY udi;
