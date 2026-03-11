"""
Unit tests for combat strategy module.
Tests damage calculation, win probability, and enemy healing analysis.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from src.strategy.combat import (
    calculate_damage, estimate_hits_to_kill, estimate_hits_to_die,
    estimate_enemy_effective_hp, calculate_win_probability_agent,
    calculate_win_probability_monster, get_combat_analysis,
)
from src.models import AgentSelf, VisibleAgent, Monster, Weapon, Item


def make_agent(hp=100, ep=10, atk=10, def_=5, weapon_name="Fist",
               weapon_bonus=0, weapon_range=0, kills=0, inventory=None):
    """Helper to create test AgentSelf."""
    weapon = Weapon(id="w1", name=weapon_name, atk_bonus=weapon_bonus, range_=weapon_range)
    return AgentSelf(
        id="agent1", name="TestBot", hp=hp, max_hp=100, ep=ep, max_ep=10,
        atk=atk, def_=def_, vision=1, region_id="r1",
        inventory=inventory or [], equipped_weapon=weapon, is_alive=True, kills=kills,
    )


def make_enemy(hp=100, atk=10, def_=5, weapon_name="Fist",
               weapon_bonus=0, weapon_range=0, inventory=None):
    """Helper to create test VisibleAgent."""
    weapon = Weapon(id="w2", name=weapon_name, atk_bonus=weapon_bonus, range_=weapon_range)
    return VisibleAgent(
        id="enemy1", name="Enemy", hp=hp, max_hp=100, atk=atk, def_=def_,
        region_id="r1", equipped_weapon=weapon, is_alive=True,
        inventory=inventory or [],
    )


def make_monster(name="Wolf", hp=5, atk=15, def_=1):
    """Helper to create test Monster."""
    return Monster(id="m1", name=name, hp=hp, atk=atk, def_=def_, region_id="r1")


class TestDamageCalculation(unittest.TestCase):
    """Test combat damage formula."""

    def test_basic_damage(self):
        """ATK 10 + Fist(0) vs DEF 5 → 10 + 0 - 2.5 = 7"""
        dmg = calculate_damage(10, 0, 5)
        self.assertEqual(dmg, 7)

    def test_sword_damage(self):
        """ATK 10 + Sword(+8) vs DEF 5 → 10 + 8 - 2.5 = 15"""
        dmg = calculate_damage(10, 8, 5)
        self.assertEqual(dmg, 15)

    def test_katana_damage(self):
        """ATK 10 + Katana(+21) vs DEF 5 → 10 + 21 - 2.5 = 28"""
        dmg = calculate_damage(10, 21, 5)
        self.assertEqual(dmg, 28)

    def test_sniper_damage(self):
        """ATK 10 + Sniper(+17) vs DEF 5 → 10 + 17 - 2.5 = 24"""
        dmg = calculate_damage(10, 17, 5)
        self.assertEqual(dmg, 24)

    def test_minimum_damage(self):
        """Minimum damage is 1 even with very high DEF."""
        dmg = calculate_damage(1, 0, 100)
        self.assertEqual(dmg, 1)

    def test_zero_def(self):
        """No defense: full damage."""
        dmg = calculate_damage(10, 8, 0)
        self.assertEqual(dmg, 18)

    def test_high_def(self):
        """High defense reduces damage significantly."""
        dmg = calculate_damage(10, 0, 20)
        # 10 + 0 - 10 = 0 → min 1
        self.assertEqual(dmg, 1)


class TestHitsToKill(unittest.TestCase):
    """Test hits-to-kill calculation."""

    def test_one_shot_wolf(self):
        """Katana vs Wolf (5 HP): should be 1 hit."""
        dmg = calculate_damage(10, 21, 1)  # 30 damage
        hits = estimate_hits_to_kill(dmg, 5)
        self.assertEqual(hits, 1)

    def test_multiple_hits(self):
        """10 damage vs 100 HP: 10 hits."""
        hits = estimate_hits_to_kill(10, 100)
        self.assertEqual(hits, 10)

    def test_zero_damage(self):
        """Zero damage: infinite hits."""
        hits = estimate_hits_to_kill(0, 100)
        self.assertEqual(hits, 999)


class TestEnemyHealing(unittest.TestCase):
    """Test enemy effective HP estimation with healing items."""

    def test_no_healing(self):
        """Enemy without healing items: effective HP = actual HP."""
        enemy = make_enemy(hp=80)
        eff = estimate_enemy_effective_hp(enemy)
        self.assertEqual(eff, 80)

    def test_with_bandage(self):
        """Enemy with Bandage (+30): effective HP = 80 + 30 = 110."""
        bandage = Item(id="i1", name="Bandage", category="recovery", hp_restore=30)
        enemy = make_enemy(hp=80, inventory=[bandage])
        eff = estimate_enemy_effective_hp(enemy)
        self.assertEqual(eff, 110)

    def test_with_medkit(self):
        """Enemy with Medkit (+50): effective HP = 60 + 50 = 110."""
        medkit = Item(id="i1", name="Medkit", category="recovery", hp_restore=50)
        enemy = make_enemy(hp=60, inventory=[medkit])
        eff = estimate_enemy_effective_hp(enemy)
        self.assertEqual(eff, 110)

    def test_multiple_healing(self):
        """Enemy with multiple healing items."""
        items = [
            Item(id="i1", name="Bandage", category="recovery", hp_restore=30),
            Item(id="i2", name="Emergency Food", category="recovery", hp_restore=20),
        ]
        enemy = make_enemy(hp=50, inventory=items)
        eff = estimate_enemy_effective_hp(enemy)
        self.assertEqual(eff, 100)  # 50 + 30 + 20


class TestWinProbability(unittest.TestCase):
    """Test win probability calculation."""

    def test_strong_vs_weak(self):
        """Katana + full HP vs Fist + low HP: very high probability."""
        agent = make_agent(hp=100, weapon_name="Katana", weapon_bonus=21)
        enemy = make_enemy(hp=20, weapon_name="Fist", weapon_bonus=0)
        prob = calculate_win_probability_agent(agent, enemy)
        self.assertGreater(prob, 0.85)

    def test_weak_vs_strong(self):
        """Fist + low HP vs Katana + full HP: very low probability."""
        agent = make_agent(hp=20, weapon_name="Fist", weapon_bonus=0)
        enemy = make_enemy(hp=100, weapon_name="Katana", weapon_bonus=21)
        prob = calculate_win_probability_agent(agent, enemy)
        self.assertLess(prob, 0.30)

    def test_even_match(self):
        """Equal stats: around 50-60%."""
        agent = make_agent(hp=100, weapon_name="Sword", weapon_bonus=8)
        enemy = make_enemy(hp=100, weapon_name="Sword", weapon_bonus=8)
        prob = calculate_win_probability_agent(agent, enemy)
        self.assertGreater(prob, 0.4)
        self.assertLess(prob, 0.7)

    def test_enemy_healing_reduces_probability(self):
        """Enemy with healing should reduce our win probability."""
        agent = make_agent(hp=80, weapon_name="Sword", weapon_bonus=8)
        enemy_no_heal = make_enemy(hp=60, weapon_name="Knife", weapon_bonus=5)
        enemy_with_heal = make_enemy(hp=60, weapon_name="Knife", weapon_bonus=5,
                                     inventory=[Item(id="i1", name="Medkit",
                                                    category="recovery", hp_restore=50)])

        prob_no_heal = calculate_win_probability_agent(agent, enemy_no_heal)
        prob_with_heal = calculate_win_probability_agent(agent, enemy_with_heal)
        self.assertGreater(prob_no_heal, prob_with_heal)

    def test_monster_easy_kill(self):
        """Wolf with Katana: near guaranteed win."""
        agent = make_agent(hp=100, weapon_name="Katana", weapon_bonus=21)
        wolf = make_monster("Wolf", hp=5, atk=15, def_=1)
        prob = calculate_win_probability_monster(agent, wolf)
        self.assertGreater(prob, 0.9)


if __name__ == "__main__":
    unittest.main()
