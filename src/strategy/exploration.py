"""
Molty Royale AI Bot — Exploration Strategy
Smart region exploration, avoiding revisits, prioritizing high-value areas.
Upgrade: healing item search in mid game.
"""

from typing import Optional
from src.models import GameState
from src.strategy.movement import is_region_safe, get_safe_regions
from src.config import TERRAIN_PRIORITY


# Max times to explore same region before moving on
MAX_EXPLORES_PER_REGION = 3


class ExplorationTracker:
    """Tracks explored regions and exploration state per game."""

    def __init__(self):
        self.explored_regions: set = set()   # Regions we've explored
        self.visited_regions: set = set()    # Regions we've been to
        self.empty_regions: set = set()      # Regions with no loot found
        self.explore_count: dict = {}        # region_id -> explore count

    def reset(self):
        """Reset for new game."""
        self.explored_regions.clear()
        self.visited_regions.clear()
        self.empty_regions.clear()
        self.explore_count.clear()

    def mark_visited(self, region_id: str):
        """Mark region as visited."""
        self.visited_regions.add(region_id)

    def mark_explored(self, region_id: str, found_items: bool = True):
        """Mark region as explored and increment counter."""
        self.explored_regions.add(region_id)
        self.explore_count[region_id] = self.explore_count.get(region_id, 0) + 1
        if not found_items:
            self.empty_regions.add(region_id)

    def is_explored(self, region_id: str) -> bool:
        return region_id in self.explored_regions

    def is_visited(self, region_id: str) -> bool:
        return region_id in self.visited_regions

    def is_exhausted(self, region_id: str) -> bool:
        """Has this region been explored too many times? Time to move."""
        return self.explore_count.get(region_id, 0) >= MAX_EXPLORES_PER_REGION


def should_explore_current(state: GameState, tracker: ExplorationTracker) -> bool:
    """
    Should we explore the current region?
    Yes if: not yet explored or under explore cap.
    No if: exhausted (explored 3+ times), or no EP.
    """
    region = state.current_region
    agent = state.self_agent

    # Need at least 1 EP
    if agent.ep < 1:
        return False

    # Region exhausted (explored 3+ times) → MUST move on
    if tracker.is_exhausted(region.id):
        return False

    # Never explored this region -> yes
    if not tracker.is_explored(region.id):
        return True

    # Ruins have higher item find rate, worth re-exploring (if under cap)
    if region.terrain == "ruins" and region.id not in tracker.empty_regions:
        return True

    return False


def get_exploration_target(state: GameState, tracker: ExplorationTracker,
                           boost_healing: bool = False) -> Optional[str]:
    """
    Find the best region to move to for exploration.
    Prioritizes: unexplored > ruins > regions with visible items.
    NEVER returns death zone or pending death zone regions.

    When boost_healing=True (mid game, low on heals): boost regions with recovery items.
    """
    safe_regions = get_safe_regions(state)
    if not safe_regions:
        return None

    # Build set of regions with visible recovery items
    recovery_regions = set()
    if boost_healing:
        for vi in state.visible_items:
            if vi.item.is_recovery and is_region_safe(vi.region_id, state):
                recovery_regions.add(vi.region_id)

    # Build set of regions with visible weapon items
    weapon_regions = set()
    for vi in state.visible_items:
        if vi.item.is_weapon and is_region_safe(vi.region_id, state):
            weapon_regions.add(vi.region_id)

    scored = []
    for r in safe_regions:
        score = 0

        # Unexplored bonus (huge)
        if not tracker.is_explored(r.id):
            score += 10

        # Never visited bonus
        if not tracker.is_visited(r.id):
            score += 5

        # Terrain bonus — ruins have best item find rate
        if r.terrain == "ruins":
            score += 8
        score += TERRAIN_PRIORITY.get(r.terrain, 1)

        # Has unused facilities
        if r.has_unused_facility:
            score += 6

        # Avoid water (2 EP to move)
        if r.terrain == "water":
            score -= 5

        # Known empty = penalty
        if r.id in tracker.empty_regions:
            score -= 8

        # Exhausted = big penalty (explored 3+ times, move on!)
        if tracker.is_exhausted(r.id):
            score -= 12

        # Boost: region has recovery items on ground
        if r.id in recovery_regions:
            score += 15

        # Boost: region has WEAPON items on ground (very high priority)
        if r.id in weapon_regions:
            score += 20

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1].id if scored else None


def has_valuable_exploration_nearby(state: GameState, tracker: ExplorationTracker) -> bool:
    """Check if there are unexplored or high-value regions nearby."""
    safe_regions = get_safe_regions(state)
    for r in safe_regions:
        if not tracker.is_explored(r.id):
            return True
        if r.terrain == "ruins" and r.id not in tracker.empty_regions:
            return True
        if r.has_unused_facility:
            return True
    return False


# ─── Healing Item Search (Upgrade 5) ──────────────────────────────
def find_healing_item_region(state: GameState) -> Optional[str]:
    """
    Scan visible items for safe regions containing recovery items on ground.
    Returns region_id of nearest safe region with healing items, or None.
    Prioritizes connected regions (1-move away).
    """
    safe_connected_ids = {r.id for r in get_safe_regions(state)}

    # Check connected regions first (immediate move)
    best_region = None
    best_hp_restore = 0

    for vi in state.visible_items:
        if vi.item.is_recovery and vi.item.hp_restore > 0:
            if vi.region_id in safe_connected_ids:
                if vi.item.hp_restore > best_hp_restore:
                    best_hp_restore = vi.item.hp_restore
                    best_region = vi.region_id

    return best_region

