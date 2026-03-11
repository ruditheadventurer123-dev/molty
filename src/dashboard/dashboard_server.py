"""
Molty Royale AI Bot — Dashboard Web Server
Flask + Socket.IO server for real-time agent monitoring.
Runs as a daemon thread alongside the bot.
"""

import os
import threading
import time
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit
from src.dashboard.dashboard_state import state as dashboard_state


app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(24)

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Register socketio with shared state
dashboard_state.set_socketio(socketio)


def _auth_required(f):
    """Decorator: require login if DASHBOARD_PASSWORD is set."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if DASHBOARD_PASSWORD and not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    """Simple password login page."""
    if not DASHBOARD_PASSWORD:
        session["authenticated"] = True
        return redirect(url_for("index"))

    error = ""
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Wrong password"

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Molty Royale — Login</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0e17;font-family:'Inter',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;color:#e0e6f0}}
.login-box{{background:rgba(15,20,35,0.95);border:1px solid rgba(99,102,241,0.3);border-radius:16px;padding:40px;width:340px;text-align:center}}
.login-box h1{{font-size:22px;margin-bottom:8px;background:linear-gradient(135deg,#818cf8,#6366f1);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.login-box p{{font-size:13px;color:#8892b0;margin-bottom:24px}}
input[type=password]{{width:100%;padding:12px 16px;background:rgba(30,40,70,0.8);border:1px solid rgba(99,102,241,0.3);border-radius:8px;color:#e0e6f0;font-size:14px;margin-bottom:16px;outline:none}}
input[type=password]:focus{{border-color:#6366f1}}
button{{width:100%;padding:12px;background:linear-gradient(135deg,#6366f1,#818cf8);border:none;border-radius:8px;color:#fff;font-size:14px;font-weight:600;cursor:pointer}}
button:hover{{opacity:0.9}}
.error{{color:#f87171;font-size:13px;margin-bottom:12px}}
</style></head><body>
<div class="login-box">
<h1>⚔️ MOLTY ROYALE</h1>
<p>Agent Dashboard</p>
{'<div class="error">'+error+'</div>' if error else ''}
<form method="post"><input type="password" name="password" placeholder="Enter password" autofocus>
<button type="submit">Login</button></form></div></body></html>"""


@app.route("/")
@_auth_required
def index():
    """Serve the dashboard page."""
    return render_template("index.html")


@app.route("/api/state")
@_auth_required
def api_state():
    """REST endpoint for full state snapshot."""
    return jsonify(dashboard_state.get_full_snapshot())


@socketio.on("connect")
def handle_connect():
    """Send full state snapshot on new connection (to requesting client ONLY)."""
    snapshot = dashboard_state.get_full_snapshot()
    emit("full_state", snapshot)  # emit() sends to THIS client only


_server_thread = None


def start_dashboard(port: int = None):
    """Start the dashboard server in a daemon thread."""
    global _server_thread

    if _server_thread and _server_thread.is_alive():
        return  # Already running

    port = port or int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 8080)))

    def _run():
        try:
            # Suppress Flask/Werkzeug startup logs to keep console clean
            import logging
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.WARNING)

            socketio.run(
                app,
                host="0.0.0.0",
                port=port,
                debug=False,
                use_reloader=False,
                allow_unsafe_werkzeug=True,
            )
        except Exception as e:
            print(f"[Dashboard] Server error: {e}")

    _server_thread = threading.Thread(target=_run, daemon=True, name="Dashboard")
    _server_thread.start()

    # Brief wait to let server bind
    time.sleep(1)

    from src import logger
    auth_note = " (password protected)" if DASHBOARD_PASSWORD else " (no auth)"
    logger.info(f"[Dashboard] Running at http://0.0.0.0:{port}{auth_note}")


def get_system_stats() -> dict:
    """Get CPU and memory stats."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0)
        proc = psutil.Process()
        rss = proc.memory_info().rss  # Process RSS (actual memory used)
        return {
            "cpu": f"{cpu:.0f}%",
            "ram_used": f"{rss // (1024*1024)}MB",
        }
    except ImportError:
        return {"cpu": "N/A", "ram_used": "N/A"}


def emit_system_stats():
    """Background task to emit system stats every 5 seconds."""
    while True:
        try:
            stats = get_system_stats()
            if dashboard_state._socketio:
                dashboard_state._socketio.emit("system_stats", stats)
        except Exception:
            pass
        time.sleep(5)


def start_stats_emitter():
    """Start background stats emitter thread."""
    t = threading.Thread(target=emit_system_stats, daemon=True, name="StatsEmitter")
    t.start()
