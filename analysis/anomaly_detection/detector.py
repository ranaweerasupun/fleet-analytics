"""
detector.py
-----------
Three statistical anomaly detection methods applied to IoT fleet telemetry.
Each method has different strengths — understanding when to use which one
is the actual data analyst skill I am demonstrating here.

Methods implemented:
  1. Z-score          — detects outliers based on standard deviations from mean
  2. IQR              — detects outliers based on interquartile range (robust to skew)
  3. Isolation Forest — ML-based, detects anomalies in multiple dimensions at once

"""


import pandas as pd
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from typing import Tuple

class AnomalyDetector:
   def zscore(self, threshold: float = 3.0) -> pd.DataFrame:
      pass
   def iqr(self, multiplier: float = 1.5) -> pd.DataFrame:
      pass
   def isolation_forest(self, contamination: float = 0.02) -> pd.DataFrame:
      pass
   

