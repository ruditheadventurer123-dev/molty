"""
Molty Royale AI Bot — Main Entry Point
Continuous lifecycle: find game → play → learn → repeat.
Handles Ctrl+C gracefully with signal handlers.
"""

import signal
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api_client import MoltyAPIClient, APIError
from src.bot import Bot
from src.room_manager import RoomManager
from src.ml.training import retrain_if_needed, get_model_status
from src.ml.strategy_optimizer import optimizer as strategy_optimizer
from src.config import ensure_data_dirs, load_api_key, load_room_type, HOST_ACCOUNT
from src import logger


class MoltyBot:
    """Main orchestrator — continuous game lifecycle."""

    def __init__(self, api_key: str = None, room_type: str = None, room_name: str = None, agent_label: str = "", is_fallback_host: bool = False):
        self._running = True
        self.api_client = None
        self.bot = None
        self.room_manager = None
        self.agent_name = ""
        self.games_played = 0
        self._api_key = api_key  # None = load from env (backward compatible)
        self._room_type = room_type  # None = load from env
        self._room_name = room_name  # None = auto-generate (fallback)
        self._agent_label = agent_label  # For multi-agent log prefix
        self._is_fallback_host = is_fallback_host

        # Register signal handlers for graceful shutdown
        # Only register in main thread to avoid errors in worker threads
        import threading
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C and SIGTERM gracefully."""
        if not self._running:
            # Second Ctrl+C = force exit
            print("\nForce exit!")
            sys.exit(1)

        self._running = False
        logger.shutdown_message()

        # Stop all components gracefully
        if self.bot:
            self.bot.stop()
        if self.room_manager:
            self.room_manager.stop()

    def run(self):
        """Main entry point — runs continuously until stopped."""
        # Set log prefix for multi-agent mode
        self._color_idx = 0
        if self._agent_label:
            self._color_idx = int(self._agent_label.split('-')[-1]) - 1 if '-' in self._agent_label else 0
            logger.set_prefix(f"[{self._agent_label}]", self._color_idx)

        logger.banner()

        # ── Step 1: Load API key ─────────────────────────────────
        api_key = self._api_key or load_api_key()
        if not api_key:
            logger.error("No API key found!")
            logger.info("Set MR_API_KEY environment variable or run ./run.sh for setup.")
            return

        logger.success(f"API key loaded: {api_key[:12]}...{api_key[-4:]}")

        # ── Step 2: Initialize API client ────────────────────────
        self.api_client = MoltyAPIClient(api_key)

        # ── Step 3: Fetch account info ───────────────────────────
        try:
            account = self.api_client.get_account_info()
            self.agent_name = account.get("name", "MoltyBot")
            balance = account.get("balance", 0)
            total_games = account.get("totalGames", 0)
            total_wins = account.get("totalWins", 0)
            wallet = account.get("walletAddress", "Not set")

            logger.separator("-")
            logger.info(f"Account: {self.agent_name}", logger.SYM_BOT)
            logger.info(f"Balance: {balance} $Moltz", logger.SYM_MONEY)
            logger.info(f"Record : {total_wins}W / {total_games}G", logger.SYM_TROPHY)
            logger.info(f"Wallet : {wallet[:10]}...{wallet[-6:]}" if len(str(wallet)) > 20 else f"Wallet : {wallet}")
            logger.separator("-")

            # Update prefix to real agent name (replaces generic "Agent-1" etc.)
            if self._agent_label:
                logger.set_prefix(f"[{self.agent_name}]", self._color_idx)
                self._agent_label = self.agent_name

            if wallet == "Not set" or not wallet:
                logger.warning("No wallet address set! You won't receive rewards.")
                logger.info("Set wallet via: PUT /accounts/wallet")

        except APIError as e:
            logger.error(f"Failed to fetch account info: {e}")
            logger.info("Check your API key and try again.")
            sys.exit(1)

        # ── Step 4: Load room type ───────────────────────────────
        room_type = self._room_type or load_room_type()
        logger.info(f"Room type: {room_type.upper()}", logger.SYM_GEAR)

        # ── Step 5: Show ML status ───────────────────────────────
        logger.info(get_model_status(), logger.SYM_GEAR)
        logger.info(f"Strategy: {strategy_optimizer.get_summary()}", logger.SYM_GEAR)

        # ── Step 6: Initialize components ────────────────────────
        self.bot = Bot(self.api_client)
        self.bot._agent_label = self._agent_label or self.agent_name
        
        # Determine if this agent is the host
        clean_host = (HOST_ACCOUNT or "").strip(' "\'').lower()
        clean_name = (self.agent_name or "").strip(' "\'').lower()
        is_host = (clean_name == clean_host)
        
        # If no host account is explicitly defined in ENV, fallback to the first agent
        if not clean_host and self._is_fallback_host:
            is_host = True
            
        logger.info(f"DEBUG HOST: name='{clean_name}', env_host='{clean_host}', fallback={self._is_fallback_host} => is_host={is_host}")
            
        if is_host:
            logger.success(f"Agent {self.agent_name} is the designated HOST for room creation.", logger.SYM_STAR)
            
        self.room_manager = RoomManager(self.api_client, self._room_type, self._room_name, is_host)
        self.room_manager.set_agent_name(self.agent_name)
        self.room_manager._agent_label = self._agent_label or self.agent_name

        # Initialize dashboard state with account info
        try:
            from src.dashboard.dashboard_state import state as dash
            label = self._agent_label or self.agent_name
            dash.update_agent_state(label, {
                "name": self.agent_name,
                "status": "idle",
                "wins": total_wins,
                "moltz": balance,
                "hp": 0, "max_hp": 100, "ep": 0, "max_ep": 10,
                "atk": 0, "def": 0, "vision": 0, "kills": 0,
                "weapon": "Fist", "weapon_bonus": 0,
                "region_name": "-", "terrain": "", "weather": "",
                "game_name": "", "turn": 0,
                "inventory": [], "visible_agents": [],
                "visible_monsters": [], "visible_items": [],
            })
        except Exception:
            pass

        ensure_data_dirs()

        # Initialize Supabase cloud storage (graceful if not configured)
        try:
            from src.storage import supabase_store
            supabase_store.init()
        except Exception:
            pass  # No Supabase = local only, that's fine

        # ── Start Dashboard Server (single-agent mode) ───────────
        try:
            from src.dashboard.dashboard_server import start_dashboard, start_stats_emitter
            start_dashboard()
            start_stats_emitter()
        except Exception as e:
            logger.warning(f"Dashboard: {e}")

        logger.separator("=")
        logger.success("Bot initialized! Starting game lifecycle...", logger.SYM_BOT)
        logger.separator("=")

        # ── Step 7: Continuous game lifecycle ─────────────────────
        while self._running:
            try:
                # Find and join a game
                game_id, agent_id = self.room_manager.find_and_join_game()

                if not game_id or not agent_id:
                    if self._running:
                        logger.warning("Could not join a game. Retrying in 30s...")
                        self._sleep_interruptible(30)
                    continue

                # Play the game
                self.bot._game_name = self.room_manager.last_game_name
                self.bot.play_game(game_id, agent_id, self.agent_name)
                self.games_played += 1

                # Emit updated counters to dashboard
                try:
                    from src.dashboard import dashboard_state as ds
                    if ds.state._socketio:
                        ds.state._socketio.emit("counter_update", {
                            "total_games": ds.state._total_games,
                            "total_wins": ds.state._total_wins,
                        })
                except Exception:
                    pass

                if not self._running:
                    break

                # Post-game: ML update
                logger.separator("-")
                logger.info(f"Game #{self.games_played} complete. Running post-game analysis...")

                # Retrain ML model if needed
                retrain_if_needed()

                # Update strategy weights
                strategy_optimizer.update_weights()
                logger.info(f"Strategy: {strategy_optimizer.get_summary()}", logger.SYM_GEAR)

                logger.separator("-")
                logger.info("Looking for next game...", logger.SYM_SEARCH)

                # Brief pause before looking for next game
                self._sleep_interruptible(5)

            except Exception as e:
                logger.error(f"Lifecycle error: {e}")
                if self._running:
                    self._sleep_interruptible(15)

        # ── Shutdown ─────────────────────────────────────────────
        logger.separator("=")
        logger.info(f"Total games played this session: {self.games_played}", logger.SYM_TROPHY)
        logger.info(get_model_status(), logger.SYM_GEAR)
        logger.success("Bot shutdown complete. Goodbye!", logger.SYM_BOT)

    def _sleep_interruptible(self, seconds: float):
        """Sleep but can be interrupted by stop signal."""
        import time
        end_time = time.time() + seconds
        while time.time() < end_time and self._running:
            time.sleep(min(1.0, end_time - time.time()))


def main():
    """Entry point."""
    bot = MoltyBot()
    bot.run()


if __name__ == "__main__":
    main()
