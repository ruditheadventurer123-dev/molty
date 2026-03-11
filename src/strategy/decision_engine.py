"""
Molty Royale AI Bot — Decision Engine
Main priority-based decision tree. The brain of the bot.

Priority Order:
1. ESCAPE DEATH ZONE (ABSOLUTE — never stay in death/pending death zone)
2. CRITICAL HEALING (HP < threshold, phase-aware)
2.5 RETALIATION (if we were attacked, fight back!)
3. EP MANAGEMENT (rest if too low)
3.5 CROWDED REGION ESCAPE (4+ agents, mid/late game)
4. WEAPON HUNTING (early/mid game, still using Fist → kill monsters for drops)
5. COMBAT (aggressive, kills = ranking; late game uses ML)
6. STRATEGIC POSITIONING (only if enemies visible, max 2/game)
6.5 HEALING ITEM SEARCH (mid game, low on heals)
7. LOOT & EXPLORE (facilities, unexplored regions)
8. MOVEMENT (toward strategic position, deep safety in mid/late)
DEFAULT: explore current region
"""

from typing import Optional
from src.models import GameState
from src.strategy import combat, movement, exploration, inventory
from src.strategy.inventory import get_game_phase, get_healing_items_count
from src.config import (
    load_strategy_weights, CROWDED_AGENT_THRESHOLD,
    EARLY_GAME_END, MID_GAME_END,
)
from src import logger


class DecisionEngine:
    """Priority-based decision engine for the AI agent."""

    def __init__(self):
        self.exploration_tracker = exploration.ExplorationTracker()
        self.turn_count = 0
        self.last_action_type = ""
        self.last_hp = 100  # Track HP to detect attacks
        self.ambush_count = 0  # Limit ambush moves per game
        self._late_game_predictor = None  # Lazy loaded
        self.MAX_AMBUSH_PER_GAME = 2  # Max ambush positioning moves

    def reset(self):
        """Reset for a new game."""
        self.exploration_tracker.reset()
        self.turn_count = 0
        self.last_action_type = ""
        self.last_hp = 0  # 0 = first turn, won't trigger false retaliation
        self.ambush_count = 0

    def _get_late_game_predictor(self):
        """Lazy load late game predictor to avoid circular imports."""
        if self._late_game_predictor is None:
            try:
                from src.ml.late_game_predictor import late_game_predictor
                self._late_game_predictor = late_game_predictor
            except ImportError:
                pass
        return self._late_game_predictor

    def decide(self, state: GameState) -> dict:
        """
        Main decision function. Returns action dict and reasoning.
        Returns: {"action": {...}, "reasoning": str, "planned": str}
        """
        self.turn_count += 1
        agent = state.self_agent
        region = state.current_region
        weights = load_strategy_weights()
        game_phase = get_game_phase(self.turn_count)
        agents_here = len(state.agents_in_region())

        # Detect if we were attacked (HP dropped without our action)
        hp_lost = max(0, self.last_hp - agent.hp)
        was_attacked = hp_lost > 0 and self.last_action_type != "attack" and self.last_hp > 0
        self.last_hp = agent.hp  # Update for next turn

        # Track visited
        self.exploration_tracker.mark_visited(region.id)

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 1: ESCAPE DEATH ZONE (ABSOLUTE)
        # NEVER stay in death zone or pending death zone
        # ═══════════════════════════════════════════════════════════
        if state.in_death_zone:
            logger.death_zone_alert(region.name, is_pending=False)
            escape_id = movement.find_escape_route(state)
            if escape_id:
                return self._action(
                    {"type": "move", "regionId": escape_id},
                    f"EMERGENCY: In death zone ({region.name})! Taking 1.34 HP/sec damage!",
                    "Escaping to safe region immediately"
                )
            else:
                # Trapped — try to heal or rest
                heal = inventory.should_heal(agent, game_phase, agents_here)
                if heal:
                    return self._action(
                        {"type": "use_item", "itemId": heal.id},
                        "Trapped in death zone! Healing to survive",
                        "Attempting to survive death zone"
                    )
                return self._action(
                    {"type": "rest"},
                    "Trapped in death zone with no escape! Resting",
                    "No escape route available"
                )

        if state.in_pending_death_zone:
            logger.death_zone_alert(region.name, is_pending=True)
            escape_id = movement.find_escape_route(state)
            if escape_id:
                return self._action(
                    {"type": "move", "regionId": escape_id},
                    f"Pending death zone ({region.name})! Pre-emptive evacuation",
                    "Moving to safe region before death zone expands"
                )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 2: CRITICAL HEALING (Phase-aware — Upgrade 2)
        # Early: HP<40 | Mid: HP<50 | Late: HP<70% | Chaos: HP<60
        # ═══════════════════════════════════════════════════════════
        heal_item = inventory.should_heal(agent, game_phase, agents_here)
        if heal_item and agent.ep >= 1:
            # Check conservation: should we save this item?
            healing_count = get_healing_items_count(agent)
            should_conserve = inventory.should_conserve_healing(
                agent, game_phase, healing_count
            )
            if not should_conserve:
                phase_note = f" [{game_phase} game]"
                chaos_note = f" [CHAOS: {agents_here} agents nearby]" if agents_here >= 3 else ""
                return self._action(
                    {"type": "use_item", "itemId": heal_item.id},
                    f"Healing HP ({agent.hp}/{agent.max_hp}){phase_note}{chaos_note} with {heal_item.name}",
                    f"Restoring HP (+{heal_item.hp_restore})"
                )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 2.5: RETALIATION (Fix 4 — fight back!)
        # If we were attacked and there are agents here → attack back
        # ═══════════════════════════════════════════════════════════
        if was_attacked and agents_here > 0 and agent.ep >= 2:
            enemies = state.agents_in_region()
            if enemies:
                # Attack the lowest HP enemy (easiest kill)
                target_enemy = min(enemies, key=lambda e: e.hp)
                analysis = combat.get_combat_analysis(agent, target_enemy)
                logger.combat_analysis(
                    analysis["target_name"], analysis["target_hp"],
                    analysis["win_probability"], analysis["our_damage"],
                    analysis["their_damage"], analysis["has_healing"],
                )
                # Only retaliate if we have a reasonable chance (>15%)
                # Otherwise fall through to normal priority (flee/heal)
                if analysis["win_probability"] >= 0.15:
                    return self._action(
                        {"type": "attack", "targetId": target_enemy.id,
                         "targetType": "agent"},
                        f"RETALIATION! Lost {hp_lost}HP → attacking {target_enemy.name} (HP:{target_enemy.hp})",
                        f"Fighting back — win prob: {analysis['win_probability']:.0%}"
                    )
                else:
                    logger.warning(
                        f"Attacked but too weak to retaliate (win: {analysis['win_probability']:.0%}). "
                        f"Seeking escape or healing instead."
                    )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 3: EP MANAGEMENT
        # ═══════════════════════════════════════════════════════════
        if agent.ep < 2:
            # Check for energy drink first
            energy = inventory.should_use_energy_drink(agent)
            if energy and agent.ep >= 1:
                return self._action(
                    {"type": "use_item", "itemId": energy.id},
                    f"Low EP ({agent.ep}). Using Energy Drink (+5 EP)",
                    "Restoring EP for combat capability"
                )
            # Rest for +1 bonus EP
            if not self._has_combat_threat(state):
                return self._action(
                    {"type": "rest"},
                    f"Low EP ({agent.ep}). Resting for +1 bonus EP",
                    "Recovering EP for next turn"
                )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 3.5: CROWDED REGION ESCAPE (Upgrade 3)
        # If 4+ agents in region AND mid/late game → consider fleeing
        # ═══════════════════════════════════════════════════════════
        if agents_here >= CROWDED_AGENT_THRESHOLD and game_phase in ("mid", "late"):
            # Low HP → flee
            if agent.hp_percent < 0.5 and agent.ep >= 1:
                escape_id = movement.find_safe_escape_from_crowd(state)
                if escape_id:
                    logger.warning(
                        f"CROWDED: {agents_here} agents in {region.name}! "
                        f"HP low ({agent.hp}/{agent.max_hp}), fleeing!"
                    )
                    return self._action(
                        {"type": "move", "regionId": escape_id},
                        f"[CROWDED] {agents_here} agents in region, HP low — evacuating",
                        "Fleeing crowded region to survive"
                    )

            # Medium HP → heal first if possible
            if agent.hp_percent < 0.7:
                heal = inventory.should_heal(agent, "late", agents_here)
                if heal and agent.ep >= 1:
                    return self._action(
                        {"type": "use_item", "itemId": heal.id},
                        f"[CROWDED] {agents_here} agents nearby, healing before combat",
                        f"Preparing for chaos war (+{heal.hp_restore} HP)"
                    )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 4: WEAPON HUNTING (Fix 2 — early/mid game must get weapon)
        # If still using Fist → hunt monsters for weapon drops
        # AVOID death zones / pending death zones
        # ═══════════════════════════════════════════════════════════
        has_no_weapon = agent.weapon_atk_bonus == 0  # Fist = 0 bonus
        in_danger = state.in_death_zone or state.in_pending_death_zone
        if has_no_weapon and game_phase in ("early", "mid") and agent.ep >= 2:
            # Don't hunt in death zones
            if not in_danger:
                # Priority: kill monsters for weapon drops (Wolf→Knife/Bow, Bear→Sword/Pistol)
                for monster in state.monsters_in_region():
                    analysis = combat.get_combat_analysis(agent, monster)
                    # Be more aggressive with monsters when we need weapons
                    if analysis["win_probability"] >= 0.4 or monster.hp <= 10:
                        logger.combat_analysis(
                            analysis["target_name"], analysis["target_hp"],
                            analysis["win_probability"], analysis["our_damage"],
                            analysis["their_damage"], analysis["has_healing"],
                        )
                        return self._action(
                            {"type": "attack", "targetId": monster.id,
                             "targetType": "monster"},
                            f"WEAPON HUNT: Killing {monster.name} (HP:{monster.hp}) for weapon drops!",
                            f"Need weapon! {monster.name} drops Knife/Bow/Sword"
                        )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 5: COMBAT (Killer mode + flee awareness)
        # ═══════════════════════════════════════════════════════════
        if inventory.can_attack(agent):
            # Check if we should FLEE instead of fight
            if combat.should_flee_instead(state):
                escape_id = movement.find_safe_escape_from_crowd(state)
                if escape_id and agent.ep >= 1:
                    logger.warning(
                        f"DANGER: {agents_here} enemies in death zone! Fleeing!"
                    )
                    return self._action(
                        {"type": "move", "regionId": escape_id},
                        f"[FLEE] In danger zone with {agents_here} enemies — evacuating!",
                        "Survival over combat in death zone"
                    )

            # Late game with multiple enemies → consult ML
            if game_phase == "late" and agents_here >= 3:
                ml_decision = self._late_game_ml_decision(state)
                if ml_decision:
                    return ml_decision

            target = combat.select_best_target(state)
            if target:
                # Log combat analysis
                logger.combat_analysis(
                    target["target_name"],
                    target["target_hp"],
                    target["win_probability"],
                    target["our_damage"],
                    target["their_damage"],
                    target["has_healing"],
                )

                # Check if target is in a dangerous region
                target_region = None
                if target["target_type"] == "agent":
                    for a in state.visible_agents:
                        if a.id == target["target_id"]:
                            target_region = a.region_id
                            break
                elif target["target_type"] == "monster":
                    for m in state.visible_monsters:
                        if m.id == target["target_id"]:
                            target_region = m.region_id
                            break

                # ABSOLUTE: if target is in pending/actual death zone, don't fight there
                in_dangerous_region = False
                if target_region:
                    in_dangerous_region = not movement.is_region_safe(target_region, state)

                if not in_dangerous_region:
                    healing_note = ""
                    if target["has_healing"]:
                        healing_note = f" (enemy has ~{target['healing_potential']}HP healing)"

                    mode_tag = "[KILLER] " if agent.weapon_atk_bonus > 0 else ""
                    return self._action(
                        {"type": "attack", "targetId": target["target_id"],
                         "targetType": target["target_type"]},
                        f"{mode_tag}Attacking {target['target_name']} (HP:{target['target_hp']}{healing_note}). "
                        f"Win prob: {target['win_probability']:.0%}",
                        f"Combat: {target['our_damage']} dmg/hit, need {target['hits_to_kill']} hits"
                    )
                else:
                    logger.warning(f"Target {target['target_name']} is in death/pending zone — skipping combat, evacuating!")

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 6: STRATEGIC POSITIONING (Fix 3 — only with enemies visible)
        # Only ambush if enemies are actually nearby AND under limit
        # ═══════════════════════════════════════════════════════════
        if self.ambush_count < self.MAX_AMBUSH_PER_GAME:
            edge_regions = movement.get_death_zone_edge_regions(state)
            # Only ambush if we can see enemies fleeing nearby
            visible_enemy_count = len(state.visible_agents)
            if edge_regions and agent.ep >= 1 and visible_enemy_count > 0:
                for er in edge_regions:
                    if er.id != region.id and movement.is_region_safe(er.id, state):
                        self.ambush_count += 1
                        return self._action(
                            {"type": "move", "regionId": er.id},
                            f"Ambush positioning ({er.name}) — {visible_enemy_count} enemies visible",
                            "Intercepting enemies fleeing death zone"
                        )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 5.5: HEALING ITEM SEARCH (Upgrade 5)
        # Mid game + low on heals → search for recovery items
        # ═══════════════════════════════════════════════════════════
        if inventory.should_seek_healing_items(agent, game_phase) and agent.ep >= 1:
            # Check if there's a nearby region with healing items on ground
            heal_region = exploration.find_healing_item_region(state)
            if heal_region and heal_region != region.id:
                return self._action(
                    {"type": "move", "regionId": heal_region},
                    f"[HEAL SEARCH] Low on healing items, moving to pick up recovery",
                    "Seeking healing items for late game survival"
                )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 6: LOOT & EXPLORE
        # ═══════════════════════════════════════════════════════════
        # Use facilities
        facility = inventory.get_best_facility_to_use(state)
        if facility and agent.ep >= 1:
            return self._action(
                {"type": "interact", "interactableId": facility["interactableId"]},
                f"Using facility: {facility['type']}",
                "Interacting with facility for resources"
            )

        # Explore current region if not yet explored
        boost_healing = inventory.should_seek_healing_items(agent, game_phase)
        if exploration.should_explore_current(state, self.exploration_tracker) and agent.ep >= 1:
            return self._action(
                {"type": "explore"},
                f"Exploring {region.name} ({region.terrain})",
                "Searching for items and enemies"
            )

        # ═══════════════════════════════════════════════════════════
        # PRIORITY 7: MOVEMENT (deep safety in mid/late — Upgrade 1)
        # ═══════════════════════════════════════════════════════════
        if agent.ep >= 1:
            use_deep = game_phase in ("mid", "late")

            # Try exploration target first
            explore_target = exploration.get_exploration_target(
                state, self.exploration_tracker,
                boost_healing=boost_healing
            )
            if explore_target:
                return self._action(
                    {"type": "move", "regionId": explore_target},
                    f"Moving to unexplored/valuable region",
                    "Seeking items and strategic advantage"
                )

            # Fall back to strategic position (with deep safety in mid/late)
            strat_target = movement.find_strategic_position(
                state, self.exploration_tracker.visited_regions,
                use_deep_safety=use_deep
            )
            if strat_target:
                return self._action(
                    {"type": "move", "regionId": strat_target},
                    "Moving to strategic position",
                    "Seeking better terrain and visibility"
                )

        # ═══════════════════════════════════════════════════════════
        # DEFAULT: explore or rest
        # ═══════════════════════════════════════════════════════════
        if agent.ep >= 1:
            return self._action(
                {"type": "explore"},
                "Default action: exploring current region",
                "No priority targets found"
            )

        return self._action(
            {"type": "rest"},
            "No EP and no priority. Resting",
            "Recovering EP"
        )

    # ─── Late Game ML Decision (Upgrade 4) ─────────────────────────
    def _late_game_ml_decision(self, state: GameState) -> Optional[dict]:
        """
        Use ML predictor for late-game fight/flee/heal decisions.
        Returns action dict if ML has high confidence, None to fall through.
        """
        predictor = self._get_late_game_predictor()
        if not predictor:
            return None

        try:
            from src.ml.late_game_predictor import extract_late_game_features
            features = extract_late_game_features(state, self.turn_count)
            action_name, confidence = predictor.predict(features)

            agent = state.self_agent
            agents_here = len(state.agents_in_region())

            # Record for training
            try:
                from src.ml.data_collector import collector
                collector.record_late_game_decision(
                    self.turn_count, features.tolist(),
                    action_name, f"ML confidence: {confidence:.2f}"
                )
            except Exception:
                pass

            # Only use ML decision if confidence is decent
            if confidence < 0.55:
                return None

            ml_tag = f"[ML:{confidence:.0%}]"

            if action_name == "heal":
                heal_item = inventory.should_heal(agent, "late", agents_here)
                if heal_item and agent.ep >= 1:
                    return self._action(
                        {"type": "use_item", "itemId": heal_item.id},
                        f"{ml_tag} Late game ML: heal before combat ({agents_here} enemies)",
                        f"ML predicts healing is optimal (+{heal_item.hp_restore} HP)"
                    )

            elif action_name == "flee":
                escape_id = movement.find_safe_escape_from_crowd(state)
                if escape_id and agent.ep >= 1:
                    return self._action(
                        {"type": "move", "regionId": escape_id},
                        f"{ml_tag} Late game ML: flee from {agents_here} enemies",
                        "ML predicts fleeing gives best survival odds"
                    )

            # action_name == "attack" falls through to normal combat logic
            return None

        except Exception:
            return None

    def _action(self, action: dict, reasoning: str, planned: str) -> dict:
        """Package action with reasoning."""
        self.last_action_type = action.get("type", "")
        return {
            "action": action,
            "reasoning": reasoning,
            "planned": planned,
        }

    def _has_combat_threat(self, state: GameState) -> bool:
        """Check if there are hostile agents in our region."""
        return len(state.agents_in_region()) > 0


# Singleton instance
engine = DecisionEngine()

