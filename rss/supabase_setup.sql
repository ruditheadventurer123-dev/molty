-- ═══════════════════════════════════════════════════════════
-- Molty Royale AI Bot — Supabase Schema Setup
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ═══════════════════════════════════════════════════════════

-- Game History Table (main storage)
CREATE TABLE IF NOT EXISTS game_history (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    game_id         TEXT NOT NULL,
    agent_name      TEXT DEFAULT '',
    started_at      TEXT DEFAULT '',
    ended_at        TEXT DEFAULT '',
    total_turns     INTEGER DEFAULT 0,
    is_winner       BOOLEAN DEFAULT FALSE,
    final_rank      INTEGER DEFAULT 0,
    kills           INTEGER DEFAULT 0,
    rewards         INTEGER DEFAULT 0,
    regions_visited INTEGER DEFAULT 0,
    combat_events_count INTEGER DEFAULT 0,
    items_collected_count INTEGER DEFAULT 0,
    full_data       TEXT DEFAULT '{}'
);

-- Combat Events Table (for ML training)
CREATE TABLE IF NOT EXISTS combat_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    game_id         TEXT NOT NULL,
    timestamp       TEXT DEFAULT '',
    our_hp          INTEGER DEFAULT 0,
    our_weapon      TEXT DEFAULT 'Fist',
    our_weapon_bonus INTEGER DEFAULT 0,
    enemy_hp        INTEGER DEFAULT 0,
    enemy_weapon    TEXT DEFAULT 'Fist',
    enemy_has_healing BOOLEAN DEFAULT FALSE,
    result          TEXT DEFAULT 'pending',
    damage_dealt    INTEGER DEFAULT 0,
    damage_taken    INTEGER DEFAULT 0
);

-- Enable Row Level Security (recommended by Supabase)
ALTER TABLE game_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE combat_events ENABLE ROW LEVEL SECURITY;

-- Allow all operations with service key (bot uses service key)
CREATE POLICY "Allow all for service role" ON game_history
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all for service role" ON combat_events
    FOR ALL USING (true) WITH CHECK (true);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_game_history_game_id ON game_history(game_id);
CREATE INDEX IF NOT EXISTS idx_combat_events_game_id ON combat_events(game_id);
