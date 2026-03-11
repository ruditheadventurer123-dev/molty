"""
Molty Royale AI Bot — Room Manager
Auto-join/create game rooms with fast polling. Supports free and paid rooms.
"""

import time
import random
import threading
from src.api_client import MoltyAPIClient, APIError
from src.config import ROOM_TYPE
from src import logger

# Global lock to prevent multiple agents in the same process from creating a room simultaneously.
CREATE_GAME_LOCK = threading.Lock()

class _SharedState:
    """Shared memory for rapid P2P joining within the same multi-runner instance."""
    def __init__(self):
        self.game_id: str = ""
        self.timestamp: float = 0.0
        self.lock = threading.Lock()

    def set_game(self, game_id: str):
        with self.lock:
            self.game_id = game_id
            self.timestamp = time.time()

    def get_recent_game(self, max_age: float = 10.0) -> str:
        with self.lock:
            if self.game_id and (time.time() - self.timestamp) < max_age:
                return self.game_id
            return ""

SHARED_STATE = _SharedState()

class RoomManager:
    """Manages game lifecycle: find → join → play → repeat."""

    def __init__(self, api_client: MoltyAPIClient, room_type: str = None, room_name: str = None, is_host: bool = False):
        self.api = api_client
        self.room_type = room_type or ROOM_TYPE
        self.room_name = room_name
        self.is_host = is_host
        self.agent_name = ""
        self._running = True
        self._consecutive_timeouts = 0
        self._base_poll_interval = 5
        self._agent_label = ""
        self.last_game_name = ""  # Store room name for dashboard

    def stop(self):
        """Signal the manager to stop."""
        self._running = False

    def set_agent_name(self, name: str):
        """Set the agent display name (fetched from API key)."""
        self.agent_name = name

    def _get_poll_interval(self) -> float:
        """
        Adaptive polling interval.
        Fast (5s) when server is responsive, slows down (up to 30s) on repeated timeouts.
        """
        if self._consecutive_timeouts == 0:
            return self._base_poll_interval
        # Gradually increase: 5 → 10 → 15 → 20 → 25 → 30 (max)
        return min(30, self._base_poll_interval + (self._consecutive_timeouts * 5))

    def find_and_join_game(self) -> tuple:
        """
        Find and join a game. Returns (game_id, agent_id) or (None, None).

        Flow:
        1. Check currentGames for existing active game
        2. If none, search for waiting game matching room type
        3. If none found, create a new game
        4. Register agent and return IDs
        """
        # Step 1: Check if already in a game
        try:
            account = self.api.get_account_info()
            self._consecutive_timeouts = 0  # Server responded
            current_games = account.get("currentGames", [])

            for game in current_games:
                entry_type = game.get("entryType", "free")
                game_status = game.get("gameStatus", "")
                is_alive = game.get("isAlive", True)

                if entry_type == self.room_type:
                    game_id = game.get("gameId", "")
                    agent_id = game.get("agentId", "")
                    agent_name = game.get("agentName", self.agent_name)

                    if game_status == "running":
                        if not is_alive:
                            # Agent is dead in this running game — wait for it to finish
                            short_id = game_id[:8] if game_id else "?"
                            logger.info(
                                f"Agent is dead in running {entry_type} game [{short_id}...]. "
                                f"Waiting for game to finish before joining a new one..."
                            )
                            self._wait_for_game_finish(game_id)
                            # Game finished, now fall through to search for new game
                            continue

                        logger.success(f"Already in running {entry_type} game!", logger.SYM_STAR)
                        logger.joined_game(f"Active Game", game_id, agent_name)
                        self.last_game_name = game.get("gameName", game.get("name", "Active Game"))
                        return game_id, agent_id

                    if game_status == "waiting":
                        logger.info(f"Already in waiting {entry_type} game. Waiting for start...")
                        self.last_game_name = game.get("gameName", game.get("name", "Waiting Room"))
                        self._wait_for_game_start_by_id(game_id)
                        return game_id, agent_id

        except APIError as e:
            if e.code in ("READ_TIMEOUT", "CONNECT_TIMEOUT", "CONNECTION_ERROR", "NETWORK_ERROR"):
                self._consecutive_timeouts += 1
                logger.warning(
                    f"Server timeout (streak: {self._consecutive_timeouts}). "
                    f"Polling interval: {self._get_poll_interval():.0f}s"
                )
            else:
                logger.error(f"Error checking account: {e}")

        # Step 2: Search for waiting game
        check_count = 0
        while self._running:
            try:
                check_count += 1
                logger.waiting_for_game(check_count, self.room_type)
                self._dash_status("searching")

                # 1. Check P2P Shared Memory (bypasses list_games API for instant joining!)
                # This only works for agents running in the exact same multi_runner.py execution.
                if self.room_name:
                    recent_shared_id = SHARED_STATE.get_recent_game(max_age=10.0)
                    if recent_shared_id:
                        agent_id = self._register_in_game(recent_shared_id)
                        if agent_id:
                            self.last_game_name = self.room_name
                            print("")
                            logger.success(f"[P2P SHARE] Instantly joined {self.room_type} room: {self.room_name}")
                            logger.joined_game(self.room_name, recent_shared_id, self.agent_name)
                            return recent_shared_id, agent_id

                # 2. If no shared game, request list from API (slower)
                games = self.api.list_games("waiting")
                self._consecutive_timeouts = 0  # Server responded!

                # Filter by room type
                matching = [g for g in games if g.get("entryType", "free") == self.room_type]
                
                # Filter by room name if specified
                if self.room_name:
                    matching = [g for g in matching if g.get("name", "") == self.room_name]

                if matching:
                    game = matching[0]
                    game_id = game["id"]
                    game_name = game.get("name", "Unknown")
                    print("")  # New line after waiting indicator
                    logger.success(f"Found waiting {self.room_type} game: {game_name}")

                    # Register agent
                    agent_id = self._register_in_game(game_id)
                    if agent_id:
                        self.last_game_name = game_name
                        logger.joined_game(game_name, game_id, self.agent_name)
                        return game_id, agent_id

                else:
                    # No matching game found. If a specific room_name is targeted, EVERYONE can try to create it.
                    # This decentralizes room creation to avoid rate limits (Anti-Spam) on a single host.
                    # If someone else creates it first, this agent cleanly catches WAITING_GAME_EXISTS.
                    if self.room_name or self.is_host:
                        # CROSS-PROJECT JITTER: If not the primary host, randomly delay 0.5s - 3.0s before 
                        # trying to create. This prevents 4 separate Railway projects from creating 
                        # 4 identical rooms at the exact same millisecond. The winner creates it, 
                        # and the sleepers will cleanly catch WAITING_GAME_EXISTS when they wake up.
                        if not self.is_host:
                            jitter = random.uniform(0.5, 3.0)
                            time.sleep(jitter)

                        game_id = self._try_create_game()
                        if game_id:
                            agent_id = self._register_in_game(game_id)
                            if agent_id:
                                self.last_game_name = self.room_name or f"{self.agent_name}'s Room"
                                logger.joined_game("New Room", game_id, self.agent_name)
                                return game_id, agent_id
                        elif not self.is_host:
                            # If creation failed but they aren't the primary host, just log that they're waiting
                            print("")
                            logger.info(f"Room '{self.room_name}' not found. Waiting for it to be created...")
                    else:
                        print("")
                        logger.info(f"Waiting for a '{self.room_type}' room to appear...")

                # AGGRESSIVE (0.5s) polling for EVERYONE targeting a specific room
                # to snipe free 100/100 rooms that fill in < 3 seconds
                poll_time = 0.5 if self.room_name else self._get_poll_interval()
                self._sleep_interruptible(poll_time)

            except APIError as e:
                if e.code == "ACCOUNT_ALREADY_IN_GAME":
                    game_id, agent_id = self._get_current_game_ids()
                    # Check if agent is alive in this game before returning
                    if game_id and agent_id:
                        is_alive = self._is_agent_alive(game_id, agent_id)
                        if not is_alive:
                            short_id = game_id[:8] if game_id else "?"
                            logger.info(
                                f"Agent is dead in active game [{short_id}...]. "
                                f"Waiting for game to finish..."
                            )
                            self._wait_for_game_finish(game_id)
                            continue  # Try again to find a new game
                    self._log_active_game_status(game_id, agent_id)
                    return game_id, agent_id

                if e.code in ("READ_TIMEOUT", "CONNECT_TIMEOUT", "CONNECTION_ERROR", "NETWORK_ERROR"):
                    self._consecutive_timeouts += 1
                    poll = self._get_poll_interval()
                    print("")  # New line after waiting indicator
                    logger.warning(
                        f"Server timeout (streak: {self._consecutive_timeouts}). "
                        f"Next attempt in {poll:.0f}s..."
                    )
                    self._sleep_interruptible(poll)
                else:
                    logger.error(f"Error searching for games: {e}")
                    self._sleep_interruptible(10)

            except Exception as e:
                self._consecutive_timeouts += 1
                print("")
                logger.error(f"Unexpected error: {type(e).__name__}: {e}")
                self._sleep_interruptible(self._get_poll_interval())

        return None, None

    def _register_in_game(self, game_id: str) -> str:
        """Register agent in a game. Returns agent_id or empty string."""
        try:
            if self.room_type == "paid":
                # Paid game: use join-paid flow
                return self._join_paid_game(game_id)
            else:
                # Free game: direct register
                agent_data = self.api.register_agent(game_id, self.agent_name)
                return agent_data.get("id", "")

        except APIError as e:
            if e.code == "ONE_AGENT_PER_API_KEY":
                logger.info("Already registered in this game.")
                return self._get_agent_id_for_game(game_id)
            elif e.code == "ACCOUNT_ALREADY_IN_GAME":
                game_id_active, agent_id_active = self._get_current_game_ids()
                self._log_active_game_status(game_id_active, agent_id_active)
                return agent_id_active or ""
            elif e.code == "MAX_AGENTS_REACHED":
                logger.warning("Game is full. Trying another...")
                return ""
            elif e.code == "GAME_ALREADY_STARTED":
                logger.warning("Game already started. Looking for another...")
                return ""
            else:
                logger.error(f"Registration failed: {e}")
                return ""

    def _join_paid_game(self, game_id: str) -> str:
        """Join a paid game."""
        try:
            sig_data = self.api.join_paid(game_id)
            logger.info("Got EIP-712 signature for paid game.")
            logger.warning("Paid game requires on-chain transaction.")
            logger.info(f"UUID: {sig_data.get('uuid')}")
            logger.info(f"AgentId: {sig_data.get('agentId')}")
            logger.info("Please complete the on-chain transaction to join.")

            # Wait for auto-registration after on-chain tx
            logger.info("Waiting for on-chain registration confirmation...")
            for _ in range(60):  # Wait up to 5 minutes
                if not self._running:
                    return ""
                account = self.api.get_account_info()
                for game in account.get("currentGames", []):
                    if game.get("gameId") == game_id:
                        return game.get("agentId", "")
                time.sleep(5)

            logger.error("Paid game join timed out.")
            return ""

        except APIError as e:
            logger.error(f"Paid game join failed: {e}")
            return ""

    def _try_create_game(self) -> str:
        """Try to create a new game room safely. Returns game_id or empty string."""
        with CREATE_GAME_LOCK:
            # Double check if someone else in another thread just created it while we waited for the lock
            try:
                games = self.api.list_games("waiting")
                matching = [g for g in games if g.get("entryType", "free") == self.room_type]
                if self.room_name:
                    matching = [g for g in matching if g.get("name", "") == self.room_name]
                
                if matching:
                    # Someone else created it! Cleanly exit so we can join it on the next loop phase.
                    return ""
            except Exception:
                pass # Ignore list errors and proceed to creation

            try:
                host_name = self.room_name if self.room_name else f"{self.agent_name}'s Room"
                game_data = self.api.create_game(
                    host_name=host_name,
                    entry_type=self.room_type,
                )
                game_id = game_data.get("id", "")
                if game_id:
                    SHARED_STATE.set_game(game_id)  # Broadcast to peers instantly!
                    print("")  # New line after waiting indicator
                    logger.success(f"Created new {self.room_type} game room!", logger.SYM_STAR)
                return game_id

            except APIError as e:
                if e.code == "WAITING_GAME_EXISTS":
                    pass  # Normal — will find it on next poll
                else:
                    logger.warning(f"Could not create game: {e}")
                return ""

    def _log_active_game_status(self, game_id: str, agent_id: str):
        """Log detailed info about the active game this agent is already in."""
        room_label = self.room_type.upper()

        if not game_id:
            logger.info(
                f"[WAIT] Sudah terdaftar di {room_label} game yang sedang berlangsung. "
                f"Menunggu game selesai sebelum join game baru..."
            )
            return

        short_id = game_id[:8]

        # Try to get game state for more details
        try:
            if agent_id:
                state = self.api.get_agent_state(game_id, agent_id)
                game_status = state.get("gameStatus", "unknown")
                current_turn = state.get("turn", "?")
                max_turns = state.get("maxTurns", 56)
                alive_agents = state.get("aliveAgentsCount", "?")
                total_agents = state.get("totalAgentsCount", "?")

                if game_status == "running":
                    logger.info(
                        f"[WAIT] {room_label} game [{short_id}...] sedang berlangsung - "
                        f"Turn {current_turn}/{max_turns}, "
                        f"Agents hidup: {alive_agents}/{total_agents}. "
                        f"Harap tunggu game selesai."
                    )
                elif game_status == "waiting":
                    logger.info(
                        f"[WAIT] {room_label} game [{short_id}...] menunggu pemain - "
                        f"Players: {total_agents}/? "
                        f"Harap tunggu game dimulai."
                    )
                else:
                    logger.info(
                        f"[WAIT] {room_label} game [{short_id}...] status: {game_status}. "
                        f"Harap tunggu game selesai."
                    )
                return
        except APIError as e:
            if "AGENT_NOT_FOUND" in str(e):
                logger.warning(
                    f"[WAIT] {room_label} game [{short_id}...] agent record removed. "
                    f"Match is likely finishing up. Please wait..."
                )
                return
        except Exception:
            pass

        # Fallback with game ID but no state details
        logger.info(
            f"[WAIT] {room_label} game [{short_id}...] sedang berlangsung. "
            f"Harap tunggu game selesai."
        )

    def _get_current_game_ids(self) -> tuple:
        """Get game_id and agent_id from current active game."""
        try:
            account = self.api.get_account_info()

            # currentGames is empty list from API — can't get game details
            # Just try known field names as list

            # Try multiple possible field names for current games
            games = []
            for key in ("currentGames", "activeGames", "games"):
                val = account.get(key)
                if isinstance(val, list) and val:
                    games = val
                    break

            for game in games:
                entry_type = game.get("entryType", game.get("type", "free"))
                if entry_type == self.room_type:
                    gid = game.get("gameId", game.get("game_id", game.get("id", "")))
                    aid = game.get("agentId", game.get("agent_id", ""))
                    return gid, aid

            # If we have games but none match room type, return the first one
            if games:
                game = games[0]
                gid = game.get("gameId", game.get("game_id", game.get("id", "")))
                aid = game.get("agentId", game.get("agent_id", ""))
                return gid, aid

        except APIError:
            pass
        return None, None

    def _get_agent_id_for_game(self, game_id: str) -> str:
        """Get agent_id for a specific game from account info."""
        try:
            account = self.api.get_account_info()
            for game in account.get("currentGames", []):
                if game.get("gameId") == game_id:
                    return game.get("agentId", "")
        except APIError:
            pass
        return ""

    def _wait_for_game_finish(self, game_id: str):
        """Wait for a running game to finish (used when agent is dead in that game)."""
        self._dash_status("waiting_death")
        while self._running:
            try:
                # Re-check account to see if the game is still in currentGames
                account = self.api.get_account_info()
                current_games = account.get("currentGames", [])
                still_in_game = False
                for game in current_games:
                    if game.get("gameId") == game_id:
                        game_status = game.get("gameStatus", "")
                        if game_status == "finished":
                            logger.info(f"Game [{game_id[:8]}...] has finished. Ready for next game.")
                            return
                        still_in_game = True
                        break

                if not still_in_game:
                    # Game no longer in currentGames — it must have finished
                    logger.info(f"Game [{game_id[:8]}...] no longer active. Ready for next game.")
                    return

                logger.info(
                    f"Waiting for game [{game_id[:8]}...] to finish...",
                    logger.SYM_CLOCK
                )
                self._sleep_interruptible(30)  # Check every 30s, no rush

            except APIError:
                self._sleep_interruptible(30)

    def _is_agent_alive(self, game_id: str, agent_id: str) -> bool:
        """Check if agent is still alive in a game."""
        try:
            account = self.api.get_account_info()
            for game in account.get("currentGames", []):
                if game.get("gameId") == game_id:
                    return game.get("isAlive", True)
        except APIError:
            pass
        return True  # Assume alive if can't check

    def _wait_for_game_start_by_id(self, game_id: str):
        """Wait for a specific game to start."""
        while self._running:
            try:
                game_info = self.api.get_game_info(game_id)
                status = game_info.get("status", "waiting")
                agent_count = game_info.get("agentCount", 0)
                max_agents = game_info.get("maxAgents", 100)

                if status == "running":
                    logger.success("Game has started!", logger.SYM_FIRE)
                    return

                if status == "finished":
                    logger.info("Game already finished.")
                    return

                logger.info(
                    f"Waiting for game to start... ({agent_count}/{max_agents} agents)",
                    logger.SYM_CLOCK
                )
                self._sleep_interruptible(10)

            except APIError:
                self._sleep_interruptible(15)

    def _sleep_interruptible(self, seconds: float):
        """Sleep but can be interrupted by stop()."""
        end_time = time.time() + seconds
        while time.time() < end_time and self._running:
            time.sleep(min(1.0, end_time - time.time()))

    def _dash_status(self, status: str):
        """Push status update to dashboard."""
        try:
            from src.dashboard.dashboard_state import state as dash
            label = self._agent_label or self.agent_name
            if label:
                dash.update_agent_status(label, status)
        except Exception:
            pass
