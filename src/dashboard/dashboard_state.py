"""
Molty Royale AI Bot — Dashboard State Store
Thread-safe in-memory store for agent states, logs, and kill feed.
Emits updates via Socket.IO when available.
"""

import threading
import time
import re
from collections import deque
from datetime import datetime


# ANSI escape code stripper
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    return _ANSI_RE.sub('', text)


class DashboardState:
    """Thread-safe shared state for the dashboard."""

    MAX_LOGS = 500
    MAX_KILL_FEED = 100

    def __init__(self):
        self._lock = threading.Lock()
        self._agents = {}          # agent_label -> agent state dict
        self._logs = {}            # agent_label -> deque of log entries
        self._global_logs = deque(maxlen=self.MAX_LOGS)
        self._kill_feed = deque(maxlen=self.MAX_KILL_FEED)
        self._socketio = None      # Set when server starts
        self._start_time = time.time()
        self._total_games = 0
        self._total_wins = 0

    def set_socketio(self, sio):
        """Register Socket.IO instance for real-time emit."""
        self._socketio = sio

    # ─── Agent State ────────────────────────────────────────────

    def update_agent_state(self, agent_label: str, state_data: dict):
        """Update an agent's state and emit via WebSocket."""
        with self._lock:
            if agent_label not in self._agents:
                self._agents[agent_label] = {}
                self._logs[agent_label] = deque(maxlen=self.MAX_LOGS)

            self._agents[agent_label].update(state_data)
            self._agents[agent_label]["last_update"] = datetime.now().isoformat()

        if self._socketio:
            self._socketio.emit("state_update", {
                "agent": agent_label,
                "data": self._agents[agent_label],
            })

    def update_agent_status(self, agent_label: str, status: str):
        """Quick status update (idle/searching/waiting/playing/dead)."""
        self.update_agent_state(agent_label, {"status": status})

    # ─── Logging ────────────────────────────────────────────────

    def push_log(self, agent_label: str, level: str, message: str):
        """Push a log entry and emit via WebSocket."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": strip_ansi(message),
            "agent": agent_label,
        }

        with self._lock:
            # Per-agent log
            if agent_label and agent_label in self._logs:
                self._logs[agent_label].append(entry)
            elif agent_label:
                self._logs[agent_label] = deque(maxlen=self.MAX_LOGS)
                self._logs[agent_label].append(entry)

            # Global log
            self._global_logs.append(entry)

        if self._socketio:
            self._socketio.emit("new_log", entry)

    # ─── Kill Feed ──────────────────────────────────────────────

    def push_kill(self, killer: str, victim: str, weapon: str = "Fist",
                  is_monster: bool = False, agent_label: str = ""):
        """Push a kill event to the feed."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "killer": killer,
            "victim": victim,
            "weapon": weapon,
            "is_monster": is_monster,
            "agent_label": agent_label,
        }

        with self._lock:
            self._kill_feed.append(entry)

        if self._socketio:
            self._socketio.emit("kill_feed", entry)

    # ─── Global Stats ──────────────────────────────────────────

    def increment_games(self):
        with self._lock:
            self._total_games += 1

    def increment_wins(self):
        with self._lock:
            self._total_wins += 1

    # ─── Getters ────────────────────────────────────────────────

    def get_full_snapshot(self) -> dict:
        """Get complete state for initial page load."""
        with self._lock:
            agents = dict(self._agents)
            logs = {k: list(v) for k, v in self._logs.items()}
            global_logs = list(self._global_logs)
            kill_feed = list(self._kill_feed)
            uptime = int(time.time() - self._start_time)

        return {
            "agents": agents,
            "logs": logs,
            "global_logs": global_logs,
            "kill_feed": kill_feed,
            "total_games": self._total_games,
            "total_wins": self._total_wins,
            "uptime": uptime,
        }

    def get_agent_labels(self) -> list:
        """Get list of all known agent labels."""
        with self._lock:
            return list(self._agents.keys())


# Singleton
state = DashboardState()
