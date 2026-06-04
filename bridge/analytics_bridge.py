"""
analytics_bridge.py
-------------------
Subscribes to all fleet MQTT topics and writes structured data into InfluxDB.
This is the data pipeline component — the bridge between raw device messages
and the analytics layer (Grafana / Power BI / Pandas).

Subscribes to:
  fleet/+/telemetry  → influx measurement: device_telemetry
  fleet/+/status     → influx measurement: device_status
  fleet/+/events     → influx measurement: device_events

Run:
  python analytics_bridge.py
  python analytics_bridge.py --broker-host 192.168.1.10 --influx-url http://localhost:8086
"""

import json
import argparse
import time
import sys
import os
import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("analytics_bridge")

# ── InfluxDB config (matches docker-compose.yml) ──────────────────────────────

INFLUX_URL   = "http://localhost:8086"
INFLUX_TOKEN = "fleet-super-secret-token-001"
INFLUX_ORG   = "fleet-org"
INFLUX_BUCKET = "fleet-telemetry"


class AnalyticsBridge:

    def __init__(self, broker_host: str, broker_port: int, influx_url: str):
        self.broker_host = broker_host
        self.broker_port = broker_port

        # InfluxDB write client
        self._influx = InfluxDBClient(
            url=influx_url,
            token=INFLUX_TOKEN,
            org=INFLUX_ORG,
        )
        self._write_api = self._influx.write_api(write_options=SYNCHRONOUS)

        # Stats
        self.messages_received = 0
        self.messages_written = 0
        self.parse_errors = 0

        # MQTT client (plain paho — bridge doesn't need offline queuing)
        self._mqtt = mqtt.Client(client_id="analytics_bridge", protocol=mqtt.MQTTv311)
        self._mqtt.on_connect    = self._on_connect
        self._mqtt.on_message    = self._on_message
        self._mqtt.on_disconnect = self._on_disconnect

    # ── MQTT callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("Connected to broker — subscribing to fleet/#")
            client.subscribe("fleet/#", qos=1)
        else:
            log.error(f"Broker connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        log.warning(f"Disconnected from broker (rc={rc}) — will reconnect automatically")

    def _on_message(self, client, userdata, msg):
        self.messages_received += 1
        try:
            self._route_message(msg.topic, msg.payload)
        except Exception as e:
            self.parse_errors += 1
            log.warning(f"Failed to process {msg.topic}: {e}")

    # ── Message routing ───────────────────────────────────────────────────────

    def _route_message(self, topic: str, raw: bytes):
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "fleet":
            return

        _, device_id, msg_type = parts
        data = json.loads(raw.decode("utf-8"))

        if msg_type == "telemetry":
            self._write_telemetry(device_id, data)
        elif msg_type == "status":
            self._write_status(device_id, data)
        elif msg_type == "events":
            self._write_event(device_id, data)

    # ── InfluxDB writers ──────────────────────────────────────────────────────

    def _write_telemetry(self, device_id: str, d: dict):
        point = (
            Point("device_telemetry")
            .tag("device_id",   device_id)
            .tag("device_type", d.get("device_type", "unknown"))
            .tag("location",    d.get("location", "unknown"))
            .tag("anomaly",     str(d.get("anomaly", False)))
            .field("cpu_percent",    float(d["cpu_percent"]))
            .field("ram_percent",    float(d["ram_percent"]))
            .field("temperature_c",  float(d["temperature_c"]))
            .field("signal_dbm",     int(d["signal_dbm"]))
            .field("uptime_s",       int(d["uptime_s"]))
            .field("publish_count",  int(d.get("publish_count", 0)))
            .time(d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                  WritePrecision.NS)
        )
        self._write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        self.messages_written += 1
        log.debug(f"telemetry written: {device_id} cpu={d['cpu_percent']}%")

    def _write_status(self, device_id: str, d: dict):
        point = (
            Point("device_status")
            .tag("device_id",   device_id)
            .tag("device_type", d.get("device_type", "unknown"))
            .tag("location",    d.get("location", "unknown"))
            .field("uptime_s",        int(d.get("uptime_s", 0)))
            .field("publish_count",   int(d.get("publish_count", 0)))
            .field("error_count",     int(d.get("error_count", 0)))
            .field("queue_depth",     int(d.get("queue_depth", 0)))
            .field("inflight_count",  int(d.get("inflight_count", 0)))
            .field("is_connected",    int(d.get("is_connected", False)))
            .field("reconnect_count", int(d.get("reconnect_count", 0)))
            .time(d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                  WritePrecision.NS)
        )
        self._write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        self.messages_written += 1
        log.debug(f"status written: {device_id} queue={d.get('queue_depth', 0)}")

    def _write_event(self, device_id: str, d: dict):
        point = (
            Point("device_events")
            .tag("device_id",   device_id)
            .tag("device_type", d.get("device_type", "unknown"))
            .tag("location",    d.get("location", "unknown"))
            .tag("event",       d.get("event", "unknown"))
            .field("firmware_version", d.get("firmware_version", "unknown"))
            .field("event_count", 1)
            .time(d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                  WritePrecision.NS)
        )
        self._write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        self.messages_written += 1
        log.info(f"event written: {device_id} event={d.get('event')}")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        log.info(f"Connecting to broker at {self.broker_host}:{self.broker_port}")
        self._mqtt.connect(self.broker_host, self.broker_port, keepalive=60)
        self._mqtt.loop_start()

        log.info("Bridge running — press Ctrl+C to stop")
        try:
            while True:
                time.sleep(30)
                log.info(
                    f"Stats — received={self.messages_received} "
                    f"written={self.messages_written} "
                    f"errors={self.parse_errors}"
                )
        except KeyboardInterrupt:
            log.info("Stopping bridge...")
        finally:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
            self._influx.close()
            log.info("Bridge stopped cleanly")


def main():
    parser = argparse.ArgumentParser(description="MQTT → InfluxDB analytics bridge")
    parser.add_argument("--broker-host", default="localhost")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--influx-url", default=INFLUX_URL)
    args = parser.parse_args()

    bridge = AnalyticsBridge(
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        influx_url=args.influx_url,
    )
    bridge.run()


if __name__ == "__main__":
    main()
