"""
Molty Royale AI Bot — Configuration
All game constants, API settings, and tunable strategy parameters.
"""

import os
import json
import random
from datetime import datetime, timezone

# ─── API Configuration ─────────────────────────────────────────────
BASE_URL = "https://cdn.moltyroyale.com/api"

def load_api_key():
    """Load API key from env var or credentials file."""
    key = os.environ.get("MR_API_KEY")
    if key:
        return key
    cred_path = os.path.expanduser("~/.molty-royale/credentials.json")
    if os.path.exists(cred_path):
        with open(cred_path, "r") as f:
            data = json.load(f)
            return data.get("api_key", "")
    return ""

def load_room_type():
    """Load room type preference from env var or credentials file."""
    rt = os.environ.get("MR_ROOM_TYPE")
    if rt and rt in ("free", "paid"):
        return rt
    cred_path = os.path.expanduser("~/.molty-royale/credentials.json")
    if os.path.exists(cred_path):
        with open(cred_path, "r") as f:
            data = json.load(f)
            return data.get("room_type", "free")
    return "free"

# ─── Indonesian Room Name Generator ────────────────────────────────
NOUNS_ID = [
    "Harimau", "Garuda", "Kancil", "Kucing", "Singa", "Elang", "Naga", "Serigala",
    "Beruang", "Kuda", "Banteng", "Hiu", "Paus", "Rajawali", "Macan", "Bima"
]
ADJECTIVES_ID = [
    "Sakti", "Hitam", "Putih", "Emas", "Perkasa", "Gesit", "Cepat", "Kuat",
    "Ganas", "Kilat", "Petir", "Api", "Es", "Bayangan", "Baja", "Bintang"
]

def generate_indo_room_name():
    """Generate a consistent random name like 'Harimau Sakti' based on the current day."""
    # Use current Date as seed in UTC to avoid hourly desynchronization
    # e.g., "20260310"
    seed_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    seed_val = int(seed_str)
    
    # Store old state to avoid affecting other random calls
    old_state = random.getstate()
    random.seed(seed_val)
    
    noun = random.choice(NOUNS_ID)
    adj = random.choice(ADJECTIVES_ID)
    
    # Restore old state
    random.setstate(old_state)
    
    return f"{noun} {adj}"

def load_room_name():
    """Load room name from env, fallback to auto-generated."""
    return os.environ.get("MR_ROOM_NAME") or generate_indo_room_name()

def get_friendly_agents():
    """Get list of friendly agent names to avoid attacking."""
    friends = set()
    
    # Try MR_FRIENDS env var first (comma separated)
    env_friends = os.environ.get("MR_FRIENDS")
    if env_friends:
        for f in env_friends.split(","):
            if f.strip():
                friends.add(f.strip().lower())
                
    # Parse accounts_db.json
    try:
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounts_db.json")
        if os.path.exists(db_path):
            with open(db_path, "r") as f:
                data = json.load(f)
                for account in data.get("accounts", []):
                    name = account.get("name")
                    if name:
                        friends.add(name.lower())
    except Exception as e:
        print(f"Warning: Failed to load friendly agents from accounts_db.json: {e}")
        
    return list(friends)

API_KEY = load_api_key()
ROOM_TYPE = load_room_type()
AUTO_ROOM_NAME = load_room_name()
HOST_ACCOUNT = os.environ.get("MR_HOST_ACCOUNT", "martyr") # Default host
FRIENDLY_AGENTS = get_friendly_agents()

# ─── Game Time Constants ───────────────────────────────────────────
TOTAL_TURNS = 56                    # 14 days × 4 turns/day
TURN_DURATION_SECONDS = 60          # Real-time seconds per turn
GAME_HOURS_PER_TURN = 6
DEATH_ZONE_START_DAY = 2            # Day 2, 06:00
DEATH_ZONE_EXPANSION_INTERVAL = 3   # Every 3 turns
DEATH_ZONE_DPS = 1.34               # HP per second

# ─── Stats Defaults ────────────────────────────────────────────────
DEFAULT_HP = 100
DEFAULT_MAX_HP = 100
DEFAULT_EP = 10
DEFAULT_MAX_EP = 10
DEFAULT_ATK = 10
DEFAULT_DEF = 5
DEFAULT_VISION = 1
MAX_INVENTORY = 10

# ─── EP Costs ──────────────────────────────────────────────────────
EP_COST = {
    "move": 1,
    "move_storm": 2,
    "move_water": 2,
    "explore": 1,
    "attack": 2,
    "use_item": 1,
    "interact": 1,
    "rest": 0,
    "pickup": 0,
    "equip": 0,
    "talk": 0,
    "whisper": 0,
    "broadcast": 0,
}

# ─── Weapon Stats (ATK Bonus, Range, Tier) ─────────────────────────
WEAPONS = {
    "fist":    {"atk_bonus": 0,  "range": 0, "tier": 0, "type": "melee"},
    "knife":   {"atk_bonus": 5,  "range": 0, "tier": 1, "type": "melee"},
    "bow":     {"atk_bonus": 3,  "range": 1, "tier": 2, "type": "ranged"},
    "sword":   {"atk_bonus": 8,  "range": 0, "tier": 3, "type": "melee"},
    "pistol":  {"atk_bonus": 6,  "range": 1, "tier": 4, "type": "ranged"},
    "sniper":  {"atk_bonus": 17, "range": 2, "tier": 5, "type": "ranged"},
    "katana":  {"atk_bonus": 21, "range": 0, "tier": 6, "type": "melee"},
}

# Weapon ranking by effective power (atk_bonus), highest first
WEAPON_RANKING = ["katana", "sniper", "sword", "pistol", "knife", "bow", "fist"]

# ─── Monster Stats ─────────────────────────────────────────────────
MONSTERS = {
    "wolf":   {"hp": 5,  "atk": 15, "def": 1},
    "bear":   {"hp": 15, "atk": 20, "def": 2},
    "bandit": {"hp": 25, "atk": 25, "def": 3},
}

# ─── Recovery Items ────────────────────────────────────────────────
RECOVERY_ITEMS = {
    "emergency food": {"hp_restore": 20, "ep_restore": 0},
    "bandage":        {"hp_restore": 30, "ep_restore": 0},
    "medkit":         {"hp_restore": 50, "ep_restore": 0},
    "energy drink":   {"hp_restore": 0,  "ep_restore": 5},
}

# ─── Terrain Modifiers ─────────────────────────────────────────────
TERRAIN = {
    "plains": {"vision_mod": 1,  "move_ep_extra": 0},
    "forest": {"vision_mod": -1, "move_ep_extra": 0},
    "hills":  {"vision_mod": 2,  "move_ep_extra": 0},
    "ruins":  {"vision_mod": 0,  "move_ep_extra": 0},
    "water":  {"vision_mod": 0,  "move_ep_extra": 1},
}

# Terrain preference for strategic positioning (higher = better)
TERRAIN_PRIORITY = {"hills": 4, "ruins": 3, "forest": 2, "plains": 1, "water": 0}

# ─── Weather Modifiers ─────────────────────────────────────────────
WEATHER = {
    "clear": {"vision_mod": 0,  "move_ep_extra": 0},
    "rain":  {"vision_mod": -1, "move_ep_extra": 0},
    "fog":   {"vision_mod": -2, "move_ep_extra": 0},
    "storm": {"vision_mod": -2, "move_ep_extra": 1},
}

# ─── Strategy Tuning — Loaded/Saved at Runtime ────────────────────
DEFAULT_STRATEGY_WEIGHTS = {
    "hp_heal_threshold": 30,           # Heal when HP below this
    "hp_heal_medkit_threshold": 50,    # Use Medkit when HP below this
    "win_probability_threshold": 0.7,  # Min probability to initiate attack
    "guaranteed_kill_hp": 20,          # Chase enemy if their HP below this
    "ep_minimum_for_attack": 2,        # Need at least 2 EP to attack
    "ep_rest_threshold": 2,            # Rest if EP below this
    "aggression_factor": 0.6,          # Weight: combat vs avoidance (0-1)
    "exploration_priority": 0.3,       # Weight: explore vs attack (0-1)
}

# ─── Game Phase Constants ──────────────────────────────────────────
EARLY_GAME_END = 20       # Turns 1-20
MID_GAME_END = 40         # Turns 21-40
# Late game = turns 41-56

# ─── Late Game Healing Thresholds ──────────────────────────────────
LATE_GAME_HP_HEAL_THRESHOLD = 50       # Heal when HP below this in late game
LATE_GAME_MEDKIT_THRESHOLD = 70        # Use medkit when HP below this in late game
LATE_GAME_HEAL_PERCENT = 0.70          # Always heal if HP < 70% in late game
CHAOS_HP_THRESHOLD = 60               # Heal when 3+ agents in region, HP below this
CROWDED_AGENT_THRESHOLD = 4           # 4+ agents = crowded region, consider fleeing

# ─── Healing Conservation Thresholds ───────────────────────────────
EARLY_GAME_CONSERVE_HP = 40            # Only heal if HP < 40 in early game
MID_GAME_CONSERVE_HP = 50              # Only heal if HP < 50 in mid game

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
GAME_HISTORY_DIR = os.path.join(DATA_DIR, "game_history")
MODELS_DIR = os.path.join(DATA_DIR, "models")
STRATEGY_WEIGHTS_PATH = os.path.join(DATA_DIR, "strategy_weights.json")

def load_strategy_weights():
    """Load strategy weights from file, or return defaults."""
    if os.path.exists(STRATEGY_WEIGHTS_PATH):
        try:
            with open(STRATEGY_WEIGHTS_PATH, "r") as f:
                saved = json.load(f)
                weights = DEFAULT_STRATEGY_WEIGHTS.copy()
                weights.update(saved)
                return weights
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_STRATEGY_WEIGHTS.copy()

def save_strategy_weights(weights):
    """Save strategy weights to file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STRATEGY_WEIGHTS_PATH, "w") as f:
        json.dump(weights, f, indent=2)

def ensure_data_dirs():
    """Create data directories if they don't exist."""
    os.makedirs(GAME_HISTORY_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)
