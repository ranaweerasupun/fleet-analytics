"""
device_simulator.py
-------------------
Simulates a single edge IoT device publishing telemetry to the fleet broker.
Uses robmqtt for resilient delivery — handles broker outages automatically.

Topics published:
  fleet/{device_id}/telemetry  — CPU, RAM, temperature, signal strength
  fleet/{device_id}/status     — uptime, queue depth, connection state
  fleet/{device_id}/events     — discrete events (boot, alert, etc.)

Run one device:
  python device_simulator.py --device-id device_001 --device-type sensor

Run 15 devices at once:
  python fleet_simulator.py --count 15
"""

import json
import time
import random
import argparse
import threading
import math
from datetime import datetime, timezone
from robmqtt import ProductionMQTTClient

# ── Device type profiles ────────────────────────────────────────────────────
# Each profile defines realistic operating ranges for that device type.

DEVICE_PROFILES = {
    "sensor": {
        "cpu_base": 8,
        "cpu_variance": 6,
        "ram_base": 35,
        "ram_variance": 10,
        "temp_base": 42.0,
        "temp_variance": 5.0,
        "signal_base": -62,
        "signal_variance": 8,
        "telemetry_interval": 10,
        "failure_rate": 0.03,
    },
    "gateway": {
        "cpu_base": 28,
        "cpu_variance": 18,
        "ram_base": 55,
        "ram_variance": 20,
        "temp_base": 52.0,
        "temp_variance": 8.0,
        "signal_base": -55,
        "signal_variance": 5,
        "telemetry_interval": 5,
        "failure_rate": 0.01,
    },
    "camera": {
        "cpu_base": 65,
        "cpu_variance": 20,
        "ram_base": 70,
        "ram_variance": 15,
        "temp_base": 61.0,
        "temp_variance": 10.0,
        "signal_base": -58,
        "signal_variance": 6,
        "telemetry_interval": 5,
        "failure_rate": 0.02,
    },
    "controller": {
        "cpu_base": 18,
        "cpu_variance": 12,
        "ram_base": 45,
        "ram_variance": 12,
        "temp_base": 48.0,
        "temp_variance": 6.0,
        "signal_base": -60,
        "signal_variance": 7,
        "telemetry_interval": 8,
        "failure_rate": 0.015,
    },
}

# ── Location map ─────────────────────────────────────────────────────────────

LOCATIONS = [
    "warehouse_a", "warehouse_b", "factory_floor_1",
    "factory_floor_2", "office_block", "server_room",
    "loading_bay", "outdoor_yard",
]


class DeviceSimulator:
    """
    Simulates a single edge device. Publishes telemetry on a regular interval.
    Occasionally simulates network drops to exercise the offline queue.
    """

    def __init__(self, device_id: str, device_type: str, broker_host: str, broker_port: int):
        self.device_id = device_id
        self.device_type = device_type
        self.profile = DEVICE_PROFILES.get(device_type, DEVICE_PROFILES["sensor"])
        self.location = random.choice(LOCATIONS)
        self.boot_time = time.time()
        self.publish_count = 0
        self.error_count = 0
        self._running = False

        # Slow drift for realistic long-term sensor trends
        self._drift_phase = random.uniform(0, 2 * math.pi)

        self.client = ProductionMQTTClient(
            client_id=f"fleet_{device_id}",
            broker_host=broker_host,
            broker_port=broker_port,
            max_queue_size=500,
            db_path=f"./data/{device_id}.db",
            min_backoff=2,
            max_backoff=30,
            log_dir=f"./logs/{device_id}",
        )

    # ── Telemetry generation ─────────────────────────────────────────────────

    def _cpu(self) -> float:
        p = self.profile
        drift = 5 * math.sin(time.time() / 300 + self._drift_phase)
        noise = random.gauss(0, p["cpu_variance"] / 2)
        value = p["cpu_base"] + drift + noise
        return round(max(1.0, min(99.0, value)), 1)

    def _ram(self) -> float:
        p = self.profile
        noise = random.gauss(0, p["ram_variance"] / 3)
        value = p["ram_base"] + noise
        return round(max(5.0, min(99.0, value)), 1)

    def _temperature(self) -> float:
        p = self.profile
        drift = 3 * math.sin(time.time() / 600 + self._drift_phase)
        noise = random.gauss(0, p["temp_variance"] / 3)
        value = p["temp_base"] + drift + noise
        return round(max(20.0, min(95.0, value)), 2)

    def _signal(self) -> int:
        p = self.profile
        noise = random.randint(-p["signal_variance"], p["signal_variance"])
        return p["signal_base"] + noise

    def _uptime_seconds(self) -> int:
        return int(time.time() - self.boot_time)

    def _is_anomaly(self) -> bool:
        return random.random() < self.profile["failure_rate"]

    # ── Publish helpers ───────────────────────────────────────────────────────

    def _publish_telemetry(self):
        payload = {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "location": self.location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cpu_percent": self._cpu(),
            "ram_percent": self._ram(),
            "temperature_c": self._temperature(),
            "signal_dbm": self._signal(),
            "uptime_s": self._uptime_seconds(),
            "publish_count": self.publish_count,
        }

        # Inject an anomaly occasionally for interesting analytics
        if self._is_anomaly():
            payload["cpu_percent"] = round(random.uniform(88, 99), 1)
            payload["temperature_c"] = round(random.uniform(78, 92), 2)
            payload["anomaly"] = True
            self.error_count += 1

        self.client.publish(
            topic=f"fleet/{self.device_id}/telemetry",
            payload=json.dumps(payload),
            qos=1,
            priority=5,
        )
        self.publish_count += 1

    def _publish_status(self):
        stats = self.client.get_statistics()
        payload = {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "location": self.location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_s": self._uptime_seconds(),
            "publish_count": self.publish_count,
            "error_count": self.error_count,
            "queue_depth": stats.get("offline_queue_size", 0),
            "inflight_count": stats.get("inflight_count", 0),
            "is_connected": stats.get("is_connected", False),
            "reconnect_count": stats.get("reconnect_count", 0),
        }
        self.client.publish(
            topic=f"fleet/{self.device_id}/status",
            payload=json.dumps(payload),
            qos=1,
            priority=8,
        )

    def _publish_boot_event(self):
        payload = {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "location": self.location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "boot",
            "firmware_version": "1.4.2",
        }
        self.client.publish(
            topic=f"fleet/{self.device_id}/events",
            payload=json.dumps(payload),
            qos=2,
            priority=10,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        import os
        os.makedirs(f"./data", exist_ok=True)
        os.makedirs(f"./logs/{self.device_id}", exist_ok=True)

        self.client.connect()
        self.client.start()
        self._publish_boot_event()

        self._running = True
        interval = self.profile["telemetry_interval"]
        status_every = max(1, 60 // interval)  # publish status ~every 60s
        tick = 0

        print(f"[{self.device_id}] Started — type={self.device_type} location={self.location}")

        try:
            while self._running:
                self._publish_telemetry()
                if tick % status_every == 0:
                    self._publish_status()
                tick += 1
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.client.stop()
            print(f"[{self.device_id}] Stopped after {self.publish_count} publishes")


def main():
    parser = argparse.ArgumentParser(description="Simulate a single fleet edge device")
    parser.add_argument("--device-id", default="device_001")
    parser.add_argument("--device-type", choices=list(DEVICE_PROFILES.keys()), default="sensor")
    parser.add_argument("--broker-host", default="localhost")
    parser.add_argument("--broker-port", type=int, default=1883)
    args = parser.parse_args()

    sim = DeviceSimulator(
        device_id=args.device_id,
        device_type=args.device_type,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
    )
    sim.run()


if __name__ == "__main__":
    main()
