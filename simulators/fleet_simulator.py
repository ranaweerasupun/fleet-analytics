"""
fleet_simulator.py
------------------
Launches multiple device simulators concurrently using threads.
Each device runs independently with its own robmqtt client and SQLite store.

Usage:
  python fleet_simulator.py --count 15
  python fleet_simulator.py --count 20 --broker-host 192.168.1.10
"""

import argparse
import threading
import random
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from device_simulator import DeviceSimulator, DEVICE_PROFILES

DEVICE_TYPES = list(DEVICE_PROFILES.keys())

# Fixed distribution across types to mimic a real fleet
TYPE_WEIGHTS = {
    "sensor":     0.45,
    "gateway":    0.20,
    "camera":     0.20,
    "controller": 0.15,
}


def pick_type() -> str:
    r = random.random()
    cumulative = 0.0
    for t, w in TYPE_WEIGHTS.items():
        cumulative += w
        if r < cumulative:
            return t
    return "sensor"


def run_device(device_id: str, device_type: str, broker_host: str, broker_port: int):
    sim = DeviceSimulator(device_id, device_type, broker_host, broker_port)
    # Stagger startup by up to 3s so the broker isn't hit simultaneously
    time.sleep(random.uniform(0, 3))
    sim.run()


def main():
    parser = argparse.ArgumentParser(description="Launch a simulated fleet of edge devices")
    parser.add_argument("--count", type=int, default=15, help="Number of devices to simulate")
    parser.add_argument("--broker-host", default="localhost")
    parser.add_argument("--broker-port", type=int, default=1883)
    args = parser.parse_args()

    print(f"Starting fleet of {args.count} devices → {args.broker_host}:{args.broker_port}")
    print("Press Ctrl+C to stop all devices\n")

    threads = []
    for i in range(1, args.count + 1):
        device_id = f"device_{i:03d}"
        device_type = pick_type()
        t = threading.Thread(
            target=run_device,
            args=(device_id, device_type, args.broker_host, args.broker_port),
            daemon=True,
            name=device_id,
        )
        threads.append(t)
        t.start()

    try:
        while True:
            alive = sum(1 for t in threads if t.is_alive())
            print(f"\r[fleet] {alive}/{args.count} devices running", end="", flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n\nShutting down fleet...")


if __name__ == "__main__":
    main()
