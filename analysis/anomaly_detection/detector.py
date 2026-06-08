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
      results = []

      for device_id, group in self.df.groupby("Device ID"):
         group = group.copy()
         flags = pd.DataFrame(index=group.index)

         for feature in self.FEATURES:
            col = group[feature].dropna()
            if len(col) < 10:
               flags[f"iqr_{feature}"] = False
               continue

            q1  = col.quantile(0.25)
            q3  = col.quantile(0.75)
            iqr = q3 - q1
            lo  = q1 - multiplier * iqr
            hi  = q3 + multiplier * iqr

            flags[f"iqr_{feature}"] = (col < lo) | (col > hi)

            # Store bounds for explainability
            group[f"iqr_lo_{feature}"] = lo
            group[f"iqr_hi_{feature}"] = hi

         group["iqr_anomaly"] = flags.any(axis=1)
         group["iqr_trigger"] = flags.idxmax(axis=1).str.replace("iqr_", "")
         group["iqr_trigger"] = group["iqr_trigger"].where(
            group["iqr_anomaly"], other=""
         )
         results.append(group)

      return pd.concat(results).sort_index()




   def isolation_forest(self, contamination: float = 0.02) -> pd.DataFrame:

      results = []
      scaler = StandardScaler()

      for device_id, group in self.df.groupby("Device ID"):
         group = group.copy()
         feature_data = group[self.FEATURES].dropna()

         if len(feature_data) < 20:
            group["iforest_anomaly"] = False
            group["iforest_score"] = 0.0
            results.append(group)
            continue

         # Scale features so no single dimension dominates
         X = scaler.fit_transform(feature_data)

         model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
         )
         preds  = model.fit_predict(X)
         scores = model.score_samples(X)

         # -1 = anomaly, 1 = normal (sklearn convention)
         group.loc[feature_data.index, "iforest_anomaly"] = preds == -1
         group.loc[feature_data.index, "iforest_score"]   = scores

         # Anomaly score: invert so higher = more anomalous
         group["iforest_score"] = -group["iforest_score"]
         group["iforest_anomaly"] = group["iforest_anomaly"].fillna(False)

         results.append(group)

      return pd.concat(results).sort_index()
   

   def run_all(self) -> pd.DataFrame:
        """
        Run all three methods and return a single DataFrame with all flags.
        Also adds a 'consensus_anomaly' column — True if 2+ methods agree.
        Agreement across methods gives higher confidence than any single method alone.
        """
        print("Running Z-score detection...")
        df_z = self.zscore()

        print("Running IQR detection...")
        df_iqr = self.iqr()

        print("Running Isolation Forest...")
        df_if = self.isolation_forest()

        # Merge results — all three ran on same df so index aligns
        result = df_z.copy()
        result["iqr_anomaly"]     = df_iqr["iqr_anomaly"]
        result["iqr_trigger"]     = df_iqr["iqr_trigger"]
        result["iforest_anomaly"] = df_if["iforest_anomaly"]
        result["iforest_score"]   = df_if["iforest_score"]

        # Consensus: flagged by at least 2 of 3 methods
        result["method_count"] = (
            result["zscore_anomaly"].astype(int) +
            result["iqr_anomaly"].astype(int) +
            result["iforest_anomaly"].astype(int)
        )
        result["consensus_anomaly"] = result["method_count"] >= 2

        print("Done.\n")
        return result


@staticmethod
def summarise(df: pd.DataFrame) -> pd.DataFrame:
   """
   Returns a per-device summary of anomaly counts by method.
   Useful for the insight report and Grafana annotations.
   """
   return (
      df.groupby(["Device ID", "Device Type", "Location"])
      .agg(
         total_readings    = ("CPU %", "count"),
         zscore_anomalies  = ("zscore_anomaly",  "sum"),
         iqr_anomalies     = ("iqr_anomaly",     "sum"),
         iforest_anomalies = ("iforest_anomaly", "sum"),
         consensus_anomalies = ("consensus_anomaly", "sum"),
         avg_cpu           = ("CPU %",            "mean"),
         max_cpu           = ("CPU %",            "max"),
         avg_temp          = ("Temperature (°C)", "mean"),
         max_temp          = ("Temperature (°C)", "max"),
      )
      .round(1)
      .reset_index()
      .sort_values("consensus_anomalies", ascending=False)
   )

