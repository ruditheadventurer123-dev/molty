"""
Molty Royale AI Bot — Game Loop
Main 60-second turn cycle: state polling, free actions, main action, data logging.
"""

import time
from src.api_client import MoltyAPIClient, APIError
from src.models import GameState
from src.strategy.decision_engine import engine as decision_engine
from src.strategy import inventory, combat
from src.ml.data_collector import collector as data_collector
from src import logger

try:
    from src.dashboard.dashboard_state import state as dashboard_state
except Exception:
    dashboard_state = None


class Bot:
    """Main game loop executor."""

    def __init__(self, api_client: MoltyAPIClient):
        self.api = api_client
        self.game_id = ""
        self.agent_id = ""
        self.agent_name = ""
        self.turn_count = 0
        self._running = True
        self._agent_label = ""  # Set from multi_runner
        self._game_name = ""   # Room name for dashboard

    def stop(self):
        """Signal the bot to stop gracefully."""
        self._running = False

    def play_game(self, game_id: str, agent_id: str, agent_name: str):
        """
        Main game loop. Blocks until game ends, agent dies, or bot is stopped.
        """
        self.game_id = game_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.turn_count = 0
        self._running = True
        self._prev_kills = 0       # Track kills for kill feed detection
        self._prev_visible = []    # Track visible agents for kill detection
        self._prev_visible_agents = []
        self._prev_visible_monsters = []

        # Reset decision engine for new game
        decision_engine.reset()

        # Start data collection
        data_collector.start_game(game_id, agent_name)

        logger.separator("=")
        logger.info(f"Game loop started. Agent: {agent_name}", logger.SYM_BOT)
        logger.info(f"Waiting for game to start...")
        logger.separator("-")

        # Wait for game to start (if still waiting)
        if not self._wait_for_game_start():
            return

        # Main game loop
        while self._running:
            try:
                self.turn_count += 1
                logger.turn_header(self.turn_count)

                # Step 1: Get state
                raw_state = self.api.get_agent_state(self.game_id, self.agent_id)
                state = GameState.from_api_response(raw_state)

                # Step 2: Check game over / death
                if state.is_finished:
                    self._handle_game_end(state)
                    return

                if not state.is_alive:
                    self._handle_death(state)
                    return

                if not state.is_running:
                    logger.info("Game not running yet, waiting...")
                    time.sleep(10)
                    self.turn_count -= 1  # Don't count this as a turn
                    continue

                # Print status bar
                logger.status_bar(
                    state.self_agent.hp, state.self_agent.max_hp,
                    state.self_agent.ep, state.self_agent.max_ep,
                    state.self_agent.kills, self.turn_count,
                    state.current_region.name,
                    state.self_agent.weapon_name,
                )

                # Step 3: FREE ACTIONS (no cooldown, no EP cost)
                self._execute_free_actions(state)

                # Re-fetch state after free actions (inventory may have changed)
                raw_state = self.api.get_agent_state(self.game_id, self.agent_id)
                state = GameState.from_api_response(raw_state)

                # Step 4: MAIN ACTION (1 per turn)
                decision = decision_engine.decide(state)
                action = decision["action"]
                reasoning = decision["reasoning"]
                planned = decision["planned"]

                logger.action(action.get("type", "unknown"), reasoning)

                # Push state + action to dashboard
                self._push_dashboard_state(state, action.get("type", ""), reasoning)

                # Detect kills for kill feed
                self._detect_kills(state, action)

                try:
                    self.api.send_main_action(
                        self.game_id, self.agent_id,
                        action, reasoning, planned
                    )
                except APIError as e:
                    if e.code == "COOLDOWN_ACTIVE":
                        logger.warning("Cooldown still active, waiting...")
                    elif e.code == "INSUFFICIENT_EP":
                        logger.warning(f"Insufficient EP for {action.get('type')}. Resting next turn.")
                    elif e.code == "AGENT_DEAD":
                        logger.critical("Agent died!")
                        self._handle_death(state)
                        return
                    else:
                        logger.error(f"Action failed: {e}")

                # Step 5: Log turn data for ML
                self._log_turn_data(state, action, reasoning)

                # Step 6: Wait for next turn
                logger.info(f"Waiting 60s for next turn...", logger.SYM_CLOCK)
                self._sleep_interruptible(60)

            except APIError as e:
                logger.error(f"API error: {e}")
                if e.code in ("GAME_NOT_FOUND", "AGENT_NOT_FOUND"):
                    logger.critical("Game or agent not found. Exiting game loop.")
                    return
                # Retry after a brief pause
                self._sleep_interruptible(10)

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self._sleep_interruptible(10)

    def _wait_for_game_start(self) -> bool:
        """Poll until game starts. Returns True if game started, False if stopped."""
        while self._running:
            try:
                raw_state = self.api.get_agent_state(self.game_id, self.agent_id)
                state = GameState.from_api_response(raw_state)

                if state.is_running:
                    if not state.is_alive:
                        # Agent is already dead in this running game
                        logger.info("Game is running but agent is already dead.")
                        return False
                    logger.success("Game has started!", logger.SYM_FIRE)
                    return True

                if state.is_finished:
                    logger.info("Game already finished.")
                    return False

                # Still waiting
                self._sleep_interruptible(10)

            except APIError as e:
                if e.code == "GAME_NOT_FOUND":
                    logger.error("Game not found! It may have been cancelled.")
                    return False
                logger.warning(f"Error checking game status: {e}")
                self._sleep_interruptible(15)
            except Exception as e:
                logger.warning(f"Error: {e}")
                self._sleep_interruptible(15)

        return False

    def _execute_free_actions(self, state: GameState):
        """Execute all free actions (pickup, equip, respond to messages)."""
        agent = state.self_agent

        # 1. Pickup items in current region (currency first)
        items_to_pickup = inventory.get_items_to_pickup(state)
        # Build item ID→info map for recording
        item_map = {}
        for vi in state.items_in_region():
            item_map[vi.item.id] = vi.item
        for item_id in items_to_pickup:
            try:
                self.api.pickup_item(self.game_id, self.agent_id, item_id)
                item_obj = item_map.get(item_id)
                item_name = item_obj.name if item_obj else "Unknown"
                item_cat = item_obj.category if item_obj else "unknown"
                logger.action("pickup", f"Picked up {item_name}")
                data_collector.record_item_pickup(item_name, item_cat)
            except APIError as e:
                if e.code != "INVALID_ITEM":  # Item may already be taken
                    logger.warning(f"Pickup failed: {e}")

        # 2. Equip best weapon
        best_weapon = inventory.should_equip_weapon(agent)
        if best_weapon:
            try:
                self.api.equip_weapon(self.game_id, self.agent_id, best_weapon.id)
                logger.action("equip", f"Equipped {best_weapon.name} (+{best_weapon.atk_bonus} ATK)")
            except APIError:
                pass

        # 3. Respond to messages
        for msg in state.recent_messages:
            if msg.sender_id != agent.id:
                try:
                    if msg.type == "private":
                        self.api.whisper(
                            self.game_id, self.agent_id, msg.sender_id,
                            "Got it. Let's work together."
                        )
                    elif msg.type == "regional":
                        self.api.talk(
                            self.game_id, self.agent_id,
                            "Looking for allies against common threats."
                        )
                except APIError:
                    pass  # Non-critical

    def _handle_game_end(self, state: GameState):
        """Handle game over."""
        result = state.result
        is_winner = False
        if result:
            is_winner = result.is_winner
            logger.game_result(
                result.final_rank, state.self_agent.kills,
                result.rewards, result.is_winner
            )
            data_collector.end_game({
                "is_winner": result.is_winner,
                "final_rank": result.final_rank,
                "kills": state.self_agent.kills,
                "rewards": result.rewards,
            })
        else:
            logger.info("Game finished (no result data available).")
            data_collector.end_game({
                "is_winner": False, "final_rank": 0,
                "kills": state.self_agent.kills, "rewards": 0,
            })

        # Update dashboard: increment counters + reset panel
        if dashboard_state:
            dashboard_state.increment_games()
            if is_winner:
                dashboard_state.increment_wins()
            self._reset_dashboard_panel()

    def _handle_death(self, state: GameState):
        """Handle agent death."""
        logger.critical(f"Agent {self.agent_name} has been eliminated!")
        logger.info(f"Final stats - Kills: {state.self_agent.kills}")

        # Estimate rank: alive agents + 1 (we just died)
        alive_count = sum(1 for a in state.visible_agents if a.is_alive) + 1
        estimated_rank = alive_count + 1  # We placed one below the alive agents

        data_collector.end_game({
            "is_winner": False, "final_rank": estimated_rank,
            "kills": state.self_agent.kills, "rewards": 0,
        })

        # Update dashboard: increment games + reset panel
        if dashboard_state:
            dashboard_state.increment_games()
            self._reset_dashboard_panel()

    def _log_turn_data(self, state: GameState, action: dict, reasoning: str):
        """Log turn data for ML collection."""
        agent = state.self_agent
        data_collector.record_turn(
            self.turn_count,
            {
                "hp": agent.hp,
                "max_hp": agent.max_hp,
                "ep": agent.ep,
                "atk": agent.atk,
                "def": agent.def_,
                "kills": agent.kills,
                "region_id": agent.region_id,
                "region_terrain": state.current_region.terrain,
                "is_death_zone": state.current_region.is_death_zone,
                "weapon": agent.weapon_name,
                "weapon_bonus": agent.weapon_atk_bonus,
                "inventory_count": agent.inventory_count,
                "visible_agents": len(state.visible_agents),
                "visible_monsters": len(state.visible_monsters),
            },
            action,
            reasoning,
        )

        # Record combat events if we attacked
        if action.get("type") == "attack":
            target_id = action.get("targetId", "")
            target_type = action.get("targetType", "")

            our_stats = {
                "hp": agent.hp, "atk": agent.atk,
                "def": agent.def_, "weapon": agent.weapon_name,
                "weapon_bonus": agent.weapon_atk_bonus,
            }

            if target_type == "agent":
                for enemy in state.visible_agents:
                    if enemy.id == target_id:
                        enemy_stats = {
                            "hp": enemy.hp, "atk": enemy.atk,
                            "def": enemy.def_, "weapon": enemy.weapon_name,
                            "weapon_bonus": enemy.weapon_atk_bonus,
                            "has_healing": len(enemy.get_recovery_items()) > 0,
                            "healing_potential": enemy.estimate_healing_potential(),
                        }
                        data_collector.record_combat(our_stats, enemy_stats, "pending")
                        break
            elif target_type == "monster":
                for monster in state.visible_monsters:
                    if monster.id == target_id:
                        enemy_stats = {
                            "hp": monster.hp, "atk": monster.atk,
                            "def": monster.def_, "weapon": "Fist",
                            "weapon_bonus": 0,
                        }
                        data_collector.record_combat(our_stats, enemy_stats, "pending")
                        break

    def _sleep_interruptible(self, seconds: float):
        """Sleep but can be interrupted by stop()."""
        end_time = time.time() + seconds
        while time.time() < end_time and self._running:
            time.sleep(min(1.0, end_time - time.time()))

    def _push_dashboard_state(self, state: GameState, last_action: str = "",
                              last_action_detail: str = ""):
        """Push current agent state to the dashboard."""
        if not dashboard_state:
            return
        try:
            agent = state.self_agent
            label = self._agent_label or self.agent_name

            # Format inventory as simple strings
            inv_list = []
            for item in agent.inventory:
                if item.is_weapon:
                    inv_list.append(f"{item.name} (+{item.atk_bonus})")
                elif item.is_currency:
                    inv_list.append("$Moltz")
                else:
                    inv_list.append(item.name)

            # Format visible entities as simple strings
            enemies = []
            for e in state.visible_agents:
                w = e.weapon_name if e.equipped_weapon else 'Fist'
                enemies.append(f"{e.name} [{e.hp}] {w}")

            monsters = []
            for m in state.visible_monsters:
                monsters.append(f"{m.name} [{m.hp}]")

            items = []
            for vi in state.visible_items:
                if vi.region_id == agent.region_id:
                    items.append(f"{vi.item.name}")

            dashboard_state.update_agent_state(label, {
                "name": agent.name,
                "status": "playing" if state.is_running and agent.is_alive else (
                    "dead" if not agent.is_alive else "waiting"),
                "hp": agent.hp,
                "max_hp": agent.max_hp,
                "ep": agent.ep,
                "max_ep": agent.max_ep,
                "atk": agent.atk,
                "def": agent.def_,
                "vision": agent.vision,
                "kills": agent.kills,
                "weapon": agent.weapon_name,
                "weapon_bonus": agent.weapon_atk_bonus,
                "region_name": state.current_region.name,
                "terrain": state.current_region.terrain,
                "weather": state.current_region.weather,
                "game_name": f"{self._game_name} (ID: {self.game_id})" if self._game_name and self.game_id else self._game_name or "",
                "turn": self.turn_count,
                "last_action": last_action,
                "last_action_detail": last_action_detail,
                "inventory": inv_list,
                "visible_agents": enemies,
                "visible_monsters": monsters,
                "visible_items": items,
                "is_death_zone": state.current_region.is_death_zone,
            })
        except Exception:
            pass  # Non-critical

    def _reset_dashboard_panel(self):
        """Reset dashboard panel to idle/default state after game ends."""
        if not dashboard_state:
            return
        try:
            label = self._agent_label or self.agent_name
            dashboard_state.update_agent_state(label, {
                "status": "idle",
                "hp": 0, "max_hp": 100, "ep": 0, "max_ep": 10,
                "atk": 0, "def": 0, "vision": 0, "kills": 0,
                "weapon": "Fist", "weapon_bonus": 0,
                "region_name": "-", "terrain": "", "weather": "",
                "game_name": "", "turn": 0,
                "last_action": "", "last_action_detail": "",
                "inventory": [],
                "visible_agents": [], "visible_monsters": [], "visible_items": [],
                "is_death_zone": False,
            })
        except Exception:
            pass

    def _detect_kills(self, state: GameState, action: dict):
        """Detect kills by comparing kill count between turns and push to kill feed."""
        if not dashboard_state:
            return
        try:
            current_kills = state.self_agent.kills
            label = self._agent_label or self.agent_name

            if current_kills > self._prev_kills:
                # We got a kill! Determine victim
                victim_name = "Unknown"
                weapon = state.self_agent.weapon_name
                is_monster = False

                action_type = action.get("type", "")
                target_type = action.get("targetType", "")

                if action_type == "attack" and target_type == "monster":
                    # Killed a monster
                    target_id = action.get("targetId", "")
                    for m in self._prev_visible_monsters:
                        if m.get("id") == target_id:
                            victim_name = m.get("name", "Monster")
                            break
                    is_monster = True
                elif action_type == "attack" and target_type == "agent":
                    # Killed an agent
                    target_id = action.get("targetId", "")
                    for a in self._prev_visible_agents:
                        if a.get("id") == target_id:
                            victim_name = a.get("name", "Agent")
                            break
                else:
                    # Kill from retaliation or other means
                    # Check which previously visible agents disappeared
                    prev_names = {a.get("id"): a.get("name", "Agent") for a in self._prev_visible_agents}
                    current_ids = {a.id for a in state.visible_agents if a.is_alive}
                    for aid, aname in prev_names.items():
                        if aid not in current_ids:
                            victim_name = aname
                            break

                dashboard_state.push_kill(
                    killer=state.self_agent.name,
                    victim=victim_name,
                    weapon=weapon,
                    is_monster=is_monster,
                    agent_label=label,
                )

            # Also detect if WE were killed by someone (our HP dropped and we died)
            # This is handled in _handle_death

            # Store current state for next turn comparison
            self._prev_kills = current_kills
            self._prev_visible_agents = [
                {"id": a.id, "name": a.name} for a in state.visible_agents
            ]
            self._prev_visible_monsters = [
                {"id": m.id, "name": m.name} for m in state.visible_monsters
            ]
        except Exception:
            pass
