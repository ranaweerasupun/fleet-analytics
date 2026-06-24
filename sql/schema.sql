-- schema.sql
-- Fleet Analytics + AI4I Predictive Maintenance database schema
-- Compatible with: PostgreSQL, DuckDB, SQLite (with minor dialect changes noted)
--
-- Two domains in one schema:
--   1. fleet_*  — IoT device telemetry (from the fleet analytics project)
--   2. machines — Industrial sensor data (from AI4I predictive maintenance)
--
-- This demonstrates SQL across two realistic IoT/industrial domains.

-- ── Fleet domain ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fleet_telemetry (
    id              INTEGER PRIMARY KEY,
    timestamp       TIMESTAMP NOT NULL,
    device_id       VARCHAR(20) NOT NULL,
    device_type     VARCHAR(20) NOT NULL,
    location        VARCHAR(30) NOT NULL,
    cpu_pct         DECIMAL(5,1),
    ram_pct         DECIMAL(5,1),
    temperature_c   DECIMAL(6,2),
    signal_dbm      INTEGER,
    uptime_s        INTEGER,
    is_anomaly      BOOLEAN DEFAULT FALSE,
    signal_quality  VARCHAR(10),
    temp_status     VARCHAR(10),
    cpu_status      VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS fleet_status (
    device_id           VARCHAR(20) PRIMARY KEY,
    device_type         VARCHAR(20) NOT NULL,
    location            VARCHAR(30) NOT NULL,
    uptime_s            INTEGER,
    uptime_hours        DECIMAL(8,2),
    messages_published  INTEGER,
    error_count         INTEGER,
    queue_depth         INTEGER,
    reconnect_count     INTEGER,
    connection_status   VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS fleet_events (
    id              INTEGER PRIMARY KEY,
    device_id       VARCHAR(20) NOT NULL,
    device_type     VARCHAR(20) NOT NULL,
    location        VARCHAR(30) NOT NULL,
    event_type      VARCHAR(30) NOT NULL,
    firmware_version VARCHAR(10),
    event_timestamp TIMESTAMP
);

-- ── Industrial machine domain ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS machines (
    udi                     INTEGER PRIMARY KEY,
    product_id              VARCHAR(10) NOT NULL,
    machine_type            VARCHAR(5)  NOT NULL,   -- L / M / H
    air_temp_k              DECIMAL(6,1),
    process_temp_k          DECIMAL(6,1),
    rotational_speed_rpm    INTEGER,
    torque_nm               DECIMAL(6,1),
    tool_wear_min           INTEGER,
    machine_failure         BOOLEAN NOT NULL,
    failure_twf             BOOLEAN DEFAULT FALSE,  -- Tool Wear Failure
    failure_hdf             BOOLEAN DEFAULT FALSE,  -- Heat Dissipation Failure
    failure_pwf             BOOLEAN DEFAULT FALSE,  -- Power Failure
    failure_osf             BOOLEAN DEFAULT FALSE,  -- Overstrain Failure
    failure_rnf             BOOLEAN DEFAULT FALSE,  -- Random Failure
    -- Derived features (added during cleaning)
    power_w                 DECIMAL(8,2),
    temp_diff_k             DECIMAL(6,2),
    wear_torque_product     DECIMAL(10,1),
    speed_torque_product    DECIMAL(10,0),
    wear_stage              VARCHAR(10)             -- early / mid / late
);
