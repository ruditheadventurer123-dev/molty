"""
Molty Royale AI Bot — Multi-Agent Runner
Run up to 5 agents simultaneously with separate API keys.
Each agent runs in its own thread with independent game lifecycle.

Usage:
    # Single agent (backward compatible)
    MR_API_KEY=mr_live_xxx python -m src.multi_runner

    # Multiple agents (comma-separated)
    MR_API_KEYS=mr_live_key1,mr_live_key2,mr_live_key3 python -m src.multi_runner
"""

import signal
import sys
import os
import threading
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import MoltyBot
from src.config import ensure_data_dirs, load_room_type
from src import logger


MAX_AGENTS_PER_IP = 5


def load_api_keys():
    """
    Load API keys from environment.
    Priority: MR_API_KEYS (comma-separated) > MR_API_KEY (single).
    Returns list of keys (max 5).
    """
    # Multi-key format
    multi_keys = os.environ.get("MR_API_KEYS", "").strip()
    if multi_keys:
        keys = [k.strip() for k in multi_keys.split(",") if k.strip()]
        if len(keys) > MAX_AGENTS_PER_IP:
            logger.warning(
                f"Too many API keys ({len(keys)}). "
                f"Max {MAX_AGENTS_PER_IP} per IP. Using first {MAX_AGENTS_PER_IP}."
            )
            keys = keys[:MAX_AGENTS_PER_IP]
        return keys

    # Single key (backward compatible)
    single_key = os.environ.get("MR_API_KEY", "").strip()
    if single_key:
        return [single_key]

    # Try credentials file
    from src.config import load_api_key
    key = load_api_key()
    if key:
        return [key]

    return []


def run_agent(api_key, room_type, room_name, agent_label, stop_event, is_fallback_host=False):
    """Run a single agent in its own thread."""
    bot = MoltyBot(api_key=api_key, room_type=room_type, room_name=room_name, agent_label=agent_label, is_fallback_host=is_fallback_host)

    # Monitor stop event to gracefully stop this agent
    def check_stop():
        while not stop_event.is_set():
            time.sleep(1)
        bot._running = False
        if bot.bot:
            bot.bot.stop()
        if bot.room_manager:
            bot.room_manager.stop()

    stop_thread = threading.Thread(target=check_stop, daemon=True)
    stop_thread.start()

    try:
        bot.run()
    except Exception as e:
        logger.set_prefix(f"[{agent_label}]", int(agent_label.split('-')[-1]) - 1)
        logger.error(f"Agent crashed: {type(e).__name__}: {e}")


def main():
    """Multi-agent entry point."""
    # Print multi-agent banner
    try:
        from colorama import Fore, Style
    except ImportError:
        class _D:
            def __getattr__(self, _): return ""
        Fore = _D()
        Style = _D()

    print("")
    print(f"{Fore.CYAN}{Style.BRIGHT}==========================================================")
    print(f"{Fore.CYAN}{Style.BRIGHT}      MOLTY ROYALE - MULTI-AGENT RUNNER")
    print(f"{Fore.CYAN}{Style.BRIGHT}      Up to 5 agents - 5 API keys - 1 IP")
    print(f"{Fore.CYAN}{Style.BRIGHT}==========================================================")
    print("")

    # Load API keys
    api_keys = load_api_keys()
    if not api_keys:
        logger.error("No API keys found!")
        logger.info("Set MR_API_KEY or MR_API_KEYS environment variable.")
        logger.info("  Single:  MR_API_KEY=mr_live_xxx")
        logger.info("  Multi:   MR_API_KEYS=mr_live_key1,mr_live_key2,mr_live_key3")
        sys.exit(1)

    room_type = load_room_type()
    
    from src.config import AUTO_ROOM_NAME
    room_name = AUTO_ROOM_NAME
    
    ensure_data_dirs()

    # Initialize Supabase cloud storage (graceful if not configured)
    try:
        from src.storage import supabase_store
        supabase_store.init()
    except Exception:
        pass

    logger.success(f"Loaded {len(api_keys)} API key(s)")
    for i, key in enumerate(api_keys):
        logger.info(f"  Agent-{i+1}: {key[:12]}...{key[-4:]}")
    logger.info(f"Room type: {room_type.upper()}", logger.SYM_GEAR)
    logger.info(f"Target Room: {room_name}", logger.SYM_STAR)
    logger.separator("=")

    # ── Start Dashboard Server ─────────────────────────────────
    try:
        from src.dashboard.dashboard_server import start_dashboard, start_stats_emitter
        start_dashboard()
        start_stats_emitter()
    except Exception as e:
        logger.warning(f"Dashboard server failed to start: {e}")
        logger.info("Bot will continue without dashboard.")

    # Stop event for graceful shutdown
    stop_event = threading.Event()

    def signal_handler(signum, frame):
        if stop_event.is_set():
            # Second Ctrl+C = force exit
            print("\nForce exit!")
            os._exit(1)
        print("")
        logger.warning("Shutdown signal received. Stopping all agents...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Spawn agent threads
    threads = []
    for i, key in enumerate(api_keys):
        label = f"Agent-{i+1}"
        t = threading.Thread(
            target=run_agent,
            args=(key, room_type, room_name, label, stop_event, i == 0),
            name=label,
            daemon=False,
        )
        threads.append(t)

    # Start threads with very small stagger (0.1s)
    # This ensures they join almost immediately before 100/100 random players fill the free room
    for i, t in enumerate(threads):
        t.start()
        if i < len(threads) - 1:
            time.sleep(0.1)

    logger.separator("=")
    logger.success(f"All {len(threads)} agent(s) started! Press Ctrl+C to stop all.")
    logger.separator("=")

    # Wait for all threads to finish
    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=1)
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join(timeout=10)

    # Final summary
    print("")
    logger.separator("=")
    logger.success("All agents stopped. Goodbye!", logger.SYM_BOT)
    logger.separator("=")


if __name__ == "__main__":
    main()
