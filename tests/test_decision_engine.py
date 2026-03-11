"""
Unit tests for decision engine priority logic.
Tests that the correct action is chosen for each priority level.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from src.strategy.decision_engine import DecisionEngine
from src.models import (
    GameState, AgentSelf, Region, VisibleAgent, Monster,
    VisibleItem, Item, Weapon, PendingDeathzone, Message, Interactable,
)


def make_state(
    hp=100, ep=10, atk=10, def_=5,
    weapon_name="Fist", weapon_bonus=0,
    region_terrain="plains", is_death_zone=False,
    pending_deathzones=None,
    visible_agents=None, visible_monsters=None,
    visible_items=None, inventory=None,
    connected_regions=None, interactables=None,
):
    """Helper to build a GameState for testing."""
    weapon = Weapon(id="w1", name=weapon_name, atk_bonus=weapon_bonus, range_=0)
    agent = AgentSelf(
        id="agent1", name="Bot", hp=hp, max_hp=100, ep=ep, max_ep=10,
        atk=atk, def_=def_, vision=1, region_id="r_current",
        inventory=inventory or [], equipped_weapon=weapon,
        is_alive=True, kills=0,
    )
    region = Region(
        id="r_current", name="Test Region", terrain=region_terrain,
        weather="clear", vision_modifier=0, is_death_zone=is_death_zone,
        connections=["r_safe1", "r_safe2"],
        interactables=interactables or [],
    )
    conn = connected_regions or [
        Region(id="r_safe1", name="Safe 1", terrain="plains", is_death_zone=False,
               connections=["r_current", "r_safe2"]),
        Region(id="r_safe2", name="Safe 2", terrain="hills", is_death_zone=False,
               connections=["r_current", "r_safe1"]),
    ]

    return GameState(
        self_agent=agent,
        current_region=region,
        connected_regions=conn,
        visible_agents=visible_agents or [],
        visible_monsters=visible_monsters or [],
        visible_items=visible_items or [],
        visible_regions=[],
        pending_deathzones=pending_deathzones or [],
        recent_messages=[],
        game_status="running",
    )


class TestPriority1_DeathZone(unittest.TestCase):
    """P1: ESCAPE DEATH ZONE (absolute)."""

    def test_in_death_zone_moves(self):
        """In death zone → must move to safe region."""
        engine = DecisionEngine()
        state = make_state(is_death_zone=True)
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "move")

    def test_in_pending_death_zone_moves(self):
        """In pending death zone → must move away."""
        engine = DecisionEngine()
        state = make_state(
            pending_deathzones=[PendingDeathzone(id="r_current", name="Test Region")]
        )
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "move")

    def test_death_zone_overrides_combat(self):
        """Death zone escape takes priority over attack opportunity."""
        engine = DecisionEngine()
        weak_enemy = VisibleAgent(
            id="e1", name="WeakEnemy", hp=10, max_hp=100, atk=5, def_=2,
            region_id="r_current", equipped_weapon=None, is_alive=True,
        )
        state = make_state(is_death_zone=True, visible_agents=[weak_enemy])
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "move")


class TestPriority2_Healing(unittest.TestCase):
    """P2: CRITICAL HEALING."""

    def test_low_hp_heals(self):
        """HP < 30 with healing item → use_item."""
        engine = DecisionEngine()
        bandage = Item(id="i1", name="Bandage", category="recovery", hp_restore=30)
        state = make_state(hp=20, inventory=[bandage])
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "use_item")
        self.assertEqual(result["action"]["itemId"], "i1")

    def test_high_hp_no_heal(self):
        """HP = 100 with healing item → does NOT heal."""
        engine = DecisionEngine()
        bandage = Item(id="i1", name="Bandage", category="recovery", hp_restore=30)
        state = make_state(hp=100, inventory=[bandage])
        result = engine.decide(state)
        self.assertNotEqual(result["action"]["type"], "use_item")


class TestPriority3_EP(unittest.TestCase):
    """P3: EP MANAGEMENT."""

    def test_low_ep_rests(self):
        """EP < 2 with no threat → rest."""
        engine = DecisionEngine()
        state = make_state(ep=1)
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "rest")


class TestPriority4_Combat(unittest.TestCase):
    """P4: COMBAT (aggressive, kills = ranking)."""

    def test_attacks_weak_enemy(self):
        """Weak enemy in region with good stats → attack."""
        engine = DecisionEngine()
        weak_enemy = VisibleAgent(
            id="e1", name="WeakEnemy", hp=15, max_hp=100, atk=5, def_=2,
            region_id="r_current",
            equipped_weapon=Weapon(id="ew", name="Fist", atk_bonus=0, range_=0),
            is_alive=True,
        )
        state = make_state(hp=100, ep=5, weapon_name="Sword", weapon_bonus=8,
                           visible_agents=[weak_enemy])
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "attack")
        self.assertEqual(result["action"]["targetId"], "e1")

    def test_does_not_attack_strong_enemy(self):
        """Very strong enemy in region → does NOT attack (low win prob)."""
        engine = DecisionEngine()
        strong_enemy = VisibleAgent(
            id="e1", name="StrongEnemy", hp=100, max_hp=100, atk=30, def_=10,
            region_id="r_current",
            equipped_weapon=Weapon(id="ew", name="Katana", atk_bonus=21, range_=0),
            is_alive=True,
        )
        state = make_state(hp=30, ep=5, weapon_name="Fist", weapon_bonus=0,
                           visible_agents=[strong_enemy])
        result = engine.decide(state)
        self.assertNotEqual(result["action"]["type"], "attack")

    def test_attacks_monster(self):
        """Monster in region with good stats → attack."""
        engine = DecisionEngine()
        wolf = Monster(id="m1", name="Wolf", hp=5, atk=15, def_=1, region_id="r_current")
        state = make_state(hp=100, ep=5, weapon_name="Sword", weapon_bonus=8,
                           visible_monsters=[wolf])
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "attack")
        self.assertEqual(result["action"]["targetId"], "m1")


class TestPriority6_Explore(unittest.TestCase):
    """P6: LOOT & EXPLORE."""

    def test_explores_unexplored_region(self):
        """Unexplored region → explore."""
        engine = DecisionEngine()
        state = make_state(hp=100, ep=5)
        result = engine.decide(state)
        self.assertEqual(result["action"]["type"], "explore")


class TestPendingDeathZoneCombat(unittest.TestCase):
    """Combat in pending death zone → skip combat, evacuate."""

    def test_skips_combat_in_pending_dz(self):
        """Enemy in pending death zone region → do NOT attack, move instead."""
        engine = DecisionEngine()
        enemy = VisibleAgent(
            id="e1", name="Enemy", hp=50, max_hp=100, atk=10, def_=5,
            region_id="r_current",
            equipped_weapon=Weapon(id="ew", name="Knife", atk_bonus=5, range_=0),
            is_alive=True,
        )
        state = make_state(
            hp=100, ep=5, weapon_name="Sword", weapon_bonus=8,
            visible_agents=[enemy],
            pending_deathzones=[PendingDeathzone(id="r_current", name="Test")]
        )
        result = engine.decide(state)
        # Should move (evacuate), not attack
        self.assertEqual(result["action"]["type"], "move")


if __name__ == "__main__":
    unittest.main()
