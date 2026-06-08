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

   FEATURES = ["CPU %", "RAM %", "Temperature (°C)", "Signal (dBm)"]

   def __init__(self, df: pd.DataFrame):
      self.data = df.copy()
      self._validate()

   def _validate(self):
      missing = [f for f in self.FEATURES if f not in self.df.columns]
      if missing:
         raise ValueError(f"Missing columns: {missing}")
      if "Device ID" not in self.df.columns:
         raise ValueError("DataFrame must have a 'Device ID' column")

   def zscore(self, threshold: float = 3.0) -> pd.DataFrame:

      results = []

      for device_id, group in self.df.groupby("Device ID"):
            group = group.copy()
            z_scores = pd.DataFrame(index=group.index)

            for feature in self.FEATURES:
                col = group[feature].dropna()
                if len(col) < 10:
                    z_scores[f"z_{feature}"] = 0.0
                    continue
                z = np.abs(stats.zscore(col, nan_policy="omit"))
                z_scores[f"z_{feature}"] = pd.Series(z, index=col.index)

            # Max Z across all features per row
            group["max_zscore"] = z_scores.max(axis=1)
            group["zscore_anomaly"] = group["max_zscore"] > threshold

            # Which feature triggered the flag
            group["zscore_trigger"] = z_scores.idxmax(axis=1).str.replace("z_", "")
            group["zscore_trigger"] = group["zscore_trigger"].where(
                group["zscore_anomaly"], other=""
            )
            results.append(group)

      return pd.concat(results).sort_index()
   
   def iqr(self, multiplier: float = 1.5) -> pd.DataFrame:
      pass
   def isolation_forest(self, contamination: float = 0.02) -> pd.DataFrame:
      pass
   

