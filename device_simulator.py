"""
device_simulator.py
-------------------
Simulates a single edge IoT device publishing telemetry to the fleet broker.
Uses robmqtt for resilient delivery — handles broker outages automatically.

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

