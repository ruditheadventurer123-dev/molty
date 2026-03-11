"""
Molty Royale AI Bot — Feature Engine
Extract ML features from game states and combat events.
"""

import numpy as np
from src.config import WEAPON_RANKING


# Weapon name to numeric tier
WEAPON_TIER_MAP = {name: i for i, name in enumerate(reversed(WEAPON_RANKING))}


def weapon_to_tier(weapon_name: str) -> int:
    """Convert weapon name to numeric tier (0=worst, 6=best)."""
    return WEAPON_TIER_MAP.get(weapon_name.lower(), 0)


def extract_combat_features(our_stats: dict, enemy_stats: dict) -> np.ndarray:
    """
    Extract feature vector from combat event data for ML model.

    Features (10 total):
    0: hp_ratio          — our HP / enemy HP
    1: atk_diff          — our total ATK - enemy total ATK
    2: def_diff          — our DEF - enemy DEF
    3: our_weapon_tier   — our weapon tier (0-6)
    4: enemy_weapon_tier — enemy weapon tier (0-6)
    5: our_hp_pct        — our HP / 100
    6: enemy_hp_pct      — enemy HP / 100
    7: has_ranged         — 1 if we have ranged weapon, 0 otherwise
    8: enemy_has_healing  — 1 if enemy has healing items, 0 otherwise
    9: damage_ratio       — our damage output / enemy damage output
    """
    our_hp = our_stats.get("hp", 100)
    our_atk = our_stats.get("atk", 10)
    our_def = our_stats.get("def", 5)
    our_weapon = our_stats.get("weapon", "Fist")
    our_weapon_bonus = our_stats.get("weapon_bonus", 0)

    enemy_hp = enemy_stats.get("hp", 100)
    enemy_atk = enemy_stats.get("atk", 10)
    enemy_def = enemy_stats.get("def", 5)
    enemy_weapon = enemy_stats.get("weapon", "Fist")
    enemy_weapon_bonus = enemy_stats.get("weapon_bonus", 0)
    enemy_healing = 1.0 if enemy_stats.get("has_healing", False) else 0.0

    # Calculate derived features
    hp_ratio = our_hp / max(1, enemy_hp)
    our_total_atk = our_atk + our_weapon_bonus
    enemy_total_atk = enemy_atk + enemy_weapon_bonus
    atk_diff = our_total_atk - enemy_total_atk
    def_diff = our_def - enemy_def

    our_tier = weapon_to_tier(our_weapon)
    enemy_tier = weapon_to_tier(enemy_weapon)

    our_hp_pct = our_hp / 100.0
    enemy_hp_pct = enemy_hp / 100.0

    # Ranged advantage (bow=range1, pistol=range1, sniper=range2)
    has_ranged = 1.0 if our_weapon.lower() in ("bow", "pistol", "sniper") else 0.0

    # Damage output ratio
    our_dmg = max(1, our_total_atk - enemy_def * 0.5)
    enemy_dmg = max(1, enemy_total_atk - our_def * 0.5)
    damage_ratio = our_dmg / max(1, enemy_dmg)

    return np.array([
        hp_ratio, atk_diff, def_diff,
        our_tier, enemy_tier,
        our_hp_pct, enemy_hp_pct,
        has_ranged, enemy_healing, damage_ratio
    ], dtype=np.float64)


def extract_features_from_event(event: dict) -> tuple:
    """
    Extract features and label from a combat event record.
    Returns (features: np.ndarray, label: int)
    Label: 1 = win, 0 = lose
    """
    features = extract_combat_features(event["our_stats"], event["enemy_stats"])
    label = 1 if event.get("result") == "win" else 0
    return features, label


def batch_extract(events: list) -> tuple:
    """
    Extract features from a list of combat events.
    Returns (X: np.ndarray shape (n, 10), y: np.ndarray shape (n,))
    """
    if not events:
        return np.array([]).reshape(0, 10), np.array([])

    X_list = []
    y_list = []
    for event in events:
        try:
            features, label = extract_features_from_event(event)
            X_list.append(features)
            y_list.append(label)
        except (KeyError, TypeError):
            continue

    if not X_list:
        return np.array([]).reshape(0, 10), np.array([])

    return np.array(X_list), np.array(y_list)


FEATURE_NAMES = [
    "hp_ratio", "atk_diff", "def_diff",
    "our_weapon_tier", "enemy_weapon_tier",
    "our_hp_pct", "enemy_hp_pct",
    "has_ranged", "enemy_has_healing", "damage_ratio"
]


def batch_extract_with_scores(labeled_events: list) -> tuple:
    """
    Extract features from labeled combat events with continuous scores.
    Input: list of (event_dict, score_float) tuples from survival_scorer.
    Returns (X: np.ndarray shape (n, 10), y: np.ndarray shape (n,))
    where y is continuous 0.0-1.0 scores (for regression).
    """
    if not labeled_events:
        return np.array([]).reshape(0, 10), np.array([])

    X_list = []
    y_list = []
    for event, score in labeled_events:
        try:
            features = extract_combat_features(event["our_stats"], event["enemy_stats"])
            X_list.append(features)
            y_list.append(float(score))
        except (KeyError, TypeError):
            continue

    if not X_list:
        return np.array([]).reshape(0, 10), np.array([])

    return np.array(X_list), np.array(y_list)

