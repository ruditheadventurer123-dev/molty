"""
Molty Royale AI Bot — ML Training
Uses SURVIVAL SCORES to learn from ALL games (wins AND losses).
Can be run standalone: python -m src.ml.training
"""

from src.ml.data_collector import GameDataCollector
from src.ml.feature_engine import batch_extract, batch_extract_with_scores
from src.ml.combat_predictor import predictor, MIN_TRAINING_SAMPLES
from src.ml.survival_scorer import label_combat_events_with_scores, calculate_survival_score
from src import logger


RETRAIN_EVERY_N_GAMES = 3  # Retrain more often (regression needs less data)


def train_combat_model() -> float:
    """
    Train the combat predictor using survival scores (regression).
    Can learn from ALL games — doesn't need both wins and losses.
    Returns R² accuracy.
    """
    games = GameDataCollector.load_all_games()

    # Label combat events with survival scores
    labeled = label_combat_events_with_scores(games)

    if len(labeled) < MIN_TRAINING_SAMPLES:
        logger.info(
            f"ML: {len(labeled)}/{MIN_TRAINING_SAMPLES} combat events collected. "
            f"Need more data before training."
        )
        return 0.0

    # Extract features with scores (not binary labels)
    X, y = batch_extract_with_scores(labeled)
    if len(X) < MIN_TRAINING_SAMPLES:
        return 0.0

    accuracy = predictor.train(X, y)

    # Log game survival scores for insight
    if games:
        scores = [calculate_survival_score(g) for g in games]
        avg_score = sum(scores) / len(scores)
        best_score = max(scores)
        logger.info(
            f"ML: Survival scores — avg: {avg_score:.2f}, best: {best_score:.2f}, "
            f"games: {len(games)}"
        )

    logger.ml_update(len(games), accuracy)
    return accuracy


def retrain_if_needed() -> bool:
    """
    Check if enough new data to justify retraining.
    Retrains every RETRAIN_EVERY_N_GAMES games.
    Returns True if retrained.
    """
    total_games = GameDataCollector.get_total_games_played()

    # Build labeled events count
    games = GameDataCollector.load_all_games()
    labeled = label_combat_events_with_scores(games)
    total_events = len(labeled)

    # Not enough data yet
    if total_events < MIN_TRAINING_SAMPLES:
        return False

    # Check if we should retrain (every N games)
    if total_games > 0 and total_games % RETRAIN_EVERY_N_GAMES == 0:
        logger.info(f"ML: Retraining model after {total_games} games (survival score regression)...")
        accuracy = train_combat_model()
        if accuracy >= 0:
            logger.success(f"ML: Model retrained. R² score: {accuracy:.2f}")
            return True

    # Also retrain if model hasn't been trained but we have enough data
    if not predictor.is_trained and total_events >= MIN_TRAINING_SAMPLES:
        logger.info("ML: First-time model training (survival score regression)...")
        accuracy = train_combat_model()
        if accuracy >= 0:
            logger.success(f"ML: Initial model trained. R² score: {accuracy:.2f}")
            return True

    return False


def get_model_status() -> str:
    """Get current model status summary."""
    games = GameDataCollector.load_all_games()
    labeled = label_combat_events_with_scores(games)
    total_events = len(labeled)
    total_games = len(games)

    if predictor.is_trained:
        return (
            f"ML Model: ACTIVE (regression) | "
            f"R² score: {predictor.accuracy:.2f} | "
            f"Trained on: {predictor.training_samples} events | "
            f"Total games: {total_games}"
        )
    else:
        return (
            f"ML Model: COLLECTING DATA | "
            f"Events: {total_events}/{MIN_TRAINING_SAMPLES} needed | "
            f"Total games: {total_games}"
        )


# Allow running as standalone module
if __name__ == "__main__":
    print("=" * 50)
    print("Molty Royale ML Training (Survival Score)")
    print("=" * 50)
    print(get_model_status())
    print()
    accuracy = train_combat_model()
    if accuracy >= 0:
        print(f"\nTraining complete! R² score: {accuracy:.2f}")
    else:
        print("\nInsufficient data for training.")
    print(get_model_status())
