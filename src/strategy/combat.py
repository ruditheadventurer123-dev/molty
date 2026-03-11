"""
Molty Royale AI Bot — Combat Strategy
Damage calculation, win probability, target selection, enemy healing analysis.
"""

import math
from typing import Optional, Union
from src.models import AgentSelf, VisibleAgent, Monster, GameState
from src.config import RECOVERY_ITEMS, load_strategy_weights, FRIENDLY_AGENTS


def calculate_damage(attacker_atk: int, weapon_bonus: int, target_def: int) -> int:
    """
    Calculate combat damage using game formula.
    Damage = ATK + weapon_bonus - (target_DEF × 0.5)
    Minimum damage = 1
    """
    raw = attacker_atk + weapon_bonus - (target_def * 0.5)
    return max(1, int(raw))


def estimate_our_damage(agent: AgentSelf, target_def: int) -> int:
    """Calculate damage we deal to a target."""
    return calculate_damage(agent.atk, agent.weapon_atk_bonus, target_def)


def estimate_target_damage_to_us(target_atk: int, target_weapon_bonus: int, our_def: int) -> int:
    """Calculate damage a target deals to us."""
    return calculate_damage(target_atk, target_weapon_bonus, our_def)


def estimate_enemy_effective_hp(enemy: VisibleAgent) -> int:
    """
    Estimate enemy's effective HP including their healing items.
    Factors in visible recovery items in enemy inventory.
    """
    base_hp = enemy.hp
    healing = enemy.estimate_healing_potential()
    return base_hp + healing


def estimate_hits_to_kill(our_damage: int, target_hp: int) -> int:
    """How many attacks needed to kill target."""
    if our_damage <= 0:
        return 999
    return math.ceil(target_hp / our_damage)


def estimate_hits_to_die(their_damage: int, our_hp: int) -> int:
    """How many attacks from target needed to kill us."""
    if their_damage <= 0:
        return 999
    return math.ceil(our_hp / their_damage)


def calculate_win_probability_agent(agent: AgentSelf, enemy: VisibleAgent) -> float:
    """
    Calculate win probability against another agent.
    Factors: HP, damage exchange, weapon quality, enemy healing.
    Returns float 0.0 to 1.0.
    """
    our_dmg = estimate_our_damage(agent, enemy.def_)
    enemy_weapon_bonus = enemy.weapon_atk_bonus
    their_dmg = estimate_target_damage_to_us(enemy.atk, enemy_weapon_bonus, agent.def_)

    # Factor in enemy healing items — they effectively have more HP
    enemy_eff_hp = estimate_enemy_effective_hp(enemy)

    hits_to_kill = estimate_hits_to_kill(our_dmg, enemy_eff_hp)
    hits_to_die = estimate_hits_to_die(their_dmg, agent.hp)

    if hits_to_kill <= 0:
        return 1.0
    if hits_to_die <= 0:
        return 0.0

    # Core probability: ratio of how fast we kill vs how fast they kill us
    # If we kill in fewer hits than they kill us, we're likely to win
    kill_ratio = hits_to_die / hits_to_kill  # > 1 means we're favored

    # Sigmoid-like conversion to probability
    if kill_ratio >= 3.0:
        base_prob = 0.95
    elif kill_ratio >= 2.0:
        base_prob = 0.85
    elif kill_ratio >= 1.5:
        base_prob = 0.75
    elif kill_ratio >= 1.0:
        base_prob = 0.60
    elif kill_ratio >= 0.7:
        base_prob = 0.40
    elif kill_ratio >= 0.5:
        base_prob = 0.25
    else:
        base_prob = 0.10

    # HP advantage modifier
    hp_ratio = agent.hp / max(1, enemy.hp)
    hp_modifier = min(0.1, max(-0.1, (hp_ratio - 1.0) * 0.05))

    # Weapon range advantage: ranged vs melee is +bonus
    range_bonus = 0.0
    if agent.weapon_range > 0 and enemy.weapon_atk_bonus <= 5:
        range_bonus = 0.05  # We can hit from distance

    prob = base_prob + hp_modifier + range_bonus
    return max(0.0, min(1.0, prob))


def calculate_win_probability_monster(agent: AgentSelf, monster: Monster) -> float:
    """
    Calculate win probability against a monster.
    Monsters don't heal, so simpler calculation.
    """
    our_dmg = estimate_our_damage(agent, monster.def_)
    their_dmg = estimate_target_damage_to_us(monster.atk, 0, agent.def_)

    hits_to_kill = estimate_hits_to_kill(our_dmg, monster.hp)
    hits_to_die = estimate_hits_to_die(their_dmg, agent.hp)

    if hits_to_kill <= 1:
        return 0.98  # One-shot kill is almost guaranteed
    if hits_to_die <= hits_to_kill:
        return 0.2
    if hits_to_die >= hits_to_kill * 3:
        return 0.95

    ratio = hits_to_die / hits_to_kill
    return max(0.1, min(0.95, ratio / (ratio + 1)))


def enemy_has_healing(enemy: VisibleAgent) -> bool:
    """Check if enemy has visible healing items."""
    return enemy.estimate_healing_potential() > 0


def get_combat_analysis(agent: AgentSelf, target: Union[VisibleAgent, Monster]) -> dict:
    """
    Full combat analysis for a target.
    Returns dict with all calculated values for logging and decision-making.
    """
    if isinstance(target, VisibleAgent):
        our_dmg = estimate_our_damage(agent, target.def_)
        their_weapon_bonus = target.weapon_atk_bonus
        their_dmg = estimate_target_damage_to_us(target.atk, their_weapon_bonus, agent.def_)
        eff_hp = estimate_enemy_effective_hp(target)
        win_prob = calculate_win_probability_agent(agent, target)
        has_healing = enemy_has_healing(target)
        return {
            "target_name": target.name,
            "target_id": target.id,
            "target_type": "agent",
            "target_hp": target.hp,
            "target_effective_hp": eff_hp,
            "our_damage": our_dmg,
            "their_damage": their_dmg,
            "hits_to_kill": estimate_hits_to_kill(our_dmg, eff_hp),
            "hits_to_die": estimate_hits_to_die(their_dmg, agent.hp),
            "win_probability": win_prob,
            "has_healing": has_healing,
            "healing_potential": target.estimate_healing_potential() if has_healing else 0,
        }
    elif isinstance(target, Monster):
        our_dmg = estimate_our_damage(agent, target.def_)
        their_dmg = estimate_target_damage_to_us(target.atk, 0, agent.def_)
        win_prob = calculate_win_probability_monster(agent, target)
        return {
            "target_name": target.name,
            "target_id": target.id,
            "target_type": "monster",
            "target_hp": target.hp,
            "target_effective_hp": target.hp,
            "our_damage": our_dmg,
            "their_damage": their_dmg,
            "hits_to_kill": estimate_hits_to_kill(our_dmg, target.hp),
            "hits_to_die": estimate_hits_to_die(their_dmg, agent.hp),
            "win_probability": win_prob,
            "has_healing": False,
            "healing_potential": 0,
        }
    return {}


def select_best_target(state: GameState) -> Optional[dict]:
    """
    Select the best target to attack from visible agents and monsters.
    Returns combat analysis dict for the best target, or None.

    Priority (user-defined):
    1. Multiple enemies → attack LOWEST HP first
    2. Multiple enemies with same HP → attack one WITH WEAPON (more dangerous)
    3. Early/mid game no weapon → kill monsters for drops (avoid death zones)
    4. Have weapon → KILLER MODE: scan ALL visible enemies, kill lowest HP
    5. Death zone + many agents → return None (caller should flee)
    """
    weights = load_strategy_weights()
    agent = state.self_agent
    game_phase = _get_game_phase(state)
    has_weapon = agent.weapon_atk_bonus > 0
    in_danger = state.in_death_zone or state.in_pending_death_zone

    # ── TEAM COOPERATION LOGIC ──
    # Check if there are any non-friendly agents visible globally
    any_hostiles_visible = any(
        a.is_alive and a.name.lower() not in FRIENDLY_AGENTS 
        for a in state.visible_agents
    )
    
    # We can only attack a target if they are NOT a friend, 
    # OR if it's late game and there are no hostiles visible.
    def is_targetable(enemy_agent: VisibleAgent) -> bool:
        if not enemy_agent.is_alive:
            return False
        is_friend = enemy_agent.name.lower() in FRIENDLY_AGENTS
        if not is_friend:
            return True  # Always attack hostiles
        # It IS a friend. Only attack if late game AND no hostiles around.
        if game_phase == "late" and not any_hostiles_visible:
            return True
        return False

    agents_here = [a for a in state.agents_in_region() if is_targetable(a)]

    # ── FLEE SIGNAL: death zone + many hostiles = don't fight, run ──
    if in_danger and len(agents_here) >= 3:
        return None  # Signal caller to flee

    # ── KILLER MODE: have weapon → aggressively hunt ALL visible enemies ──
    if has_weapon:
        all_enemies = []

        # Same-region enemies (melee + ranged)
        for enemy in agents_here:
            analysis = get_combat_analysis(agent, enemy)
            all_enemies.append((enemy, analysis, "same"))

        # Adjacent-region enemies (ranged weapon only)
        if agent.weapon_range >= 1:
            for region in state.connected_regions:
                for enemy in state.agents_in_region(region.id):
                    if is_targetable(enemy):
                        analysis = get_combat_analysis(agent, enemy)
                        all_enemies.append((enemy, analysis, "adjacent"))

        if all_enemies:
            # Sort: lowest HP first, then prefer those with weapons (more dangerous)
            all_enemies.sort(key=lambda x: (
                x[0].hp,                          # Primary: lowest HP
                -x[0].weapon_atk_bonus,           # Secondary: has weapon (more threatening)
                0 if x[2] == "same" else 1,       # Tertiary: prefer same region
            ))

            # Pick best target — in danger zones, only attack if very favorable
            for enemy, analysis, location in all_enemies:
                if in_danger:
                    # In danger: only attack guaranteed kills (very low HP)
                    if enemy.hp <= 15 and analysis["win_probability"] >= 0.8:
                        return analysis
                else:
                    # Normal: attack if reasonable win chance
                    min_prob = 0.45 if enemy.hp <= 30 else 0.55
                    if analysis["win_probability"] >= min_prob:
                        return analysis

    # ── EARLY/MID: No weapon → hunt monsters for drops (avoid death zones) ──
    if not has_weapon and game_phase in ("early", "mid"):
        for monster in state.monsters_in_region():
            # Skip if region is death zone / pending
            if in_danger:
                continue
            analysis = get_combat_analysis(agent, monster)
            if analysis["win_probability"] >= 0.4 or monster.hp <= 10:
                return analysis

    # ── FALLBACK: No weapon but enemies present → attack lowest HP ──
    if agents_here:
        # Sort by HP ascending, weapon holders get slight priority on ties
        sorted_enemies = sorted(agents_here, key=lambda e: (e.hp, -e.weapon_atk_bonus))
        for enemy in sorted_enemies:
            analysis = get_combat_analysis(agent, enemy)
            if analysis["win_probability"] >= 0.5:
                return analysis

    # ── MONSTERS (any phase, if nothing else to fight) ──
    for monster in state.monsters_in_region():
        if in_danger:
            continue
        analysis = get_combat_analysis(agent, monster)
        if analysis["win_probability"] >= 0.5:
            return analysis

    return None


def should_flee_instead(state: GameState) -> bool:
    """
    Check if the agent should flee instead of fighting.
    True when: in death/pending zone + many enemies, OR very low HP + outnumbered.
    """
    agent = state.self_agent
    agents_here = len(state.agents_in_region())
    in_danger = state.in_death_zone or state.in_pending_death_zone

    # Death zone + multiple enemies = flee
    if in_danger and agents_here >= 2:
        return True

    # Very low HP + outnumbered = flee
    if agent.hp_percent < 0.25 and agents_here >= 2:
        return True

    return False


def _get_game_phase(state: GameState) -> str:
    """Get game phase from visible state heuristics."""
    # Rough estimate from death zone expansion
    dz_count = len([r for r in state.visible_regions if r.is_death_zone])
    pending_count = len(state.pending_deathzones)
    if dz_count >= 3 or pending_count >= 2:
        return "late"
    elif dz_count >= 1 or pending_count >= 1:
        return "mid"
    return "early"
