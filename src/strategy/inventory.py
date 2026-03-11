"""
Molty Royale AI Bot — Inventory & Resource Management
Weapon ranking, item priority, EP/HP management, pickup/equip decisions.
Upgrades: Late game healing priority, healing conservation, healing item search.
"""

from typing import Optional
from src.models import AgentSelf, Item, GameState
from src.config import (
    WEAPON_RANKING, RECOVERY_ITEMS, load_strategy_weights,
    EARLY_GAME_END, MID_GAME_END,
    LATE_GAME_HP_HEAL_THRESHOLD, LATE_GAME_MEDKIT_THRESHOLD,
    LATE_GAME_HEAL_PERCENT, CHAOS_HP_THRESHOLD,
    EARLY_GAME_CONSERVE_HP, MID_GAME_CONSERVE_HP,
)


# ─── Game Phase Helper ─────────────────────────────────────────────
def get_game_phase(turn_count: int) -> str:
    """Get current game phase based on turn number."""
    if turn_count <= EARLY_GAME_END:
        return "early"
    elif turn_count <= MID_GAME_END:
        return "mid"
    return "late"


# ─── Weapon Ranking ────────────────────────────────────────────────
WEAPON_TIER = {
    "katana": 6,
    "sniper": 5,
    "sword": 3,
    "pistol": 4,
    "knife": 1,
    "bow": 2,
    "fist": 0,
}


def get_weapon_tier(weapon_name: str) -> int:
    """Get weapon tier by name (case-insensitive). Higher = better."""
    return WEAPON_TIER.get(weapon_name.lower(), 0)


def get_weapon_tier_by_bonus(atk_bonus: int) -> int:
    """Get weapon tier by ATK bonus. Higher = better."""
    bonus_to_tier = {0: 0, 3: 2, 5: 1, 6: 4, 8: 3, 17: 5, 21: 6}
    return bonus_to_tier.get(atk_bonus, 0)


def get_best_weapon(inventory: list) -> Optional[Item]:
    """Find the best weapon in inventory by ATK bonus."""
    weapons = [i for i in inventory if i.is_weapon]
    if not weapons:
        return None
    return max(weapons, key=lambda w: w.atk_bonus)


def should_equip_weapon(agent: AgentSelf) -> Optional[Item]:
    """
    Check if we should equip a better weapon from inventory.
    Returns the weapon to equip, or None.
    """
    best = get_best_weapon(agent.inventory)
    if not best:
        return None

    current_bonus = agent.weapon_atk_bonus
    if best.atk_bonus > current_bonus:
        return best
    return None


# ─── Healing & Recovery ────────────────────────────────────────────
def get_healing_items_count(agent: AgentSelf) -> int:
    """Count number of healing items in inventory."""
    return len([i for i in agent.inventory_recovery if i.hp_restore > 0])


def get_best_healing_item(agent: AgentSelf) -> Optional[Item]:
    """
    Get the most appropriate healing item.
    Strategy: use smallest heal that restores enough.
    Don't waste Medkit (+50) on 10 HP damage.
    """
    hp_missing = agent.max_hp - agent.hp
    if hp_missing <= 0:
        return None

    recovery = agent.inventory_recovery
    if not recovery:
        return None

    # Sort by hp_restore ascending (use smallest appropriate item)
    hp_items = [i for i in recovery if i.hp_restore > 0]
    hp_items.sort(key=lambda i: i.hp_restore)

    # Find smallest item that restores at least 60% of missing HP
    for item in hp_items:
        if item.hp_restore >= hp_missing * 0.6:
            return item

    # If no perfect match, use the largest available
    if hp_items:
        return hp_items[-1]

    return None


def get_energy_drink(agent: AgentSelf) -> Optional[Item]:
    """Get an energy drink from inventory if available."""
    for item in agent.inventory:
        if item.is_recovery and item.ep_restore > 0:
            return item
    return None


def should_heal(agent: AgentSelf, game_phase: str = "early",
                agents_in_region: int = 0) -> Optional[Item]:
    """
    Check if we should heal now. Phase-aware with dynamic thresholds.
    Returns the healing item to use, or None.

    Thresholds:
    - Early game: HP < 40 (conserve for later)
    - Mid game: HP < 50
    - Late game: HP < 50 (or 70% of max HP, whichever is higher)
    - Chaos (3+ agents nearby): HP < 60
    """
    weights = load_strategy_weights()

    # ── Late Game: higher heal thresholds
    if game_phase == "late":
        late_threshold = max(
            LATE_GAME_HP_HEAL_THRESHOLD,
            int(agent.max_hp * LATE_GAME_HEAL_PERCENT)
        )
        if agent.hp < late_threshold:
            return get_best_healing_item(agent)
        # Medkit threshold also higher in late game
        if agent.hp < LATE_GAME_MEDKIT_THRESHOLD:
            for item in agent.inventory_recovery:
                if item.hp_restore >= 50:  # Medkit
                    return item

    # ── Chaos War: 3+ agents in region → heal if HP < 60
    if agents_in_region >= 3 and agent.hp < CHAOS_HP_THRESHOLD:
        return get_best_healing_item(agent)

    # ── Phase-based conservation thresholds
    if game_phase == "early":
        threshold = EARLY_GAME_CONSERVE_HP
    elif game_phase == "mid":
        threshold = MID_GAME_CONSERVE_HP
    else:
        threshold = weights.get("hp_heal_threshold", 30)

    # Critical HP: use any healing
    if agent.hp < threshold:
        return get_best_healing_item(agent)

    # Medium HP: use Medkit if available (only if below medkit threshold)
    medkit_threshold = weights.get("hp_heal_medkit_threshold", 50)
    if agent.hp < medkit_threshold:
        for item in agent.inventory_recovery:
            if item.hp_restore >= 50:  # Medkit
                return item

    return None


def should_use_energy_drink(agent: AgentSelf) -> Optional[Item]:
    """
    Check if we should use an energy drink.
    Use when EP < 2 (can't attack) and we have one.
    """
    if agent.ep < 2:
        return get_energy_drink(agent)
    return None


# ─── Healing Conservation (Upgrade 5) ──────────────────────────────
def should_conserve_healing(agent: AgentSelf, game_phase: str,
                            healing_count: int) -> bool:
    """
    Check if we should conserve healing items (not use them yet).
    Returns True if we should save items for later.
    """
    if game_phase == "late":
        return False  # Use freely in late game

    if healing_count <= 1:
        # Only 1 or 0 items left — conserve unless critical
        if game_phase == "early":
            return agent.hp >= 25  # Only use at critical HP
        return agent.hp >= 35

    return False  # Have enough items, no need to conserve


def should_seek_healing_items(agent: AgentSelf, game_phase: str) -> bool:
    """
    Check if we should actively search for healing items.
    Returns True when healing_count < 2 and game is mid phase.
    """
    healing_count = get_healing_items_count(agent)
    if game_phase == "mid" and healing_count < 2:
        return True
    if game_phase == "early" and healing_count == 0:
        return True
    return False


# ─── Pickup Decisions ──────────────────────────────────────────────
def get_items_to_pickup(state: GameState, game_phase: str = "early") -> list:
    """
    Get list of items worth picking up in current region.
    Priority: currency > better weapons > recovery items > utility.
    In mid game with low healing: boost recovery priority.
    Returns list of item IDs to pickup.
    """
    agent = state.self_agent
    items_here = state.items_in_region()

    if not items_here or agent.inventory_full:
        return []

    pickup_list = []
    space = 10 - agent.inventory_count

    # In mid game, boost healing item priority
    healing_count = get_healing_items_count(agent)
    boost_healing = (game_phase == "mid" and healing_count < 2)

    # Categorize items
    currency_items = []
    weapon_items = []
    recovery_items = []
    utility_items = []

    for vi in items_here:
        item = vi.item
        if item.is_currency:
            currency_items.append(item)
        elif item.is_weapon:
            # Only pick up if better than current
            if item.atk_bonus > agent.weapon_atk_bonus:
                weapon_items.append(item)
        elif item.is_recovery:
            recovery_items.append(item)
        elif item.is_utility:
            utility_items.append(item)

    # Sort weapons by atk_bonus descending
    weapon_items.sort(key=lambda i: i.atk_bonus, reverse=True)
    # Sort recovery by hp_restore descending
    recovery_items.sort(key=lambda i: i.hp_restore + i.ep_restore, reverse=True)

    if boost_healing:
        # Priority: recovery > currency > weapons > utility
        for item in recovery_items:
            if space > 0:
                pickup_list.append(item.id)
                space -= 1
        for item in currency_items:
            if space > 0:
                pickup_list.append(item.id)
                space -= 1
    else:
        # Normal priority: currency > weapons > recovery > utility
        for item in currency_items:
            if space > 0:
                pickup_list.append(item.id)
                space -= 1

    for item in weapon_items:
        if space > 0:
            pickup_list.append(item.id)
            space -= 1

    if not boost_healing:
        for item in recovery_items:
            if space > 0:
                pickup_list.append(item.id)
                space -= 1

    for item in utility_items:
        if space > 0:
            pickup_list.append(item.id)
            space -= 1

    return pickup_list


# ─── EP Management ─────────────────────────────────────────────────
def should_rest(agent: AgentSelf) -> bool:
    """Check if we should rest to recover EP."""
    weights = load_strategy_weights()
    threshold = weights.get("ep_rest_threshold", 2)
    return agent.ep < threshold


def can_attack(agent: AgentSelf) -> bool:
    """Check if we have enough EP to attack."""
    return agent.ep >= 2


def can_act(agent: AgentSelf) -> bool:
    """Check if we have any EP for an action."""
    return agent.ep >= 1


# ─── Facility Usage ────────────────────────────────────────────────
def get_best_facility_to_use(state: GameState) -> Optional[dict]:
    """
    Get the best unused facility in current region.
    Priority: medical_facility > supply_cache > watchtower > broadcast_station.
    Returns {"interactableId": ..., "type": ...} or None.
    """
    region = state.current_region
    facilities = region.get_unused_facilities()
    agent = state.self_agent

    if not facilities or agent.ep < 1:
        return None

    # Priority ordering
    priority = {
        "medical_facility": 5 if agent.hp < agent.max_hp else 0,
        "supply_cache": 4,
        "watchtower": 3,
        "broadcast_station": 1,
        "cave": 0,  # Usually avoid cave (restricts movement)
    }

    facilities.sort(key=lambda f: priority.get(f.type, 0), reverse=True)
    best = facilities[0]

    if priority.get(best.type, 0) > 0:
        return {"interactableId": best.id, "type": best.type}

    return None

