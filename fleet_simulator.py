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

