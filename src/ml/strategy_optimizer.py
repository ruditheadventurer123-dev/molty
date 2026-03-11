"""
Molty Royale AI Bot — Strategy Optimizer
Feedback loop to tune strategy weights based on game results.
"""

from src.config import load_strategy_weights, save_strategy_weights, DEFAULT_STRATEGY_WEIGHTS
from src.ml.data_collector import GameDataCollector
from src import logger


class StrategyOptimizer:
    """Adjusts strategy weights based on game performance feedback."""

    def __init__(self):
        self.weights = load_strategy_weights()

    def update_weights(self):
        """
        Analyze recent game results and adjust strategy weights.
        Uses simple gradient-free optimization: nudge weights toward better outcomes.
        """
        games = GameDataCollector.load_all_games()
        if len(games) < 3:
            return  # Need at least 3 games for meaningful analysis

        # Analyze last 10 games
        recent = games[-10:]

        # Calculate performance metrics
        wins = sum(1 for g in recent if g.get("result", {}).get("is_winner", False))
        avg_kills = sum(g.get("result", {}).get("kills", 0) for g in recent) / len(recent)
        avg_rank = sum(g.get("result", {}).get("final_rank", 50) for g in recent) / len(recent)

        # Count death zone deaths
        dz_deaths = 0
        aggressive_deaths = 0
        for g in recent:
            turns = g.get("turns", [])
            if turns and not g.get("result", {}).get("is_winner", False):
                last_turn = turns[-1] if turns else {}
                state = last_turn.get("state", {})
                if state.get("is_death_zone", False):
                    dz_deaths += 1
                last_action = last_turn.get("action", {})
                if last_action.get("type") == "attack":
                    aggressive_deaths += 1

        # Adjust weights based on feedback
        delta = 0.02  # Small adjustment step

        # If dying aggressively too much, lower aggression / raise win probability threshold
        if aggressive_deaths > len(recent) * 0.4:
            self.weights["win_probability_threshold"] = min(
                0.9, self.weights["win_probability_threshold"] + delta
            )
            self.weights["aggression_factor"] = max(
                0.3, self.weights["aggression_factor"] - delta
            )
            logger.info("Strategy: Slightly reducing aggression (too many combat deaths)")

        # If getting good kills, increase aggression slightly
        if avg_kills > 3 and aggressive_deaths < len(recent) * 0.2:
            self.weights["win_probability_threshold"] = max(
                0.5, self.weights["win_probability_threshold"] - delta
            )
            self.weights["aggression_factor"] = min(
                0.9, self.weights["aggression_factor"] + delta
            )
            logger.info("Strategy: Slightly increasing aggression (good kill rate)")

        # If dying in death zones, adjust heal threshold (survive longer)
        if dz_deaths > 1:
            self.weights["hp_heal_threshold"] = min(
                50, self.weights["hp_heal_threshold"] + 2
            )
            logger.info("Strategy: Raising heal threshold (death zone deaths)")

        # If winning, keep weights stable but slightly optimize
        if wins > len(recent) * 0.3:
            logger.info(f"Strategy: Good performance ({wins}/{len(recent)} wins, avg kills: {avg_kills:.1f})")

        # Save updated weights
        save_strategy_weights(self.weights)

    def reset_to_defaults(self):
        """Reset all weights to defaults."""
        self.weights = DEFAULT_STRATEGY_WEIGHTS.copy()
        save_strategy_weights(self.weights)

    def get_summary(self) -> str:
        """Get a summary of current strategy weights."""
        w = self.weights
        return (
            f"Win Prob Threshold: {w['win_probability_threshold']:.2f} | "
            f"Aggression: {w['aggression_factor']:.2f} | "
            f"Heal HP: <{w['hp_heal_threshold']} | "
            f"EP Rest: <{w['ep_rest_threshold']}"
        )


# Singleton
optimizer = StrategyOptimizer()
