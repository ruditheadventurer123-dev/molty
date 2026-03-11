"""
Molty Royale AI Bot — Supabase Cloud Storage
Syncs game data to Supabase for persistent storage (survives Railway re-deploys).
Falls back gracefully if Supabase is not configured.
"""

import os
import json
from datetime import datetime
from src import logger

# Supabase config from environment
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client = None
_enabled = False


def init():
    """Initialize Supabase client. Call once at startup."""
    global _client, _enabled

    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.info("Supabase not configured (no SUPABASE_URL/KEY). Data saved locally only.")
        return False

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _enabled = True
        logger.success("Supabase connected! Game data will be synced to cloud.", "☁️")
        return True
    except ImportError:
        logger.warning("supabase package not installed. Data saved locally only.")
        return False
    except Exception as e:
        logger.warning(f"Supabase init failed: {e}. Data saved locally only.")
        return False


def is_enabled() -> bool:
    """Check if Supabase storage is active."""
    return _enabled and _client is not None


def save_game(game_data: dict) -> bool:
    """
    Save complete game data to Supabase 'game_history' table.
    Returns True if saved successfully.
    """
    if not is_enabled():
        return False

    try:
        # Prepare record for Supabase
        result = game_data.get("result", {})
        record = {
            "game_id": game_data.get("game_id", ""),
            "agent_name": game_data.get("agent_name", ""),
            "started_at": game_data.get("started_at", ""),
            "ended_at": game_data.get("ended_at", ""),
            "total_turns": game_data.get("total_turns", 0),
            "is_winner": result.get("is_winner", False),
            "final_rank": result.get("final_rank", 0),
            "kills": result.get("kills", 0),
            "rewards": result.get("rewards", 0),
            "regions_visited": len(game_data.get("regions_visited", [])),
            "combat_events_count": len(game_data.get("combat_events", [])),
            "items_collected_count": len(game_data.get("items_collected", [])),
            # Store full game data as JSON for detailed analysis
            "full_data": json.dumps(game_data),
        }

        _client.table("game_history").insert(record).execute()
        logger.success(f"Game data saved to Supabase (game: {record['game_id'][:8]}...)", "☁️")
        return True

    except Exception as e:
        logger.warning(f"Supabase save failed: {e}")
        return False


def save_combat_event(event: dict, game_id: str) -> bool:
    """Save individual combat event to 'combat_events' table."""
    if not is_enabled():
        return False

    try:
        record = {
            "game_id": game_id,
            "timestamp": event.get("timestamp", ""),
            "our_hp": event.get("our_stats", {}).get("hp", 0),
            "our_weapon": event.get("our_stats", {}).get("weapon", "Fist"),
            "our_weapon_bonus": event.get("our_stats", {}).get("weapon_bonus", 0),
            "enemy_hp": event.get("enemy_stats", {}).get("hp", 0),
            "enemy_weapon": event.get("enemy_stats", {}).get("weapon", "Fist"),
            "enemy_has_healing": event.get("enemy_stats", {}).get("has_healing", False),
            "result": event.get("result", "pending"),
            "damage_dealt": event.get("damage_dealt", 0),
            "damage_taken": event.get("damage_taken", 0),
        }

        _client.table("combat_events").insert(record).execute()
        return True

    except Exception as e:
        logger.warning(f"Supabase combat event save failed: {e}")
        return False


def load_all_games() -> list:
    """Load all game histories from Supabase."""
    if not is_enabled():
        return []

    try:
        response = _client.table("game_history") \
            .select("full_data") \
            .order("created_at", desc=True) \
            .limit(100) \
            .execute()

        games = []
        for row in response.data:
            try:
                games.append(json.loads(row["full_data"]))
            except (json.JSONDecodeError, KeyError):
                continue
        return games

    except Exception as e:
        logger.warning(f"Supabase load failed: {e}")
        return []


def get_stats() -> dict:
    """Get quick stats from Supabase."""
    if not is_enabled():
        return {}

    try:
        response = _client.table("game_history") \
            .select("is_winner, final_rank, kills, total_turns") \
            .execute()

        data = response.data
        if not data:
            return {"total_games": 0}

        total = len(data)
        wins = sum(1 for d in data if d.get("is_winner"))
        avg_rank = sum(d.get("final_rank", 0) for d in data) / max(1, total)
        avg_kills = sum(d.get("kills", 0) for d in data) / max(1, total)
        avg_turns = sum(d.get("total_turns", 0) for d in data) / max(1, total)

        return {
            "total_games": total,
            "wins": wins,
            "win_rate": wins / max(1, total),
            "avg_rank": round(avg_rank, 1),
            "avg_kills": round(avg_kills, 1),
            "avg_turns": round(avg_turns, 1),
        }

    except Exception as e:
        logger.warning(f"Supabase stats failed: {e}")
        return {}
