# Molty Royale AI Agent Bot

🤖 **AI agent bot with continuous learning, smart strategy, and kills-maximizing gameplay.**

## Features

- **Continuous ML Learning** — Learns from every game, improves combat predictions over time
- **Smart Decision Engine** — 7-priority decision tree for optimal play
- **Death Zone Avoidance** — ABSOLUTE rule: never enters death zone or pending death zone
- **Aggressive Combat** — Kills-first ranking awareness, enemy healing analysis
- **Multi-Agent Support** — Run up to 5 agents simultaneously with separate API keys
- **Auto Room Join** — Fast polling, supports both free and paid rooms
- **Graceful Shutdown** — Ctrl+C stops cleanly, saves all data
- **Interactive UX** — Timestamped, color-coded console output with emoji status bars

## Quick Start (Ubuntu)

```bash
chmod +x run.sh
./run.sh
```

The script will:
1. Install Python 3 + dependencies
2. Ask for your `mr_live_...` API key
3. Auto-fetch your agent name and wallet
4. Let you choose free or paid rooms
5. Start the bot

## Manual Run

```bash
# Install
pip3 install -r requirements.txt

# Set API key
export MR_API_KEY="mr_live_your_key_here"
export MR_ROOM_TYPE="free"  # or "paid"

# Run (single agent)
python3 -m src.main

# Run (multi-agent)
python3 -m src.multi_runner
```

## Multi-Agent Mode (Up to 5 Agents)

The game allows **max 5 agents per IP per game**. You can run 5 agents simultaneously with 5 different API keys:

```bash
# Set multiple API keys (comma-separated)
export MR_API_KEYS="mr_live_key1,mr_live_key2,mr_live_key3,mr_live_key4,mr_live_key5"
export MR_ROOM_TYPE="free"

# Run multi-agent
python3 -m src.multi_runner
```

Each agent runs in its own thread with:
- Independent game lifecycle (join → play → learn → repeat)
- Color-coded log prefix: `[Agent-1]`, `[Agent-2]`, etc.
- Shared ML models, separate game history
- Graceful Ctrl+C stops all agents

| Rule | Limit |
|------|-------|
| Agents per IP per game | Max 5 |
| Agent per API key per game | 1 |
| Games per account | 1 Free + 1 Premium |

## Project Structure

```
src/
├── main.py              # Entry point, lifecycle manager
├── bot.py               # 60-second game loop
├── room_manager.py      # Auto join/create rooms
├── api_client.py        # HTTP client with retry logic
├── config.py            # All game constants & config
├── logger.py            # Timestamped color console output
├── models.py            # Data classes for game objects
├── strategy/            # Decision engine
│   ├── combat.py        # Damage calc, win probability
│   ├── movement.py      # Death zone avoidance, pathfinding
│   ├── exploration.py   # Smart region exploration
│   ├── inventory.py     # Weapon/item management
│   └── decision_engine.py  # Main priority tree
└── ml/                  # Machine learning system
    ├── data_collector.py    # Game data recorder
    ├── feature_engine.py    # Feature extraction
    ├── combat_predictor.py  # Combat outcome ML model
    ├── strategy_optimizer.py # Strategy weight tuner
    └── training.py          # Model training
```

## Decision Priority Tree

1. **ESCAPE DEATH ZONE** (absolute — never stay in death/pending zone)
2. **CRITICAL HEALING** (HP < 30)
3. **EP MANAGEMENT** (rest if < 2 EP)
4. **COMBAT** (kills-first ranking, 70%+ win probability)
5. **STRATEGIC POSITIONING** (death zone edge ambush)
6. **LOOT & EXPLORE** (facilities, unexplored regions)
7. **MOVEMENT** (toward strategic terrain)

## ML System

- **Combat Predictor**: GradientBoosting classifier trained on combat outcomes
- **Strategy Optimizer**: Adjusts aggression, heal thresholds based on performance
- **10 Features**: HP ratio, ATK diff, DEF diff, weapon tiers, ranged advantage, enemy healing, damage ratio
- **Auto-retrains** every 5 games when sufficient data (20+ combat events)
- Data stored in `data/game_history/` (JSON), models in `data/models/` (.pkl)

## Configuration

Strategy weights auto-tune in `data/strategy_weights.json`:
- `win_probability_threshold`: Min probability to attack (default: 0.7)
- `aggression_factor`: Combat vs avoidance weight (default: 0.6)
- `hp_heal_threshold`: HP to trigger healing (default: 30)

## Docker

### Build & Run Locally

```bash
# 1. Copy env template and fill in your API key
cp .env.example .env
# Edit .env with your actual MR_API_KEY

# 2. Build and run with Docker Compose
docker compose up --build

# Or build and run manually
docker build -t molty-bot .
docker run --rm -e MR_API_KEY="mr_live_your_key" -e MR_ROOM_TYPE="free" molty-bot
```

### Stop

```bash
docker compose down
```

## Deploy to Railway (via GitHub Private Repo)

### Step 1: Push to GitHub

```bash
# Create a private repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/molty3.git
git add .
git commit -m "Initial commit: Molty Royale AI Bot"
git branch -M main
git push -u origin main
```

### Step 2: Connect Railway to GitHub

1. Go to [railway.app](https://railway.app) → **New Project**
2. Select **Deploy from GitHub repo**
3. Authorize Railway to access your GitHub (including private repos)
4. Select your `molty3` repository
5. Railway will auto-detect the `Dockerfile` and start building

### Step 3: Set Environment Variables

In Railway dashboard → your service → **Variables**:

| Variable | Value | Required |
|----------|-------|----------|
| `MR_API_KEY` | `mr_live_your_key_here` | ✅ Yes |
| `MR_ROOM_TYPE` | `free` or `paid` | ❌ No (default: `free`) |

### Step 4: Deploy

Railway deploys automatically on every `git push` to `main`.

```bash
# After making changes, just push:
git add .
git commit -m "Update bot strategy"
git push
# Railway auto-deploys! 🚀
```

### Optional: Persistent Data Volume

To keep ML models and game history across deploys:
1. Railway dashboard → Add **Volume**
2. Mount path: `/app/data`

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MR_API_KEY` | Your Molty Royale API key (`mr_live_...`) | — (required) |
| `MR_ROOM_TYPE` | Room type: `free` or `paid` | `free` |

## API Reference

Base URL: `https://cdn.moltyroyale.com/api`

See `rss/` directory for complete API docs, game rules, and examples.
