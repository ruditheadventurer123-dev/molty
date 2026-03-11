"""
Molty Royale AI Bot — Combat Predictor (ML Model)
GradientBoosting REGRESSOR for combat outcome prediction.
Uses survival scores instead of binary win/lose — can learn from ALL games.
Falls back to heuristic calculation when insufficient training data.
"""

import os
import numpy as np
from typing import Optional
from src.config import MODELS_DIR, ensure_data_dirs
from src.ml.feature_engine import extract_combat_features

MODEL_PATH = os.path.join(MODELS_DIR, "combat_predictor.pkl")
MIN_TRAINING_SAMPLES = 10  # Lowered — regression works with less data


class CombatPredictor:
    """ML model for predicting combat win probability using regression."""

    def __init__(self):
        self.model = None
        self.is_trained = False
        self.accuracy = 0.0  # R² score for regression
        self.training_samples = 0
        self._load_model()

    def _load_model(self):
        """Load saved model if exists."""
        if os.path.exists(MODEL_PATH):
            try:
                import joblib
                self.model = joblib.load(MODEL_PATH)
                self.is_trained = True
            except Exception:
                self.model = None
                self.is_trained = False

    def save_model(self):
        """Save model to disk."""
        if self.model:
            try:
                ensure_data_dirs()
                import joblib
                joblib.dump(self.model, MODEL_PATH)
            except Exception as e:
                print(f"Warning: Could not save model: {e}")

    def train(self, X: np.ndarray, y: np.ndarray) -> float:
        """
        Train the combat predictor using REGRESSION (not classification).
        y = float scores 0.0-1.0 (survival/combat scores), not binary labels.
        Returns R² score (can be negative if model is poor).
        """
        if len(X) < MIN_TRAINING_SAMPLES:
            return 0.0

        try:
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.model_selection import cross_val_score

            self.model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                min_samples_split=3,
                random_state=42,
            )

            # Cross-validation R² score
            if len(X) >= 10:
                n_splits = min(5, len(X) // 3)
                if n_splits >= 2:
                    scores = cross_val_score(self.model, X, y, cv=n_splits, scoring="r2")
                    self.accuracy = max(0.0, scores.mean())  # R² can be negative
                else:
                    self.accuracy = 0.0

            # Train on full data
            self.model.fit(X, y)
            self.is_trained = True
            self.training_samples = len(X)
            self.save_model()

            return self.accuracy

        except Exception as e:
            print(f"Warning: Model training failed: {e}")
            self.is_trained = False
            return 0.0

    def predict_win_probability(self, our_stats: dict, enemy_stats: dict) -> Optional[float]:
        """
        Predict win probability using ML model.
        Now uses regression — returns predicted score 0.0-1.0.
        Higher score = more likely favorable combat outcome.
        """
        if not self.is_trained or not self.model:
            return None

        try:
            features = extract_combat_features(our_stats, enemy_stats).reshape(1, -1)
            # Regression prediction — clamp to [0, 1]
            prediction = float(self.model.predict(features)[0])
            return max(0.0, min(1.0, prediction))
        except Exception:
            return None


# Singleton instance
predictor = CombatPredictor()
