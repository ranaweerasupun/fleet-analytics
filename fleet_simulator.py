"""
fleet_simulator.py
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

if __name__ == "__main__":
    main()


