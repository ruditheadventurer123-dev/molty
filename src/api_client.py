"""
Molty Royale AI Bot — API Client (Hardened)
HTTP client with aggressive retry, connection pooling, keep-alive,
split timeouts, and exponential backoff for unreliable Cloudflare-fronted API.
"""

import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional
from src import logger
from src.config import BASE_URL, API_KEY


class APIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, message: str, code: str = "", status_code: int = 0):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(f"[{code}] {message}" if code else message)


def _create_session(api_key: str) -> requests.Session:
    """
    Create a requests.Session with:
    - urllib3 Retry on transport-level errors (timeouts, connection resets)
    - Connection pooling (10 connections, keep-alive)
    - Proper headers for Cloudflare
    """
    session = requests.Session()

    # urllib3 automatic retry for transport errors
    # This retries on: connection errors, read timeouts, 502/503/504
    retry_strategy = Retry(
        total=5,                     # Up to 5 retries per request
        backoff_factor=1.5,          # Wait 1.5s, 3s, 4.5s, 6.75s between retries
        backoff_max=15,              # Cap backoff at 15 seconds
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these HTTP statuses
        allowed_methods=["GET", "POST", "PUT"],       # Retry all our methods
        raise_on_status=False,       # Don't raise, let us handle
    )

    # Mount adapter with connection pool + retry
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,      # Connection pool size
        pool_maxsize=10,          # Max connections in pool
        pool_block=False,         # Don't block on full pool
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Headers optimized for Cloudflare
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "keep-alive",
        "User-Agent": "MoltyRoyaleBot/2.0 (AI Agent; Python/requests)",
    })

    if api_key:
        session.headers.update({"X-API-Key": api_key})

    return session


class MoltyAPIClient:
    """HTTP client for all Molty Royale API endpoints (hardened for unreliable network)."""

    # Split timeouts: (connect_timeout, read_timeout)
    # Short connect to fail fast on DNS/routing issues
    # Longer read to tolerate slow server responses
    TIMEOUT_NORMAL = (10, 30)       # Normal requests: 10s connect, 30s read
    TIMEOUT_ACTION = (10, 20)       # Action requests: slightly tighter
    TIMEOUT_POLL = (8, 15)          # Polling (list games): tighter

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY
        self.base_url = BASE_URL
        self.session = _create_session(self.api_key)
        self._last_request_time = 0
        self._min_request_interval = 0.025  # 40 req/s (under 50/s limit)
        self._consecutive_failures = 0

    def _rate_limit(self):
        """Enforce rate limiting to stay under 50 calls/sec."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, path: str, json_data: dict = None,
                 retries: int = 3, retry_delay: float = 2.0,
                 timeout: tuple = None) -> dict:
        """
        Make an HTTP request with application-level retry logic.
        urllib3 handles transport-level retries automatically.
        This layer handles API-level errors and additional retry logic.
        """
        url = f"{self.base_url}{path}"
        timeout = timeout or self.TIMEOUT_NORMAL
        last_error = None

        for attempt in range(retries):
            try:
                self._rate_limit()

                if method == "GET":
                    resp = self.session.get(url, timeout=timeout)
                elif method == "POST":
                    resp = self.session.post(url, json=json_data, timeout=timeout)
                elif method == "PUT":
                    resp = self.session.put(url, json=json_data, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # Reset failure counter on successful HTTP response
                self._consecutive_failures = 0

                data = resp.json()

                if resp.status_code == 202:
                    return data

                if not data.get("success", False):
                    err = data.get("error", {})
                    error_code = err.get("code", "UNKNOWN")
                    error_msg = err.get("message", "Unknown error")

                    # Non-retryable errors
                    non_retryable = {
                        "GAME_NOT_FOUND", "AGENT_NOT_FOUND", "GAME_ALREADY_STARTED",
                        "WAITING_GAME_EXISTS", "MAX_AGENTS_REACHED",
                        "ACCOUNT_ALREADY_IN_GAME", "ONE_AGENT_PER_API_KEY",
                        "TOO_MANY_AGENTS_PER_IP", "INVALID_ACTION", "INVALID_TARGET",
                        "INVALID_ITEM", "INSUFFICIENT_EP", "AGENT_DEAD",
                        "GEO_RESTRICTED", "INVALID_WALLET_ADDRESS",
                        "INSUFFICIENT_BALANCE", "PAID_GAME_ACCOUNT_REQUIRED",
                    }
                    if error_code in non_retryable:
                        raise APIError(error_msg, error_code, resp.status_code)

                    # Retryable API errors
                    last_error = APIError(error_msg, error_code, resp.status_code)
                    if error_code == "COOLDOWN_ACTIVE":
                        logger.warning(f"Cooldown active, waiting {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    if attempt < retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    raise last_error

                return data

            except requests.exceptions.ConnectionError as e:
                self._consecutive_failures += 1
                last_error = e
                wait = self._get_backoff_wait(attempt, retry_delay)
                if attempt < retries - 1:
                    logger.warning(
                        f"Connection error (attempt {attempt + 1}/{retries}): "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Connection failed after {retries} attempts")
                    raise APIError(str(e), "CONNECTION_ERROR")

            except requests.exceptions.ReadTimeout as e:
                self._consecutive_failures += 1
                last_error = e
                wait = self._get_backoff_wait(attempt, retry_delay)
                if attempt < retries - 1:
                    logger.warning(
                        f"Read timeout (attempt {attempt + 1}/{retries}): "
                        f"Server slow. Retrying in {wait:.1f}s..."
                    )
                    # Increase timeout for next attempt
                    if isinstance(timeout, tuple):
                        timeout = (timeout[0], min(60, timeout[1] + 15))
                    time.sleep(wait)
                else:
                    logger.error(f"Read timeout after {retries} attempts. Server may be down.")
                    raise APIError(str(e), "READ_TIMEOUT")

            except requests.exceptions.ConnectTimeout as e:
                self._consecutive_failures += 1
                last_error = e
                wait = self._get_backoff_wait(attempt, retry_delay)
                if attempt < retries - 1:
                    logger.warning(
                        f"Connect timeout (attempt {attempt + 1}/{retries}): "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Connect timeout after {retries} attempts")
                    raise APIError(str(e), "CONNECT_TIMEOUT")

            except ValueError as e:
                self._consecutive_failures += 1
                last_error = e
                wait = self._get_backoff_wait(attempt, retry_delay)
                if attempt < retries - 1:
                    logger.warning(
                        f"JSON Parse error (attempt {attempt + 1}/{retries}). "
                        f"Server may be down. Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Failed to parse JSON after {retries} attempts: {e}")
                    raise APIError(str(e), "NETWORK_ERROR")

            except requests.exceptions.RequestException as e:
                self._consecutive_failures += 1
                last_error = e
                wait = self._get_backoff_wait(attempt, retry_delay)
                if attempt < retries - 1:
                    logger.warning(
                        f"Network error (attempt {attempt + 1}/{retries}): {type(e).__name__}. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Network error after {retries} attempts: {e}")
                    raise APIError(str(e), "NETWORK_ERROR")

        raise APIError(str(last_error), "MAX_RETRIES")

    def _get_backoff_wait(self, attempt: int, base_delay: float) -> float:
        """
        Calculate exponential backoff wait time.
        Also adds extra delay if we've had many consecutive failures.
        """
        wait = base_delay * (2 ** attempt)  # Exponential: 2s, 4s, 8s, 16s...
        # Extra backoff if server seems unstable
        if self._consecutive_failures > 5:
            wait += 10  # Add 10s if consistently failing
        return min(wait, 30)  # Cap at 30 seconds

    # ─── Account Endpoints ─────────────────────────────────────────
    def get_account_info(self) -> dict:
        """GET /accounts/me — Fetch account info."""
        resp = self._request("GET", "/accounts/me", timeout=self.TIMEOUT_NORMAL)
        return resp.get("data", {})

    def create_account(self, name: str, wallet_address: str = "") -> dict:
        """POST /accounts — Create new account."""
        body = {"name": name}
        if wallet_address:
            body["wallet_address"] = wallet_address
        resp = self._request("POST", "/accounts", body)
        return resp.get("data", {})

    def update_wallet(self, wallet_address: str) -> dict:
        """PUT /accounts/wallet — Update wallet address."""
        resp = self._request("PUT", "/accounts/wallet", {"wallet_address": wallet_address})
        return resp.get("data", {})

    def get_account_history(self, limit: int = 50) -> list:
        """GET /accounts/history — Get transaction history."""
        resp = self._request("GET", f"/accounts/history?limit={limit}")
        return resp.get("data", [])

    # ─── Game Endpoints ────────────────────────────────────────────
    def list_games(self, status: str = "waiting") -> list:
        """GET /games?status=... — List games by status."""
        resp = self._request("GET", f"/games?status={status}",
                             timeout=self.TIMEOUT_POLL, retries=4, retry_delay=3.0)
        return resp.get("data", [])

    def get_game_info(self, game_id: str) -> dict:
        """GET /games/{gameId} — Get game details."""
        resp = self._request("GET", f"/games/{game_id}", timeout=self.TIMEOUT_POLL)
        return resp.get("data", {})

    def create_game(self, host_name: str = "MoltyBot Room",
                    entry_type: str = "free") -> dict:
        """POST /games — Create a new game room."""
        body = {"hostName": host_name, "entryType": entry_type}
        resp = self._request("POST", "/games", body)
        return resp.get("data", {})

    # ─── Agent Endpoints ───────────────────────────────────────────
    def register_agent(self, game_id: str, name: str) -> dict:
        """POST /games/{gameId}/agents/register — Register agent."""
        resp = self._request("POST", f"/games/{game_id}/agents/register", {"name": name})
        return resp.get("data", {})

    def get_agent_state(self, game_id: str, agent_id: str) -> dict:
        """GET /games/{gameId}/agents/{agentId}/state — Get current state."""
        resp = self._request("GET", f"/games/{game_id}/agents/{agent_id}/state",
                             timeout=self.TIMEOUT_NORMAL, retries=4, retry_delay=3.0)
        return resp.get("data", {})

    def send_action(self, game_id: str, agent_id: str,
                    action: dict, thought: dict = None) -> dict:
        """POST /games/{gameId}/agents/{agentId}/action — Execute action."""
        body = {"action": action}
        if thought:
            body["thought"] = thought
        return self._request("POST", f"/games/{game_id}/agents/{agent_id}/action",
                             body, timeout=self.TIMEOUT_ACTION, retries=3, retry_delay=2.0)

    # ─── Paid Game Endpoints ───────────────────────────────────────
    def join_paid(self, game_id: str) -> dict:
        """POST /games/{gameId}/join-paid — Get EIP-712 signature."""
        resp = self._request("POST", f"/games/{game_id}/join-paid")
        return resp.get("data", {})

    # ─── Convenience Methods ───────────────────────────────────────
    def send_free_action(self, game_id: str, agent_id: str, action: dict) -> dict:
        """Send a free (EP 0) action."""
        return self.send_action(game_id, agent_id, action)

    def pickup_item(self, game_id: str, agent_id: str, item_id: str) -> dict:
        return self.send_free_action(game_id, agent_id, {"type": "pickup", "itemId": item_id})

    def equip_weapon(self, game_id: str, agent_id: str, item_id: str) -> dict:
        return self.send_free_action(game_id, agent_id, {"type": "equip", "itemId": item_id})

    def talk(self, game_id: str, agent_id: str, message: str) -> dict:
        return self.send_free_action(game_id, agent_id, {"type": "talk", "message": message[:200]})

    def whisper(self, game_id: str, agent_id: str, target_id: str, message: str) -> dict:
        return self.send_free_action(game_id, agent_id,
                                     {"type": "whisper", "targetId": target_id, "message": message[:200]})

    def send_main_action(self, game_id: str, agent_id: str,
                         action: dict, reasoning: str = "", planned: str = "") -> dict:
        """Send a main (EP-consuming) action with optional thought."""
        thought = None
        if reasoning or planned:
            thought = {
                "reasoning": reasoning[:500],
                "plannedAction": planned[:200],
            }
        return self.send_action(game_id, agent_id, action, thought)
