"""
Molty Royale AI Bot — Survival Score Calculator
Scores game performance on a 0-1 scale, enabling ML to learn even from losses.
Higher score = better performance, even if the game was lost.
"""


def calculate_survival_score(game_data: dict) -> float:
    """
    Calculate a 0.0 to 1.0 survival score from game data.
    ML can learn from ALL games (wins and losses) by comparing scores.

    Formula:
      - Turns survived (30%) — longer = better
      - Kills (30%) — kills = very important for ranking
      - Final HP ratio (15%) — ending with more HP = better
      - Weapon acquired (10%) — finding a weapon = smart play
      - Winner bonus (15%) — actual win = big bonus
    """
    result = game_data.get("result", {})
    turns = game_data.get("total_turns", 0)
    kills = result.get("kills", 0)
    is_winner = result.get("is_winner", False)

    # Extract weapon info from last turn
    turns_data = game_data.get("turns", [])
    final_hp = 0
    max_hp = 100
    had_weapon = False

    if turns_data:
        last_turn = turns_data[-1].get("state", {})
        final_hp = last_turn.get("hp", 0)
        max_hp = last_turn.get("max_hp", 100)
        weapon = last_turn.get("weapon", "Fist")
        had_weapon = weapon.lower() != "fist"

    # Score components
    turn_score = min(1.0, turns / 40.0)  # 40 turns = max
    kill_score = min(1.0, kills / 5.0)   # 5 kills = max
    hp_score = final_hp / max(1, max_hp)
    weapon_score = 1.0 if had_weapon else 0.0
    win_score = 1.0 if is_winner else 0.0

    # Weighted combination
    score = (
        turn_score * 0.30 +
        kill_score * 0.30 +
        hp_score * 0.15 +
        weapon_score * 0.10 +
        win_score * 0.15
    )

    return round(min(1.0, max(0.0, score)), 4)


def calculate_combat_score(event: dict, game_survival_score: float = 0.5) -> float:
    """
    Score a combat event on 0-1 scale.
    Combines combat outcome with overall game performance.

    Factors:
    - Combat result (win/lose/flee)
    - Damage efficiency (dealt vs taken)
    - Game survival score (context)
    """
    result = event.get("result", "pending")
    damage_dealt = event.get("damage_dealt", 0)
    damage_taken = event.get("damage_taken", 0)

    # Base score from result
    if result == "win":
        base = 0.8
    elif result == "flee":
        base = 0.4  # Fleeing is neutral — sometimes smart
    elif result == "pending":
        # Pending = we attacked but don't know result yet
        # Use damage ratio as indicator
        base = 0.5
    else:  # lose
        base = 0.15

    # Damage efficiency bonus (0 to 0.2)
    total_dmg = damage_dealt + damage_taken
    if total_dmg > 0:
        efficiency = damage_dealt / total_dmg
    else:
        efficiency = 0.5
    dmg_bonus = (efficiency - 0.5) * 0.4  # -0.2 to +0.2

    # Game context bonus: if the game went well overall, combat was probably good
    context_bonus = (game_survival_score - 0.5) * 0.2  # -0.1 to +0.1

    score = base + dmg_bonus + context_bonus
    return round(min(1.0, max(0.0, score)), 4)


def label_combat_events_with_scores(games: list) -> list:
    """
    Take list of game data dicts, return list of (event, score) tuples.
    Each combat event gets scored based on its result AND the game's overall survival score.
    """
    labeled = []
    for game in games:
        survival_score = calculate_survival_score(game)
        for event in game.get("combat_events", []):
            score = calculate_combat_score(event, survival_score)
            labeled.append((event, score))
    return labeled
