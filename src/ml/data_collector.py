"""
Molty Royale AI Bot — Data Collector
Records game data for ML training. Saves per-game JSON files.
"""

import os
import json
from datetime import datetime
from typing import Optional
from src.config import GAME_HISTORY_DIR, ensure_data_dirs


class GameDataCollector:
    """Collects and stores game data for ML training."""

    def __init__(self):
        self.current_game = None
        self.game_id = ""

    def start_game(self, game_id: str, agent_name: str):
        """Initialize data collection for a new game."""
        self.game_id = game_id
        self.current_game = {
            "game_id": game_id,
            "agent_name": agent_name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "result": None,
            "total_turns": 0,
            "turns": [],
            "combat_events": [],
            "deaths": [],
            "items_collected": [],
            "regions_visited": [],
        }

    def record_turn(self, turn_num: int, state_snapshot: dict, action_taken: dict,
                     reasoning: str = ""):
        """Record a single turn's data."""
        if not self.current_game:
            return

        turn_data = {
            "turn": turn_num,
            "timestamp": datetime.now().isoformat(),
            "state": {
                "hp": state_snapshot.get("hp", 0),
                "max_hp": state_snapshot.get("max_hp", 100),
                "ep": state_snapshot.get("ep", 0),
                "atk": state_snapshot.get("atk", 10),
                "def": state_snapshot.get("def", 5),
                "kills": state_snapshot.get("kills", 0),
                "region_id": state_snapshot.get("region_id", ""),
                "region_terrain": state_snapshot.get("region_terrain", ""),
                "is_death_zone": state_snapshot.get("is_death_zone", False),
                "weapon": state_snapshot.get("weapon", "Fist"),
                "weapon_bonus": state_snapshot.get("weapon_bonus", 0),
                "inventory_count": state_snapshot.get("inventory_count", 0),
                "visible_agents": state_snapshot.get("visible_agents", 0),
                "visible_monsters": state_snapshot.get("visible_monsters", 0),
            },
            "action": action_taken,
            "reasoning": reasoning,
        }
        self.current_game["turns"].append(turn_data)
        self.current_game["total_turns"] = turn_num

        # Track visited regions
        rid = state_snapshot.get("region_id", "")
        if rid and rid not in self.current_game["regions_visited"]:
            self.current_game["regions_visited"].append(rid)

    def record_combat(self, our_stats: dict, enemy_stats: dict, result: str,
                      damage_dealt: int = 0, damage_taken: int = 0):
        """Record a combat event for ML training."""
        if not self.current_game:
            return

        event = {
            "timestamp": datetime.now().isoformat(),
            "our_stats": {
                "hp": our_stats.get("hp", 100),
                "atk": our_stats.get("atk", 10),
                "def": our_stats.get("def", 5),
                "weapon": our_stats.get("weapon", "Fist"),
                "weapon_bonus": our_stats.get("weapon_bonus", 0),
            },
            "enemy_stats": {
                "hp": enemy_stats.get("hp", 100),
                "atk": enemy_stats.get("atk", 10),
                "def": enemy_stats.get("def", 5),
                "weapon": enemy_stats.get("weapon", "Fist"),
                "weapon_bonus": enemy_stats.get("weapon_bonus", 0),
                "has_healing": enemy_stats.get("has_healing", False),
                "healing_potential": enemy_stats.get("healing_potential", 0),
            },
            "result": result,  # "win", "lose", "flee"
            "damage_dealt": damage_dealt,
            "damage_taken": damage_taken,
        }
        self.current_game["combat_events"].append(event)

    def record_item_pickup(self, item_name: str, item_category: str):
        """Record an item pickup."""
        if not self.current_game:
            return
        self.current_game["items_collected"].append({
            "name": item_name,
            "category": item_category,
            "timestamp": datetime.now().isoformat(),
        })

    def end_game(self, result: dict):
        """Finalize and save game data."""
        if not self.current_game:
            return

        self.current_game["ended_at"] = datetime.now().isoformat()
        self.current_game["result"] = {
            "is_winner": result.get("is_winner", False),
            "final_rank": result.get("final_rank", 0),
            "kills": result.get("kills", 0),
            "rewards": result.get("rewards", 0),
        }

        self._save()

        # Sync to Supabase cloud (non-blocking, graceful fail)
        try:
            from src.storage import supabase_store
            if supabase_store.is_enabled():
                supabase_store.save_game(self.current_game)
                # Also save individual combat events
                game_id = self.current_game.get("game_id", "")
                for event in self.current_game.get("combat_events", []):
                    supabase_store.save_combat_event(event, game_id)
        except Exception:
            pass  # Local save already succeeded

    def record_late_game_decision(self, turn: int, features: list,
                                   action_taken: str, reasoning: str = ""):
        """
        Record a late-game ML decision for training.
        action_taken: "attack", "flee", or "heal"
        features: 15-element feature list from extract_late_game_features
        """
        if not self.current_game:
            return

        if "late_game_decisions" not in self.current_game:
            self.current_game["late_game_decisions"] = []

        self.current_game["late_game_decisions"].append({
            "turn": turn,
            "features": features,
            "action": action_taken,
            "reasoning": reasoning,
            "timestamp": datetime.now().isoformat(),
        })

    def record_healing_decision(self, turn: int, hp: int, max_hp: int,
                                 healing_items_count: int, used_item: bool,
                                 game_phase: str):
        """
        Record healing decision for ML training.
        Tracks healing usage patterns correlated with survival.
        """
        if not self.current_game:
            return

        if "healing_decisions" not in self.current_game:
            self.current_game["healing_decisions"] = []

        self.current_game["healing_decisions"].append({
            "turn": turn,
            "hp": hp,
            "max_hp": max_hp,
            "hp_pct": hp / max(1, max_hp),
            "healing_items_count": healing_items_count,
            "used_item": used_item,
            "game_phase": game_phase,
            "timestamp": datetime.now().isoformat(),
        })

    def _save(self):
        """Save current game data to JSON file."""
        ensure_data_dirs()
        filename = f"{self.game_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(GAME_HISTORY_DIR, filename)

        try:
            with open(filepath, "w") as f:
                json.dump(self.current_game, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save game data: {e}")

    @staticmethod
    def load_all_games() -> list:
        """Load all saved game histories. Tries Supabase first, falls back to local."""
        # Try Supabase first
        try:
            from src.storage import supabase_store
            if supabase_store.is_enabled():
                cloud_games = supabase_store.load_all_games()
                if cloud_games:
                    return cloud_games
        except Exception:
            pass

        # Fall back to local files
        ensure_data_dirs()
        games = []
        if not os.path.exists(GAME_HISTORY_DIR):
            return games

        for filename in os.listdir(GAME_HISTORY_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(GAME_HISTORY_DIR, filename)
                try:
                    with open(filepath, "r") as f:
                        games.append(json.load(f))
                except (json.JSONDecodeError, IOError):
                    continue
        return games

    @staticmethod
    def get_all_combat_events() -> list:
        """Extract all combat events from all game histories."""
        events = []
        for game in GameDataCollector.load_all_games():
            events.extend(game.get("combat_events", []))
        return events

    @staticmethod
    def get_total_games_played() -> int:
        """Count total games played."""
        ensure_data_dirs()
        if not os.path.exists(GAME_HISTORY_DIR):
            return 0
        return len([f for f in os.listdir(GAME_HISTORY_DIR) if f.endswith(".json")])


# Singleton instance
collector = GameDataCollector()
