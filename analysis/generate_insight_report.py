"""
generate_insight_report.py
--------------------------
Reads the fleet CSVs (real or sample) and generates a professional
one-page PDF insight narrative — the kind of document you hand to a client.
"""

import argparse
import os
import pandas as pd
import numpy as np
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, 
                                TableStyle, HRFlowable, KeepTogether)

from reportlab.lib import HexColor

# ── Brand colours ─────────────────────────────────────────────────────────────
TEAL      = HexColor("#1D9E75")
PURPLE    = HexColor("#7F77DD")
CORAL     = HexColor("#D85A30")
AMBER     = HexColor("#BA7517")
DARK      = HexColor("#2C2C2A")
MID_GRAY  = HexColor("#5F5E5A")
LIGHT_GRAY= HexColor("#F1EFE8")
RED       = HexColor("#E24B4A")
GREEN     = HexColor("#1D9E75")
PAGE_W, PAGE_H = A4

