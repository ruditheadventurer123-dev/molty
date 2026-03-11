"""
Molty Royale AI Bot — Interactive Logger
Timestamped, color-coded console output with premium UX.
Thread-safe with per-agent prefix support for multi-agent mode.
Hooks into dashboard for real-time WebSocket log streaming.
"""

import sys
import os
import threading
from datetime import datetime

# ─── Thread-Safe Logging ────────────────────────────────────────────
_print_lock = threading.Lock()
_thread_local = threading.local()

# ─── Dashboard Hook ─────────────────────────────────────────────────
def _emit_log(level: str, message: str):
    """Push log entry to dashboard state (if available)."""
    try:
        from src.dashboard.dashboard_state import state as dash
        agent_label = getattr(_thread_local, 'prefix', '').strip('[] ')
        dash.push_log(agent_label, level, message)
    except Exception:
        pass  # Dashboard not available — that's fine

# Agent prefix colors for multi-agent mode
_AGENT_COLORS = []

def set_prefix(label: str, color_index: int = 0):
    """Set per-thread log prefix (e.g. '[Agent-1]')."""
    _thread_local.prefix = label
    _thread_local.color_index = color_index

def _get_prefix():
    """Get current thread's log prefix."""
    prefix = getattr(_thread_local, 'prefix', '')
    if not prefix:
        return ''
    # Color the prefix based on agent index
    colors = [Fore.CYAN, Fore.GREEN, Fore.YELLOW, Fore.MAGENTA, Fore.BLUE]
    idx = getattr(_thread_local, 'color_index', 0) % len(colors)
    return f"{colors[idx]}{Style.BRIGHT}{prefix}{Fore.WHITE} "

def _safe_print(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)

# ─── Color Support ──────────────────────────────────────────────────
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class _Dummy:
        def __getattr__(self, _):
            return ""
    Fore = _Dummy()
    Style = _Dummy()

# ─── Symbols ────────────────────────────────────────────────────────
SYM_SWORD   = "[X]"
SYM_SHIELD  = "[O]"
SYM_HEART   = "<3"
SYM_BOLT    = "!"
SYM_SKULL   = "(x_x)"
SYM_TROPHY  = "[W]"
SYM_MAP     = "[M]"
SYM_EYE     = "(o)"
SYM_WARN    = "/!\\"
SYM_FIRE    = "^^^"
SYM_CHECK   = "[v]"
SYM_CROSS   = "[x]"
SYM_CLOCK   = "[T]"
SYM_GEAR    = "{*}"
SYM_STAR    = "[*]"
SYM_MONEY   = "[$]"
SYM_RUN     = ">>"
SYM_REST    = "zZ"
SYM_SEARCH  = "[?]"
SYM_HEAL    = "[+]"
SYM_BOT     = "[B]"
SYM_ZONE    = "(!)"

# ─── Timestamp ──────────────────────────────────────────────────────
def _ts():
    """Return current timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ─── Core Logging Functions ────────────────────────────────────────
def banner():
    """Print startup banner."""
    prefix = _get_prefix()
    lines = [
        "",
        f"{prefix}{Fore.CYAN}{Style.BRIGHT}==========================================================",
        f"{prefix}{Fore.CYAN}{Style.BRIGHT}           {SYM_BOT}  MOLTY ROYALE AI AGENT BOT  {SYM_BOT}               ",
        f"{prefix}{Fore.CYAN}{Style.BRIGHT}      Continuous Learning * Smart Strategy * Kills Max    ",
        f"{prefix}{Fore.CYAN}{Style.BRIGHT}==========================================================",
        "",
    ]
    with _print_lock:
        for line in lines:
            print(line)

def info(msg, symbol=""):
    """Standard info message with timestamp."""
    sym = f"{symbol} " if symbol else ""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {Fore.CYAN}{sym}{Fore.WHITE}{msg}")
    _emit_log("info", f"{symbol} {msg}" if symbol else msg)

def success(msg, symbol=SYM_CHECK):
    """Success message."""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {symbol} {Fore.GREEN}{msg}")
    _emit_log("success", f"{symbol} {msg}")

def warning(msg, symbol=SYM_WARN):
    """Warning message."""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {symbol} {Fore.YELLOW}{msg}")
    _emit_log("warning", f"{symbol} {msg}")

def error(msg, symbol=SYM_CROSS):
    """Error message."""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {symbol} {Fore.RED}{msg}")
    _emit_log("error", f"{symbol} {msg}")

def critical(msg, symbol=SYM_SKULL):
    """Critical message."""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {symbol} {Fore.RED}{Style.BRIGHT}{msg}")
    _emit_log("critical", f"{symbol} {msg}")

def action(action_type, detail=""):
    """Log a game action with appropriate symbol."""
    symbols = {
        "move": SYM_RUN,
        "explore": SYM_SEARCH,
        "attack": SYM_SWORD,
        "use_item": SYM_HEAL,
        "interact": SYM_GEAR,
        "rest": SYM_REST,
        "pickup": SYM_MONEY,
        "equip": SYM_SHIELD,
        "talk": "talk",
        "whisper": "whisper",
        "broadcast": "broadcast",
    }
    sym = symbols.get(action_type, SYM_GEAR)
    detail_str = f" -> {detail}" if detail else ""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {sym} {Fore.MAGENTA}{Style.BRIGHT}ACTION: {action_type}{Fore.WHITE}{detail_str}")
    _emit_log("action", f"{sym} ACTION: {action_type}{detail_str}")

def status_bar(hp, max_hp, ep, max_ep, kills, turn, region_name, weapon_name="Fist"):
    """Print a compact status bar."""
    hp_pct = hp / max_hp if max_hp > 0 else 0
    hp_color = Fore.GREEN if hp_pct > 0.5 else (Fore.YELLOW if hp_pct > 0.25 else Fore.RED)
    ep_color = Fore.CYAN if ep >= 2 else Fore.RED

    bar = (
        f"{_get_prefix()}{Fore.WHITE}[{_ts()}] "
        f"{SYM_CLOCK} T{turn:02d} | "
        f"{SYM_HEART} {hp_color}{hp}/{max_hp}{Fore.WHITE} | "
        f"{SYM_BOLT} {ep_color}{ep}/{max_ep}{Fore.WHITE} | "
        f"{SYM_SWORD} {Fore.YELLOW}{weapon_name}{Fore.WHITE} | "
        f"{SYM_SKULL} {Fore.RED}{kills}{Fore.WHITE} kills | "
        f"{SYM_MAP} {Fore.BLUE}{region_name}"
    )
    _safe_print(bar)

def death_zone_alert(region_name, is_pending=False):
    """Alert for death zone proximity."""
    if is_pending:
        warning(f"PENDING DEATH ZONE: {region_name} will become death zone soon! Evacuating!", SYM_ZONE)
    else:
        critical(f"IN DEATH ZONE: {region_name}! Taking 1.34 HP/sec damage! EMERGENCY MOVE!", SYM_ZONE)

def game_result(rank, kills, moltz, is_winner):
    """Print game end results."""
    prefix = _get_prefix()
    with _print_lock:
        print("")
        if is_winner:
            print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}{'=' * 58}")
            print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}  {SYM_TROPHY}  VICTORY!  {SYM_TROPHY}")
            print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}{'=' * 58}")
        else:
            print(f"{prefix}{Fore.WHITE}{'-' * 58}")
            print(f"{prefix}{Fore.WHITE}  {SYM_STAR} Game Over")
            print(f"{prefix}{Fore.WHITE}{'-' * 58}")

        print(f"{prefix}  Rank: #{rank}  |  Kills: {kills}  |  Moltz: {moltz}")
        print(f"{prefix}{'=' * 58 if is_winner else '-' * 58}")
        print("")

def combat_analysis(target_name, target_hp, win_prob, our_dmg, their_dmg, has_healing=False):
    """Print combat analysis before attack decision."""
    prob_color = Fore.GREEN if win_prob >= 0.7 else (Fore.YELLOW if win_prob >= 0.5 else Fore.RED)
    heal_note = f" {Fore.YELLOW}(has healing items!)" if has_healing else ""
    _safe_print(
        f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {SYM_EYE} "
        f"{Fore.CYAN}COMBAT ANALYSIS: {Fore.WHITE}{target_name} "
        f"(HP:{target_hp}{heal_note}{Fore.WHITE}) | "
        f"Win: {prob_color}{win_prob:.0%}{Fore.WHITE} | "
        f"Our DMG: {Fore.GREEN}{our_dmg}{Fore.WHITE} | "
        f"Their DMG: {Fore.RED}{their_dmg}"
    )

def separator(char="-", length=58):
    """Print a visual separator."""
    _safe_print(f"{_get_prefix()}{Fore.WHITE}{char * length}")

def turn_header(turn_num, total_turns=56):
    """Print turn header."""
    game_day = ((turn_num - 1) // 4) + 1
    time_slot = ((turn_num - 1) % 4) * 6 + 6  # 06, 12, 18, 00
    if time_slot >= 24:
        time_slot = 0
    prefix = _get_prefix()
    with _print_lock:
        print("")
        print(f"{prefix}{Fore.WHITE}{'=' * 58}")
        print(
            f"{prefix}{Fore.CYAN}{Style.BRIGHT}  {SYM_CLOCK} TURN {turn_num}/{total_turns} "
            f"| Day {game_day} {time_slot:02d}:00 "
            f"| [{_ts()}]"
        )
        print(f"{prefix}{Fore.WHITE}{'=' * 58}")

def shutdown_message():
    """Print graceful shutdown message."""
    prefix = _get_prefix()
    with _print_lock:
        print("")
        print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}{'-' * 58}")
        print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}  {SYM_BOT} Bot shutting down gracefully...")
        print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}  Saving data and cleaning up...")
        print(f"{prefix}{Fore.YELLOW}{Style.BRIGHT}{'-' * 58}")
        print("")

def waiting_for_game(check_count, room_type="free"):
    """Display waiting status."""
    dots = "." * ((check_count % 3) + 1)
    _safe_print(
        f"{_get_prefix()}{Fore.WHITE}[{_ts()}] {SYM_SEARCH} "
        f"Looking for {room_type} game{dots}   "
    )

def joined_game(game_name, game_id, agent_name):
    """Log successful game join."""
    success(f"Joined game: {game_name}", SYM_STAR)
    info(f"  Game ID  : {game_id}")
    info(f"  Agent    : {agent_name}")

def ml_update(games_played, model_accuracy=None):
    """Log ML model update."""
    acc_str = f" | Accuracy: {model_accuracy:.1%}" if model_accuracy else ""
    info(f"ML Model updated (trained on {games_played} games{acc_str})", SYM_GEAR)
