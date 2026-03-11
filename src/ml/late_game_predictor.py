"""
Molty Royale AI Bot — Late Game ML Predictor (Upgrade 4)
GradientBoosting classifier that predicts best action in crowded late-game:
  "attack" | "flee" | "heal"

Trains on recorded late-game decisions correlated with game outcomes.
Falls back to rule-based logic when no model/data available.
"""

import os
import pickle
import numpy as np
from typing import Optional
from src.models import GameState
from src.config import MODELS_DIR, ensure_data_dirs
from src import logger


# Feature names for late-game prediction (15 features)
LATE_GAME_FEATURE_NAMES = [
    "our_hp_pct",           # 0: Our HP / max HP
    "our_ep",               # 1: Our EP
    "our_weapon_tier",      # 2: Our weapon tier (0-6)
    "our_kill_count",       # 3: Kills so far
    "agents_in_region",     # 4: Number of hostile agents in current region
    "weakest_enemy_hp",     # 5: HP of weakest enemy in region
    "strongest_enemy_atk",  # 6: ATK of strongest enemy in region
    "our_healing_items",    # 7: Number of healing items we have
    "total_enemy_healing",  # 8: Sum of visible enemy healing potential
    "avg_enemy_hp",         # 9: Average HP of enemies in region
    "turn_progress",        # 10: Turn / 56 (game progress 0-1)
    "safe_neighbors",       # 11: Count of safe connected regions
    "region_connections",   # 12: Total connections from current region
    "our_damage_potential", # 13: Our ATK + weapon bonus
    "threat_level",         # 14: Sum of enemy ATK in region / our HP
]

MODEL_FILENAME = "late_game_predictor.pkl"
ACTION_LABELS = {"attack": 0, "flee": 1, "heal": 2}
ACTION_NAMES = {0: "attack", 1: "flee", 2: "heal"}


class LateGamePredictor:
    """ML predictor for late-game fight/flee/heal decisions."""

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load trained model from disk if available."""
        ensure_data_dirs()
        model_path = os.path.join(MODELS_DIR, MODEL_FILENAME)
        if os.path.exists(model_path):
            try:
                with open(model_path, "rb") as f:
                    self.model = pickle.load(f)
                logger.info("Late game ML model loaded", logger.SYM_GEAR)
            except Exception:
                self.model = None

    def has_model(self) -> bool:
        return self.model is not None

    def predict(self, features: np.ndarray) -> tuple:
        """
        Predict best action from features.
        Returns (action_name: str, confidence: float).
        """
        if not self.has_model():
            return self._rule_based_fallback(features)

        try:
            proba = self.model.predict_proba(features.reshape(1, -1))[0]
            best_idx = int(np.argmax(proba))
            confidence = float(proba[best_idx])
            return ACTION_NAMES[best_idx], confidence
        except Exception:
            return self._rule_based_fallback(features)

    def _rule_based_fallback(self, features: np.ndarray) -> tuple:
        """
        Rule-based fallback when no ML model available.
        Uses feature values to make a decision.
        """
        our_hp_pct = features[0]
        our_ep = features[1]
        agents_in_region = features[4]
        weakest_enemy_hp = features[5]
        our_healing_items = features[7]
        safe_neighbors = features[11]
        our_damage = features[13]

        # Critical HP → heal if possible
        if our_hp_pct < 0.4 and our_healing_items > 0:
            return "heal", 0.85

        # Low HP + can escape → flee
        if our_hp_pct < 0.5 and safe_neighbors > 0:
            return "flee", 0.75

        # Can one-shot weakest enemy → attack
        if weakest_enemy_hp > 0 and our_damage >= weakest_enemy_hp and our_ep >= 2:
            return "attack", 0.90

        # Good HP + EP → attack
        if our_hp_pct >= 0.6 and our_ep >= 2:
            return "attack", 0.70

        # Too many enemies + low resources → flee
        if agents_in_region >= 4 and our_hp_pct < 0.6:
            return "flee", 0.75

        # Medium HP, have healing → heal first
        if our_hp_pct < 0.7 and our_healing_items > 0:
            return "heal", 0.65

        # Default: attack if possible
        if our_ep >= 2:
            return "attack", 0.55

        return "flee", 0.50

    def train(self, X: np.ndarray, y: np.ndarray):
        """Train the model on late-game decision data."""
        if len(X) < 10:
            logger.info(f"Not enough late-game data to train ({len(X)} events, need 10)")
            return

        # Need at least 2 different classes to train
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            logger.info(f"ML: Late game — need more action variety (only have: {unique_classes})")
            return

        try:
            from sklearn.ensemble import GradientBoostingClassifier
            self.model = GradientBoostingClassifier(
                n_estimators=50,
                max_depth=4,
                learning_rate=0.1,
                random_state=42,
            )
            self.model.fit(X, y)

            # Save model
            ensure_data_dirs()
            model_path = os.path.join(MODELS_DIR, MODEL_FILENAME)
            with open(model_path, "wb") as f:
                pickle.dump(self.model, f)

            logger.success(f"Late game ML model trained on {len(X)} events", logger.SYM_GEAR)
        except ImportError:
            logger.warning("sklearn not available — using rule-based late game decisions")
        except Exception as e:
            logger.error(f"Late game model training failed: {e}")


def extract_late_game_features(state: GameState, turn: int) -> np.ndarray:
    """
    Extract 15 features for late-game ML prediction.
    """
    from src.strategy.inventory import get_healing_items_count, get_weapon_tier
    from src.strategy.movement import count_safe_neighbors

    agent = state.self_agent
    region = state.current_region
    enemies = state.agents_in_region()

    # Basic agent stats
    our_hp_pct = agent.hp / max(1, agent.max_hp)
    our_ep = float(agent.ep)
    our_weapon_tier = float(get_weapon_tier(agent.weapon_name))
    our_kills = float(agent.kills)
    num_enemies = float(len(enemies))

    # Enemy analysis
    weakest_hp = float(min((e.hp for e in enemies), default=0))
    strongest_atk = float(max((e.total_atk for e in enemies), default=0))
    total_enemy_healing = float(sum(e.estimate_healing_potential() for e in enemies))
    avg_enemy_hp = float(np.mean([e.hp for e in enemies])) if enemies else 0.0

    # Our resources
    healing_count = float(get_healing_items_count(agent))
    turn_progress = turn / 56.0
    safe_neighbors = float(count_safe_neighbors(region, state))
    connections = float(len(region.connections))
    damage_potential = float(agent.total_atk)

    # Threat level
    total_enemy_atk = sum(e.total_atk for e in enemies)
    threat_level = total_enemy_atk / max(1, agent.hp)

    return np.array([
        our_hp_pct, our_ep, our_weapon_tier, our_kills,
        num_enemies, weakest_hp, strongest_atk, healing_count,
        total_enemy_healing, avg_enemy_hp, turn_progress,
        safe_neighbors, connections, damage_potential, threat_level,
    ], dtype=np.float64)


# Singleton
late_game_predictor = LateGamePredictor()
