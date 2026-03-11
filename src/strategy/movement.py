"""
Molty Royale AI Bot — Movement Strategy
Death zone absolute avoidance, safe pathfinding, strategic positioning.
ABSOLUTE RULE: NEVER enter death zone or pending death zone regions.
Upgrade: 2-hop deep safety scoring to avoid late-game traps.
"""

from typing import Optional
from src.models import GameState, Region
from src.config import TERRAIN_PRIORITY


def is_region_safe(region_id: str, state: GameState) -> bool:
    """
    Check if a region is safe to move to.
    ABSOLUTE RULE: Returns False for death zone AND pending death zone.
    """
    # Check pending death zones
    if region_id in state.pending_deathzone_ids:
        return False

    # Check all known regions for death zone status
    all_known = state.connected_regions + state.visible_regions + [state.current_region]
    for r in all_known:
        if r.id == region_id and r.is_death_zone:
            return False

    return True


def get_safe_regions(state: GameState) -> list:
    """
    Get all connected regions that are safe (not death zone, not pending death zone).
    """
    safe = []
    for r in state.connected_regions:
        if is_region_safe(r.id, state):
            safe.append(r)
    return safe


def must_evacuate(state: GameState) -> bool:
    """Check if we MUST evacuate current region immediately."""
    return state.in_death_zone or state.in_pending_death_zone


# ─── Deep Safety Scoring (2-hop lookahead) ─────────────────────────
def count_safe_neighbors(region: Region, state: GameState) -> int:
    """Count how many of a region's connections are safe."""
    safe_count = 0
    for conn_id in region.connections:
        if is_region_safe(conn_id, state):
            safe_count += 1
    return safe_count


def score_region_safety_depth(region: Region, state: GameState) -> float:
    """
    Score a region by deep safety — how many of its neighbors are also safe.
    Higher score = more escape options if death zone expands next turn.

    Score components:
    - Base: region itself is safe (+10)
    - Each safe neighbor: +3
    - Each unsafe neighbor: -2
    - If >50% neighbors are death/pending: heavy penalty (-10)
    - Total connections bonus: more connections = more mobility
    """
    if not is_region_safe(region.id, state):
        return -100  # Never suggest an unsafe region

    total_connections = len(region.connections)
    if total_connections == 0:
        return 0

    safe_neighbors = count_safe_neighbors(region, state)
    unsafe_neighbors = total_connections - safe_neighbors

    score = 10.0  # Base safe score
    score += safe_neighbors * 3
    score -= unsafe_neighbors * 2

    # Heavy penalty if majority of exits are death zone — trap risk!
    unsafe_ratio = unsafe_neighbors / total_connections
    if unsafe_ratio > 0.5:
        score -= 10

    # Bonus for total mobility (more connections = better)
    score += total_connections * 0.5

    return score


def find_escape_route(state: GameState) -> Optional[str]:
    """
    Find the best escape route from death zone / pending death zone.
    Returns region_id to move to, or None if trapped.

    ABSOLUTE: Never suggests death zone or pending death zone.
    Uses deep safety scoring to pick region with best escape options.
    """
    safe_regions = get_safe_regions(state)

    if not safe_regions:
        # Desperate: try any connected region that is at least not currently death zone
        # even if pending (better than staying in active death zone)
        if state.in_death_zone:
            for r in state.connected_regions:
                if not r.is_death_zone:
                    return r.id
        return None

    # Score safe regions by deep safety + strategic value
    scored = []
    for r in safe_regions:
        score = score_region_safety_depth(r, state)
        # Terrain preference
        score += TERRAIN_PRIORITY.get(r.terrain, 1)
        # Avoid water (costs 2 EP)
        if r.terrain == "water":
            score -= 5
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1].id if scored else None


def find_strategic_position(state: GameState, visited_regions: set = None,
                            use_deep_safety: bool = False) -> Optional[str]:
    """
    Find the best region to move to for strategic advantage.
    FILTERS OUT ALL death zone and pending death zone regions first.

    Priorities:
    1. Hills (vision +2)
    2. Ruins (better loot find rate)
    3. Forest (stealth, ambush)
    4. Plains
    5. Avoid water (2 EP move cost)

    When use_deep_safety=True (mid/late game), factors in neighbor safety.
    """
    safe_regions = get_safe_regions(state)
    if not safe_regions:
        return None

    visited = visited_regions or set()

    scored = []
    for r in safe_regions:
        score = 0

        # Terrain priority
        score += TERRAIN_PRIORITY.get(r.terrain, 1) * 3

        # Unexplored bonus
        if r.id not in visited:
            score += 5

        # More connections = more mobility
        score += len(r.connections)

        # Has unused facilities = bonus
        if r.has_unused_facility:
            score += 4

        # Avoid water
        if r.terrain == "water":
            score -= 8

        # Penalty for storm (extra EP cost)
        if r.weather == "storm":
            score -= 3

        # Deep safety scoring for mid/late game
        if use_deep_safety:
            deep_score = score_region_safety_depth(r, state)
            score += deep_score * 0.5  # Weight deep safety at 50%

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1].id if scored else None


def find_move_toward_target(state: GameState, target_region_id: str) -> Optional[str]:
    """
    Find which connected region to move to to get closer to a target region.
    Only returns safe regions.
    """
    # If target is directly connected, move there (if safe)
    safe_regions = get_safe_regions(state)
    safe_ids = {r.id for r in safe_regions}

    if target_region_id in safe_ids:
        return target_region_id

    # Otherwise, can't pathfind further without map data
    # Return best strategic region facing the general direction
    return None


def should_preemptive_move(state: GameState) -> bool:
    """
    Check if we should move preemptively because our region is about to become death zone.
    Returns True if current region is in pendingDeathzones.
    """
    return state.in_pending_death_zone


def get_death_zone_edge_regions(state: GameState) -> list:
    """
    Find regions that are at the edge of the death zone (safe but adjacent to death zone).
    Useful for ambushing enemies fleeing the death zone.
    """
    safe = get_safe_regions(state)
    edge = []
    death_zone_ids = set()

    # Collect known death zone region IDs
    for r in state.connected_regions + state.visible_regions:
        if r.is_death_zone:
            death_zone_ids.add(r.id)

    # Pending also counts
    death_zone_ids.update(state.pending_deathzone_ids)

    for r in safe:
        # Check if this safe region is adjacent to any death zone
        for conn_id in r.connections:
            if conn_id in death_zone_ids:
                edge.append(r)
                break

    return edge


# ─── Crowded Region Escape (Upgrade 3) ─────────────────────────────
def find_safe_escape_from_crowd(state: GameState) -> Optional[str]:
    """
    Find the safest region to flee to when current region is crowded (4+ agents).
    Prefers regions with:
    - Fewest visible agents
    - Best deep safety score (most safe neighbors)
    - Not death zone or pending
    """
    safe_regions = get_safe_regions(state)
    if not safe_regions:
        return None

    scored = []
    for r in safe_regions:
        score = 0.0

        # Deep safety score (avoid getting trapped)
        score += score_region_safety_depth(r, state)

        # Fewer agents in the region = better (less combat risk)
        agents_there = len(state.agents_in_region(r.id))
        score -= agents_there * 15  # Heavy penalty per agent

        # Terrain preference
        score += TERRAIN_PRIORITY.get(r.terrain, 1)

        # Avoid water
        if r.terrain == "water":
            score -= 5

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1].id if scored else None

