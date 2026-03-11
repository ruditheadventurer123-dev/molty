#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          MOLTY ROYALE — Account Manager & Wallet Setup       ║
║          Simpan semua akun ke database JSON lokal            ║
╚══════════════════════════════════════════════════════════════╝

Cara Pakai:
  python3 molty_account_manager.py            → Menu interaktif
  python3 molty_account_manager.py --create   → Buat akun baru
  python3 molty_account_manager.py --list     → Lihat semua akun
  python3 molty_account_manager.py --refresh  → Refresh dari server
  python3 molty_account_manager.py --export   → Backup database
  python3 molty_account_manager.py --debug    → Aktifkan debug mode
  python3 molty_account_manager.py --showdb   → Tampilkan raw JSON database
"""

import requests
import json
import os
import re
import sys
import subprocess
import argparse
import time
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# KONFIGURASI
# ─────────────────────────────────────────────
BASE_URL_CDN  = "https://cdn.moltyroyale.com/api"
# api.moltyroyale.com deprecated sejak 2026-03-03 — hanya pakai CDN

# Simpan di folder yang mudah ditemukan (HOME, bukan hidden folder)
DB_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(DB_DIR, "accounts_db.json")
ENV_FILE = os.path.join(DB_DIR, ".owner.env")   # Simpan private key owner di sini

# CROSS Mainnet
CHAIN_ID = 612055
RPC_URL  = "https://mainnet.crosstoken.io:22001"

DEBUG_MODE = False

# ─────────────────────────────────────────────
# WARNA TERMINAL
# ─────────────────────────────────────────────
class C:
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    CYAN    = "\033[96m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    DIM     = "\033[2m"

# ─────────────────────────────────────────────
# SAFE INPUT (handle Ctrl+C gracefully)
# ─────────────────────────────────────────────
def safe_input(prompt: str = "", default: str = "") -> str:
    """Input yang tidak crash saat Ctrl+C — return default value."""
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{C.YELLOW}  [Dibatalkan]{C.RESET}")
        return default


# ─────────────────────────────────────────────
# HELPER: PILIH AKUN DARI LIST
# ─────────────────────────────────────────────
def pick_account(db: dict, prompt_label: str = "Pilih") -> int:
    """
    Tampilkan list akun dan minta user pilih.
    Return index (0-based), atau -1 jika user batalkan.
    Loop terus sampai input valid atau user ketik '0'/'q'/Enter kosong.
    """
    accounts = db["accounts"]
    if not accounts:
        print(f"{C.YELLOW}Database kosong.{C.RESET}")
        return -1

    while True:
        print(f"\n{C.CYAN}Pilih akun:{C.RESET}")
        for i, acc in enumerate(accounts, 1):
            ws = f"{C.GREEN}✓{C.RESET}" if acc.get("walletAddress") else f"{C.RED}✗{C.RESET}"
            print(f"  [{i}] {acc['name']:<22} Wallet: {ws}")
        print(f"  [0] Kembali ke menu")

        raw = safe_input(f"\n{prompt_label} (1-{len(accounts)}, 0=kembali): ").strip()

        if raw in ("", "0", "q", "Q"):
            print(f"{C.YELLOW}  Kembali ke menu.{C.RESET}")
            return -1

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(accounts):
                return idx
            print(f"  {C.RED}Nomor harus antara 1 sampai {len(accounts)}.{C.RESET}")
        except ValueError:
            print(f"  {C.RED}Masukkan angka atau 0 untuk kembali.{C.RESET}")


# ─────────────────────────────────────────────
# DATABASE HELPER
# ─────────────────────────────────────────────
def load_db() -> dict:
    os.makedirs(DB_DIR, exist_ok=True)
    if not os.path.exists(DB_FILE):
        db = {
            "meta": {
                "created_at"    : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "last_updated"  : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "total_accounts": 0,
                "description"   : "Molty Royale Account Database",
                "db_path"       : DB_FILE
            },
            "accounts": []
        }
        save_db(db)
        return db
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(db: dict):
    os.makedirs(DB_DIR, exist_ok=True)
    db["meta"]["last_updated"]   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db["meta"]["total_accounts"] = len(db["accounts"])
    db["meta"]["db_path"]        = DB_FILE
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def migrate_old_db():
    """Migrasi dari lokasi lama (~/.molty-royale/) ke lokasi baru (~/molty-royale/)"""
    old_path = os.path.expanduser("~/.molty-royale/accounts_db.json")
    if os.path.exists(old_path) and not os.path.exists(DB_FILE):
        print(f"{C.YELLOW}[MIGRASI]{C.RESET} Ditemukan database lama di: {old_path}")
        print(f"          Memindahkan ke: {DB_FILE}")
        os.makedirs(DB_DIR, exist_ok=True)
        with open(old_path, "r") as f:
            old_data = json.load(f)
        with open(DB_FILE, "w") as f:
            json.dump(old_data, f, indent=2, ensure_ascii=False)
        print(f"{C.GREEN}[MIGRASI]{C.RESET} Selesai! File lama tetap ada di {old_path}")


def find_account_by_name(db, name):
    for acc in db["accounts"]:
        if acc["name"].lower() == name.lower():
            return acc
    return None


def find_account_by_id(db, account_id: str):
    """Cari akun berdasarkan accountId."""
    for acc in db["accounts"]:
        if acc.get("accountId") == account_id:
            return acc
    return None


def find_account_by_apikey(db, api_key: str):
    """Cari akun berdasarkan API key."""
    for acc in db["accounts"]:
        if acc.get("apiKey") == api_key:
            return acc
    return None


# ─────────────────────────────────────────────
# VALIDASI
# ─────────────────────────────────────────────
def validate_name(name: str) -> tuple:
    if not name:
        return True, "", name
    original   = name
    name       = name.replace(" ", "_")
    name_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    errors     = []
    if len(name_clean) < 3:
        errors.append(f"Terlalu pendek (min 3 karakter)")
    if len(name_clean) > 20:
        name_clean = name_clean[:20]
        errors.append(f"Dipotong jadi: '{name_clean}'")
    if name_clean and name_clean[0].isdigit():
        name_clean = "a" + name_clean[1:]
        errors.append(f"Tidak boleh diawali angka → '{name_clean}'")
    if name_clean != original:
        errors.append(f"'{original}' → '{name_clean}'")
    return (False, " | ".join(errors), name_clean) if errors else (True, "", name_clean)


def validate_wallet(wallet: str) -> tuple:
    if not wallet:
        return False, "Wallet tidak boleh kosong"
    if not wallet.startswith("0x"):
        return False, "Harus diawali '0x'"
    if len(wallet) != 42:
        return False, f"Harus 42 karakter (sekarang: {len(wallet)})"
    try:
        int(wallet[2:], 16)
    except ValueError:
        return False, "Mengandung karakter bukan hex"
    return True, ""


# ─────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────
def _do_request(method: str, endpoint: str, payload: dict = None, api_key: str = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    urls = [(BASE_URL_CDN + endpoint, "cdn")]
    last_err = ""

    for url, label in urls:
        try:
            if DEBUG_MODE:
                print(f"{C.DIM}[DEBUG] {method.upper()} {url}{C.RESET}")
                if payload:
                    print(f"{C.DIM}[DEBUG] Payload: {json.dumps(payload)}{C.RESET}")

            if method == "post":
                res = requests.post(url, headers=headers, json=payload or {}, timeout=15)
            elif method == "put":
                res = requests.put(url, headers=headers, json=payload or {}, timeout=15)
            else:
                res = requests.get(url, headers=headers, timeout=10)

            if DEBUG_MODE:
                print(f"{C.DIM}[DEBUG] Status: {res.status_code}{C.RESET}")
                print(f"{C.DIM}[DEBUG] Response: {res.text[:600]}{C.RESET}")

            try:
                body = res.json()
            except Exception:
                return {"success": False, "error": {"message": f"Response bukan JSON: {res.text[:100]}", "code": "PARSE_ERROR"}, "_status": res.status_code}

            return {"_status": res.status_code, **body}

        except requests.exceptions.ConnectionError as e:
            last_err = str(e)
            continue
        except requests.exceptions.Timeout:
            last_err = f"Timeout ({label})"
            continue

    return {"success": False, "error": {"message": f"Tidak bisa terhubung. {last_err}", "code": "CONNECTION_ERROR"}, "_status": 0}


# ─────────────────────────────────────────────
# API FUNCTIONS
# ─────────────────────────────────────────────
def create_account(name: str, wallet_address: str = "") -> dict | None:
    print(f"\n{C.CYAN}[API]{C.RESET} Mengirim request buat akun...")
    payload = {}
    if name:
        payload["name"] = name
    if wallet_address:
        payload["wallet_address"] = wallet_address

    data = _do_request("post", "/accounts", payload)

    if not data.get("success"):
        err  = data.get("error", {})
        code = err.get("code", "?")
        msg  = err.get("message", "Unknown error")
        print(f"{C.RED}[ERROR]{C.RESET} {msg}")
        print(f"{C.RED}        Kode: {code} | HTTP: {data.get('_status', '?')}{C.RESET}")
        details = err.get("details", [])
        if details:
            print(f"{C.YELLOW}        Detail:{C.RESET}")
            for d in details:
                print(f"          • field={d.get('field','?')} | {d.get('message','?')} ({d.get('code','?')})")
        return None

    return data.get("data")


def update_wallet_separate(api_key: str, wallet_address: str) -> bool:
    data = _do_request("put", "/accounts/wallet", {"wallet_address": wallet_address}, api_key)
    if data.get("_status") == 401:
        print(f"{C.RED}[ERROR]{C.RESET} API key tidak valid.")
        return False
    if not data.get("success"):
        err = data.get("error", {})
        print(f"{C.RED}[ERROR]{C.RESET} {err.get('message', 'Unknown')} ({err.get('code', '?')})")
        return False
    return True


def get_account_info(api_key: str) -> tuple:
    """
    Fetch account info dari server.
    Return: (data_dict | None, error_msg | None)
    """
    data = _do_request("get", "/accounts/me", api_key=api_key)
    if data.get("success"):
        return data.get("data"), None
    else:
        err = data.get("error", {})
        msg = f"{err.get('message','Unknown')} (code: {err.get('code','?')}, HTTP: {data.get('_status','?')})"
        return None, msg


def create_sc_wallet(api_key: str, owner_eoa: str) -> tuple:
    """
    POST /create/wallet — buat MoltyRoyaleWallet SC untuk paid game.
    Return: (data_dict | None, error_msg | None)
    """
    data = _do_request("post", "/create/wallet", {"ownerEoa": owner_eoa}, api_key=api_key)
    if data.get("success"):
        return data.get("data"), None
    err = data.get("error", {})
    return None, f"{err.get('message','?')} ({err.get('code','?')})"


def request_whitelist(api_key: str, owner_eoa: str) -> tuple:
    """
    POST /whitelist/request — request agent EOA masuk whitelist SC wallet.
    Return: (data_dict | None, error_msg | None, status_code)
    """
    data = _do_request("post", "/whitelist/request", {"ownerEoa": owner_eoa}, api_key=api_key)
    status = data.get("_status", 0)
    if data.get("success") or status == 201:
        return data.get("data", {}), None, status
    err = data.get("error", {})
    return None, f"{err.get('message','?')} ({err.get('code','?')})", status


def get_whitelist_status_onchain(sc_wallet_addr: str, agent_wallet: str,
                                  tx_hash: str = "") -> tuple:
    """
    Cek status whitelist agent di MoltyRoyaleWallet contract.

    Strategi (berurutan):
    1. Raw eth_call dengan selector keccak256 yang sudah dihitung — lebih andal dari ABI decode
    2. Cek TX receipt: jika approveAddWhitelists sukses → APPROVED
    Return: (status_str | None, error_msg | None)
    """
    if not _check_web3():
        return None, "web3 tidak terinstall"

    from web3 import Web3

    w3 = _get_w3()
    if w3 is None:
        return None, "Tidak bisa konek ke RPC"

    checksum_sc    = Web3.to_checksum_address(sc_wallet_addr)
    checksum_agent = Web3.to_checksum_address(agent_wallet)

    # Selectors dihitung dari keccak256 (verified dari TX analysis):
    # approveAddWhitelists(address[],uint256[]) = 0xb054a5f4 ✓
    VIEW_SELECTORS = {
        "0x3af32abf": "isWhitelisted(address)",
        "0xd936547e": "whitelisted(address)",
        "0x9b19251a": "whitelist(address)",
        "0x673448dd": "isApproved(address)",
        "0xd8b964e6": "approved(address)",
        "0x1ffbb064": "isAgent(address)",
        "0xfd66091e": "agents(address)",
        "0xadf96a03": "agentApproved(address)",
        "0x812e9a95": "isAgentWhitelisted(address)",
        "0x6376d277": "agentWhitelisted(address)",
        "0xdc10a652": "getAgentStatus(address)",
        "0x28f3fac9": "agentStatus(address)",
        "0x1950c218": "checkWhitelist(address)",
        "0x8a46b589": "agentWhitelistStatus(address)",
        "0x09fd8212": "isInWhitelist(address)",
    }

    # ABI-encode address parameter: pad 32 bytes kiri
    addr_padded = bytes.fromhex("000000000000000000000000" + checksum_agent[2:].lower())

    for selector_hex, fn_sig in VIEW_SELECTORS.items():
        try:
            call_data = bytes.fromhex(selector_hex[2:]) + addr_padded
            result_hex = w3.eth.call({
                "to"   : checksum_sc,
                "data" : "0x" + call_data.hex(),
            })
            if result_hex and len(result_hex) >= 32:
                # Decode bool: 32-byte padded, last byte = 0x01 or 0x00
                val = int(result_hex.hex(), 16)
                if DEBUG_MODE:
                    print(f"\n  ✓ Selector {selector_hex} ({fn_sig}) = {bool(val)}")
                return ("approved" if val else "pending"), None
        except Exception as e:
            if DEBUG_MODE:
                print(f"  ✗ {selector_hex} ({fn_sig}): {e}")
            continue

    # ── Strategi 2: Cek TX receipt ──
    # Jika TX approveAddWhitelists sudah SUCCESS → whitelist IS approved
    if tx_hash:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                if receipt["status"] == 1:
                    # TX approve berhasil = sudah approved on-chain
                    return "approved", None
                else:
                    return "tx_failed", None
        except Exception as e:
            if DEBUG_MODE:
                print(f"  TX receipt error: {e}")

    return None, (
        f"Tidak bisa cek status — ABI MoltyRoyaleWallet tidak publik.\n"
        f"  Cek manual TX: https://explorer.crosstoken.io/612055/tx/{tx_hash}\n"
        f"  Atau contract : https://explorer.crosstoken.io/612055/address/{sc_wallet_addr}"
    )


# ═══════════════════════════════════════════════════
#  PRIVATE KEY MANAGEMENT (.owner.env) — multi-key per owner EOA
# ═══════════════════════════════════════════════════
#
#  Format file .owner.env:
#    OWNER_KEY_0xABC123...=0xprivkey_satu
#    OWNER_KEY_0xDEF456...=0xprivkey_dua
#    OWNER_KEY_0x789XYZ...=0xprivkey_tiga
#
#  Tiap entry dikunci oleh owner EOA address.
#  Satu owner EOA bisa dipakai untuk banyak akun agent.
# ═══════════════════════════════════════════════════

def _check_web3() -> bool:
    """Cek apakah web3 sudah terinstall. Kalau belum, tawarkan install."""
    try:
        import web3  # noqa
        return True
    except ImportError:
        print(f"\n  {C.YELLOW}⚠ Library 'web3' belum terinstall.{C.RESET}")
        print(f"  Diperlukan untuk transaksi on-chain.")
        print(f"  Install dengan: {C.BOLD}pip install web3{C.RESET}\n")
        if safe_input("  Install sekarang? (y/n): ").strip().lower() == "y":
            print(f"  {C.CYAN}Menginstall web3...{C.RESET}")
            ret = subprocess.run(
                [sys.executable, "-m", "pip", "install", "web3", "--break-system-packages"],
                capture_output=True, text=True
            )
            if ret.returncode == 0:
                print(f"  {C.GREEN}✓ web3 berhasil diinstall. Lanjutkan.{C.RESET}")
                return True
            else:
                print(f"  {C.RED}✗ Gagal install: {ret.stderr[:200]}{C.RESET}")
                return False
        return False


def _env_key_for(owner_eoa: str) -> str:
    """Generate key name untuk .owner.env dari owner EOA."""
    return f"OWNER_KEY_{owner_eoa.lower()}"


def _load_env_file() -> dict:
    """
    Baca .owner.env, return dict {owner_eoa_lower: privkey}.
    """
    data = {}
    if not os.path.exists(ENV_FILE):
        return data
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k.startswith("OWNER_KEY_") and v:
                eoa = k[len("OWNER_KEY_"):].lower()
                data[eoa] = v
    return data


def _save_env_file(data: dict):
    """
    Tulis ulang .owner.env dari dict {owner_eoa_lower: privkey}.
    """
    lines = [
        "# Molty Royale — Owner Private Keys",
        "# JANGAN commit file ini ke git! JANGAN bagikan ke siapapun!",
        "# Format: OWNER_KEY_<ownerEOA>=<privatekey>",
        "# Dibuat otomatis oleh molty_account_manager.py",
        "",
    ]
    for eoa, key in data.items():
        lines.append(f"OWNER_KEY_{eoa}={key}")
    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass


def load_privkey_for_eoa(owner_eoa: str) -> str:
    """
    Cari private key untuk owner_eoa tertentu di .owner.env.
    Kalau tidak ada, minta input manual dan tawarkan simpan.
    Return: private key string atau "" kalau batal.
    """
    eoa_lower = owner_eoa.lower()

    # Coba baca dari file
    env_data = _load_env_file()
    if eoa_lower in env_data:
        key = env_data[eoa_lower]
        print(f"  {C.DIM}🔑 Private key untuk {owner_eoa[:10]}...{owner_eoa[-4:]} dimuat dari {os.path.basename(ENV_FILE)}{C.RESET}")
        return key

    # Tidak ada — minta input manual
    print(f"\n  {C.BOLD}Private Key untuk Owner: {C.CYAN}{owner_eoa[:10]}...{owner_eoa[-4:]}{C.RESET}")
    print(f"  {C.DIM}Belum ada di {os.path.basename(ENV_FILE)}.{C.RESET}")
    print(f"  {C.RED}⚠ JANGAN bagikan private key ke siapapun!{C.RESET}")
    print(f"  {C.DIM}Key tidak akan tampil saat diketik.{C.RESET}\n")

    import getpass
    try:
        key = getpass.getpass(f"  Private key ({owner_eoa[:8]}...): ").strip()
    except Exception:
        key = safe_input(f"  Private key ({owner_eoa[:8]}...): ").strip()

    if not key:
        return ""

    # Normalisasi
    if not key.startswith("0x") and len(key) == 64:
        key = "0x" + key

    # Validasi panjang
    clean = key[2:] if key.startswith("0x") else key
    if len(clean) != 64:
        print(f"  {C.RED}✗ Private key tidak valid (harus 64 hex chars).{C.RESET}")
        return ""

    # Tawarkan simpan
    print(f"\n  {C.BOLD}Simpan ke {os.path.basename(ENV_FILE)}?{C.RESET}")
    print(f"  {C.DIM}Tidak perlu input ulang saat approve akun dengan owner ini.{C.RESET}")
    if safe_input("  Simpan? (y/n): ").strip().lower() == "y":
        env_data[eoa_lower] = key
        _save_env_file(env_data)
        print(f"  {C.GREEN}✓ Tersimpan.{C.RESET}")

    return key


def save_privkey_for_eoa(owner_eoa: str, key: str):
    """Simpan / update private key untuk owner_eoa tertentu."""
    env_data = _load_env_file()
    env_data[owner_eoa.lower()] = key
    _save_env_file(env_data)
    print(f"  {C.GREEN}✓ Private key untuk {owner_eoa[:10]}...{owner_eoa[-4:]} tersimpan.{C.RESET}")


def delete_privkey_for_eoa(owner_eoa: str):
    """Hapus private key untuk owner_eoa tertentu."""
    env_data = _load_env_file()
    eoa_lower = owner_eoa.lower()
    if eoa_lower in env_data:
        del env_data[eoa_lower]
        _save_env_file(env_data)
        print(f"  {C.GREEN}✓ Private key untuk {owner_eoa[:10]}... dihapus.{C.RESET}")
    else:
        print(f"  {C.DIM}Tidak ditemukan.{C.RESET}")


def delete_all_privkeys():
    """Hapus seluruh file .owner.env."""
    if os.path.exists(ENV_FILE):
        os.remove(ENV_FILE)
        print(f"  {C.GREEN}✓ {ENV_FILE} dihapus seluruhnya.{C.RESET}")
    else:
        print(f"  {C.DIM}File tidak ada.{C.RESET}")


# ═══════════════════════════════════════════════════
#  ON-CHAIN: RPC + APPROVE WHITELIST
# ═══════════════════════════════════════════════════

# Minimal ABI — hanya fungsi yang kita butuhkan
_MOLTY_WALLET_ABI = [
    {
        "name": "approveAddWhitelists",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "requestors", "type": "address[]"},
            {"name": "agentIds",   "type": "uint256[]"}
        ],
        "outputs": []
    }
]

# RPC alternatif untuk fallback
RPC_URLS = [
    "https://mainnet.crosstoken.io:22001",
    "https://rpc.crosstoken.io",           # alternatif jika ada
]

def _get_w3():
    """
    Buat Web3 instance ke CROSS Mainnet.
    Coba beberapa RPC URL, return instance pertama yang konek.
    Return: Web3 instance atau None.
    """
    from web3 import Web3
    import requests as req_lib

    for rpc in RPC_URLS:
        try:
            session = req_lib.Session()
            session.headers.update({"Content-Type": "application/json"})
            provider = Web3.HTTPProvider(
                rpc,
                request_kwargs={"timeout": 15, "verify": True}
            )
            w3 = Web3(provider)
            # Test koneksi dengan eth_blockNumber
            _ = w3.eth.block_number
            if DEBUG_MODE:
                print(f"  {C.DIM}RPC connected: {rpc}{C.RESET}")
            return w3
        except Exception as e:
            if DEBUG_MODE:
                print(f"  {C.DIM}RPC {rpc} gagal: {e}{C.RESET}")
            continue
    return None


def onchain_approve_whitelist(
    owner_privkey: str,
    sc_wallet_addr: str,
    requestors: list[str],   # list of agent EOA (walletAddress)
    agent_ids: list[int],    # list of agent publicId (numeric)
) -> tuple[str, str | None]:
    """
    Panggil approveAddWhitelists() di MoltyRoyaleWallet SC.
    Return: (tx_hash | "", error_msg | None)
    """
    if not _check_web3():
        return "", "web3 tidak terinstall"

    from web3 import Web3

    try:
        w3 = _get_w3()
        if w3 is None:
            return "", (
                f"Tidak bisa konek ke RPC. Coba cek koneksi internet atau "
                f"apakah {RPC_URLS[0]} bisa diakses dari jaringan Anda."
            )

        account       = w3.eth.account.from_key(owner_privkey)
        checksum_sc   = Web3.to_checksum_address(sc_wallet_addr)
        checksum_reqs = [Web3.to_checksum_address(r) for r in requestors]

        contract  = w3.eth.contract(address=checksum_sc, abi=_MOLTY_WALLET_ABI)
        nonce     = w3.eth.get_transaction_count(account.address)
        gas_price = w3.eth.gas_price

        tx = contract.functions.approveAddWhitelists(
            checksum_reqs,
            [int(aid) for aid in agent_ids]
        ).build_transaction({
            "from"    : account.address,
            "chainId" : CHAIN_ID,
            "nonce"   : nonce,
            "gas"     : 300_000,
            "gasPrice": gas_price,
        })

        signed  = w3.eth.account.sign_transaction(tx, owner_privkey)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex(), None

    except Exception as e:
        return "", str(e)


# ─────────────────────────────────────────────
# FLOW: BUAT AKUN BARU
# ─────────────────────────────────────────────
def flow_create_account():
    print(f"\n{C.BOLD}{'═'*57}{C.RESET}")
    print(f"{C.BOLD}  BUAT AKUN BARU{C.RESET}")
    print(f"{C.BOLD}{'═'*57}{C.RESET}")

    db = load_db()

    print(f"\n{C.DIM}Aturan nama:{C.RESET} huruf/angka/underscore, 3-20 karakter\n")
    while True:
        raw_name = safe_input(f"{C.YELLOW}Nama akun{C.RESET} (kosongkan = otomatis): ").strip()
        if not raw_name:
            final_name = ""
            break
        is_valid, err_msg, fixed = validate_name(raw_name)
        if not is_valid:
            print(f"  {C.YELLOW}[AUTO-FIX]{C.RESET} {err_msg}")
            if safe_input(f"  Gunakan '{C.BOLD}{fixed}{C.RESET}' ? (y/n): ").strip().lower() == "y":
                final_name = fixed
                break
            continue
        final_name = fixed
        break

    if final_name and find_account_by_name(db, final_name):
        print(f"{C.YELLOW}[INFO]{C.RESET} Nama '{final_name}' sudah ada di DB.")
        if safe_input("Tetap lanjut? (y/n): ").strip().lower() != "y":
            return

    # Wallet sekarang WAJIB dikirim saat create akun (per docs baru)
    print(f"\n{C.BOLD}Wallet Address{C.RESET} {C.DIM}(wajib untuk menerima reward){C.RESET}")
    print(f"{C.DIM}Format: 0x + 40 hex chars = 42 karakter{C.RESET}\n")
    wallet = ""
    while True:
        raw_wallet = safe_input(f"{C.YELLOW}Wallet address{C.RESET} (0x... / kosong = skip): ").strip()
        if not raw_wallet:
            print(f"  {C.YELLOW}⚠ Wallet dilewati. Set nanti via menu Update Wallet.{C.RESET}")
            break
        ok, err = validate_wallet(raw_wallet)
        if ok:
            wallet = raw_wallet
            print(f"  {C.GREEN}✓ Format valid{C.RESET}")
            break
        print(f"  {C.RED}✗ {err}{C.RESET}\n")

    acc_data = create_account(final_name, wallet)
    if not acc_data:
        print(f"\n{C.RED}✗ Gagal membuat akun.{C.RESET}")
        return

    # Wallet sudah dikirim saat create — tidak perlu PUT terpisah
    wallet_synced  = bool(wallet)
    wallet_address = acc_data.get("walletAddress") or wallet

    print(f"\n{C.GREEN}{'═'*57}{C.RESET}")
    print(f"{C.GREEN}✓  AKUN BERHASIL DIBUAT!{C.RESET}")
    print(f"{'═'*57}")
    print(f"  Account ID      : {C.BOLD}{acc_data['accountId']}{C.RESET}")
    print(f"  Nama            : {C.BOLD}{acc_data['name']}{C.RESET}")
    print(f"  API Key         : {C.BOLD}{C.GREEN}{acc_data['apiKey']}{C.RESET}")
    print(f"  Kode Verifikasi : {acc_data.get('verificationCode', '—')}")
    print(f"  Balance         : {acc_data.get('balance', 0)} $Moltz")
    print(f"  Wallet          : {wallet_address if wallet_address else C.YELLOW+'(belum diset)'+C.RESET}")
    print(f"\n{C.RED}⚠  API KEY HANYA MUNCUL SEKALI — disimpan otomatis ke DB!{C.RESET}")
    print(f"{'═'*57}")

    record = {
        "accountId"        : acc_data["accountId"],
        "name"             : acc_data["name"],
        "apiKey"           : acc_data["apiKey"],
        "verificationCode" : acc_data.get("verificationCode", ""),
        "publicId"         : str(acc_data.get("publicId", "")),
        "walletAddress"    : wallet_address,
        "walletSynced"     : wallet_synced,
        "balance"          : acc_data.get("balance", 0),
        "crossBalanceWei"  : acc_data.get("crossBalanceWei", "0"),
        "totalGames"       : 0,
        "totalWins"        : 0,
        "currentGames"     : [],
        "createdAt"        : acc_data.get("createdAt", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
        "lastUpdated"      : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notes"            : ""
    }

    db["accounts"].append(record)
    save_db(db)

    print(f"\n{C.GREEN}✓ Tersimpan ke database!{C.RESET}")
    print(f"\n  {'─'*53}")
    print(f"  {C.BOLD}Lokasi file DB:{C.RESET}")
    print(f"  {C.CYAN}{DB_FILE}{C.RESET}")
    print(f"  {'─'*53}")
    print(f"  Total akun: {C.BOLD}{len(db['accounts'])}{C.RESET}")
    print(f"\n  {C.DIM}Buka file:{C.RESET}  cat \"{DB_FILE}\"")
    print(f"  {C.DIM}Edit file:{C.RESET}  nano \"{DB_FILE}\"")


# ─────────────────────────────────────────────
# FLOW: TAMPILKAN RAW DATABASE JSON
# ─────────────────────────────────────────────
def flow_show_db():
    """Tampilkan isi database JSON langsung di terminal."""
    print(f"\n{C.BOLD}{'═'*70}{C.RESET}")
    print(f"{C.BOLD}  RAW DATABASE JSON{C.RESET}")
    print(f"  Path: {C.CYAN}{DB_FILE}{C.RESET}")
    print(f"{C.BOLD}{'═'*70}{C.RESET}\n")

    if not os.path.exists(DB_FILE):
        print(f"{C.YELLOW}File tidak ditemukan: {DB_FILE}{C.RESET}")
        print(f"Buat akun dulu via menu [1].")
        return

    with open(DB_FILE, "r") as f:
        content = f.read()
        db      = json.loads(content)

    # Pretty print dengan highlight
    print(f"{C.DIM}File size: {os.path.getsize(DB_FILE)} bytes | "
          f"Akun: {len(db.get('accounts', []))}{C.RESET}\n")

    # Tampilkan JSON dengan warna sederhana
    lines = json.dumps(db, indent=2, ensure_ascii=False).splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('"apiKey"'):
            # Sembunyikan sebagian API key di display
            print(f"{C.YELLOW}{line}{C.RESET}")
        elif stripped.startswith('"accountId"') or stripped.startswith('"name"') or stripped.startswith('"walletAddress"'):
            print(f"{C.GREEN}{line}{C.RESET}")
        elif stripped.startswith('"balance"') or stripped.startswith('"totalGames"') or stripped.startswith('"totalWins"'):
            print(f"{C.CYAN}{line}{C.RESET}")
        elif line.strip() in ["{", "}", "[", "]", "},", "],"] or stripped == "":
            print(f"{C.DIM}{line}{C.RESET}")
        else:
            print(line)

    print(f"\n{C.BOLD}{'─'*70}{C.RESET}")
    print(f"  {C.BOLD}Lokasi file:{C.RESET}")
    print(f"  {C.CYAN}{DB_FILE}{C.RESET}")
    print(f"\n  {C.DIM}Perintah terminal untuk mengakses file:{C.RESET}")
    print(f"  cat  \"{DB_FILE}\"")
    print(f"  nano \"{DB_FILE}\"")
    print(f"  cp   \"{DB_FILE}\" ~/Desktop/accounts_backup.json")


# ─────────────────────────────────────────────
# FLOW: LOKASI & INFO FILE DATABASE
# ─────────────────────────────────────────────
def flow_db_info():
    """Tampilkan info lokasi file database dan cara mengaksesnya."""
    print(f"\n{C.BOLD}{'═'*57}{C.RESET}")
    print(f"{C.BOLD}  INFO FILE DATABASE{C.RESET}")
    print(f"{C.BOLD}{'═'*57}{C.RESET}")

    exists = os.path.exists(DB_FILE)
    size   = os.path.getsize(DB_FILE) if exists else 0
    db     = load_db() if exists else {"accounts": []}

    print(f"""
  {C.BOLD}Lokasi file:{C.RESET}
  {C.CYAN}{DB_FILE}{C.RESET}

  {C.BOLD}Status:{C.RESET}
  Ada      : {C.GREEN + "✓ YA" if exists else C.RED + "✗ BELUM ADA"}{C.RESET}
  Ukuran   : {size} bytes
  Total akun: {len(db['accounts'])}

  {C.BOLD}Cara membuka file:{C.RESET}

  {C.YELLOW}# Tampilkan di terminal:{C.RESET}
  cat "{DB_FILE}"

  {C.YELLOW}# Edit dengan nano:{C.RESET}
  nano "{DB_FILE}"

  {C.YELLOW}# Buka dengan text editor GUI (kalau ada):{C.RESET}
  xdg-open "{DB_FILE}"
  gedit "{DB_FILE}"
  code  "{DB_FILE}"

  {C.YELLOW}# Copy ke Desktop:{C.RESET}
  cp "{DB_FILE}" ~/Desktop/accounts_db.json

  {C.YELLOW}# Folder database:{C.RESET}
  ls -la "{DB_DIR}/"
""")

    if exists and safe_input("Tampilkan isi JSON sekarang? (y/n): ").strip().lower() == "y":
        flow_show_db()


# ─────────────────────────────────────────────
# FLOW: UPDATE WALLET
# ─────────────────────────────────────────────
def flow_update_wallet():
    print(f"\n{C.BOLD}{'═'*57}{C.RESET}")
    print(f"{C.BOLD}  UPDATE WALLET{C.RESET}")
    print(f"{C.BOLD}{'═'*57}{C.RESET}")

    db = load_db()
    if not db["accounts"]:
        print(f"{C.YELLOW}Database kosong.{C.RESET}")
        return

    idx = pick_account(db, "Pilih akun")
    if idx == -1:
        return

    account = db["accounts"][idx]
    print(f"\nAkun: {C.BOLD}{account['name']}{C.RESET}")
    if account.get("walletAddress"):
        print(f"Wallet lama: {account['walletAddress']}")

    while True:
        wallet = safe_input("\nWallet baru (0x...42 karakter): ").strip()
        ok, err = validate_wallet(wallet)
        if ok:
            break
        print(f"  {C.RED}✗ {err}{C.RESET}")

    success = update_wallet_separate(account["apiKey"], wallet)
    db["accounts"][idx]["walletAddress"] = wallet
    db["accounts"][idx]["walletSynced"]  = success
    db["accounts"][idx]["lastUpdated"]   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_db(db)

    label = f"{C.GREEN}✓ Server + DB{C.RESET}" if success else f"{C.YELLOW}✓ DB lokal saja{C.RESET}"
    print(f"\nUpdate wallet: {label}")


# ─────────────────────────────────────────────
# FLOW: LIST AKUN
# ─────────────────────────────────────────────
def flow_list_accounts():
    db = load_db()
    print(f"\n{C.BOLD}{'═'*70}{C.RESET}")
    print(f"{C.BOLD}  DATABASE AKUN MOLTY ROYALE{C.RESET}")
    print(f"  File  : {C.CYAN}{DB_FILE}{C.RESET}")
    print(f"  Update: {db['meta']['last_updated']}")
    print(f"{C.BOLD}{'═'*70}{C.RESET}")

    if not db["accounts"]:
        print(f"\n  {C.YELLOW}Kosong — belum ada akun.{C.RESET}\n")
        return

    # Hitung warning summary
    no_wallet    = [a for a in db["accounts"] if not a.get("walletAddress")]
    no_sc_wallet = [a for a in db["accounts"] if not a.get("scWallet")]

    print(f"\n  Total: {C.BOLD}{len(db['accounts'])}{C.RESET} akun", end="")
    if no_wallet:
        print(f"  {C.RED}⚠ {len(no_wallet)} tanpa wallet (tidak dapat reward!){C.RESET}", end="")
    print()

    for i, acc in enumerate(db["accounts"], 1):
        w           = acc.get("walletAddress", "")
        w_synced    = acc.get("walletSynced", False)
        sc_wallet   = acc.get("scWallet", "")
        wl_status   = acc.get("whitelistStatus", "")  # unknown|pending|approved|rejected

        # Wallet display
        if w:
            sync_tag = f"{C.GREEN}server{C.RESET}" if w_synced else f"{C.YELLOW}lokal{C.RESET}"
            w_disp   = f"{C.GREEN}✓ {w[:10]}...{w[-4:]}{C.RESET} [{sync_tag}]"
        else:
            w_disp   = f"{C.RED}✗ BELUM DISET — tidak akan dapat reward!{C.RESET}"

        # SC Wallet display
        if sc_wallet:
            sc_disp = f"{C.CYAN}{sc_wallet[:10]}...{sc_wallet[-4:]}{C.RESET}"
        else:
            sc_disp = f"{C.DIM}— (belum setup, hanya untuk paid game){C.RESET}"

        # Whitelist status display
        wl_colors = {
            "approved" : f"{C.GREEN}✓ approved{C.RESET}",
            "pending"  : f"{C.YELLOW}⏳ pending (tunggu owner approve){C.RESET}",
            "rejected" : f"{C.RED}✗ rejected{C.RESET}",
        }
        wl_disp = wl_colors.get(wl_status, f"{C.DIM}— belum dicek{C.RESET}")

        # Header akun dengan flag warning
        warn = f" {C.RED}[NO WALLET]{C.RESET}" if not w else ""
        print(f"\n  {C.BOLD}[{i}] {acc['name']}{C.RESET}{warn}")
        print(f"       Account ID   : {acc['accountId']}")
        print(f"       Public ID    : {acc.get('publicId','—') or '—'}")
        print(f"       API Key      : {acc['apiKey'][:18]}...{C.DIM}(hidden){C.RESET}")
        print(f"       Verify Code  : {acc.get('verificationCode','—')}")
        # CROSS balance — konversi dari wei (18 desimal)
        cross_wei = acc.get("crossBalanceWei", "0") or "0"
        try:
            cross_val = int(cross_wei) / 1e18
            if cross_val == 0:
                cross_disp = f"{C.DIM}0 CROSS{C.RESET}"
            elif cross_val < 0.0001:
                cross_disp = f"{C.YELLOW}{cross_val:.8f} CROSS{C.RESET}"
            else:
                cross_disp = f"{C.GREEN}{cross_val:.4f} CROSS{C.RESET}"
        except Exception:
            cross_disp = f"{C.DIM}{cross_wei} wei{C.RESET}"

        print(f"       Balance      : {C.GREEN}{acc.get('balance',0)} $Moltz{C.RESET}  │  {cross_disp}")
        print(f"       Wallet       : {w_disp}")
        print(f"       SC Wallet    : {sc_disp}")
        print(f"       Whitelist    : {wl_disp}")
        print(f"       Games/Wins   : {acc.get('totalGames',0)} / {acc.get('totalWins',0)}")
        print(f"       Dibuat       : {acc.get('createdAt','—')[:10]}")
        if i < len(db["accounts"]):
            print(f"       {'─'*60}")

    # Footer warning ringkas
    if no_wallet:
        print(f"\n  {C.RED}{'─'*68}{C.RESET}")
        print(f"  {C.RED}⚠  {len(no_wallet)} akun belum punya wallet → gunakan Menu [5] untuk set wallet.{C.RESET}")
    if no_sc_wallet:
        print(f"  {C.DIM}ℹ  {len(no_sc_wallet)} akun belum setup SC Wallet (hanya perlu untuk paid game) → Menu [12].{C.RESET}")
    print()


# ─────────────────────────────────────────────
# FLOW: REFRESH DARI SERVER
# ─────────────────────────────────────────────
def flow_refresh_all():
    db = load_db()
    if not db["accounts"]:
        print(f"{C.YELLOW}Database kosong.{C.RESET}")
        return

    print(f"\n{C.CYAN}Refresh {len(db['accounts'])} akun dari server...{C.RESET}\n")
    for idx, acc in enumerate(db["accounts"]):
        print(f"  [{idx+1}] {acc['name']}...", end=" ", flush=True)
        info, err_msg = get_account_info(acc["apiKey"])
        if info:
            # Ambil walletAddress dari server jika ada
            server_wallet = (info.get("walletAddress") or "").strip()
            local_wallet  = acc.get("walletAddress", "")
            wallet_final  = server_wallet if server_wallet else local_wallet

            db["accounts"][idx].update({
                "balance"          : info.get("balance", acc.get("balance", 0)),
                "crossBalanceWei"  : info.get("crossBalanceWei", "0"),
                "totalGames"       : info.get("totalGames", 0),
                "totalWins"        : info.get("totalWins", 0),
                "currentGames"     : info.get("currentGames", []),
                "verificationCode" : info.get("verificationCode", acc.get("verificationCode", "")),
                "walletAddress"    : wallet_final,
                "walletSynced"     : bool(server_wallet),
                "publicId"         : str(info.get("publicId", acc.get("publicId", ""))),
                "lastUpdated"      : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            })
            cross_wei = info.get("crossBalanceWei", "0") or "0"
            try:
                cross_val  = int(cross_wei) / 1e18
                cross_disp = f"{cross_val:.4f} CROSS" if cross_val > 0 else "0 CROSS"
            except Exception:
                cross_disp = f"{cross_wei} wei"

            wallet_status = f"{C.GREEN}wallet ✓{C.RESET}" if server_wallet else f"{C.RED}no wallet{C.RESET}"

            cross_color = C.GREEN if cross_val > 0 else C.DIM
            print(f"{C.GREEN}✓{C.RESET} "
                  f"{info.get('balance',0)} $Moltz | "
                  f"{cross_color}{cross_disp}{C.RESET} | "
                  f"G:{info.get('totalGames',0)} W:{info.get('totalWins',0)} | "
                  f"{wallet_status}")
        else:
            print(f"{C.YELLOW}✗ Gagal — {err_msg}{C.RESET}")

    save_db(db)
    print(f"\n{C.GREEN}✓ Selesai. DB diperbarui.{C.RESET}")

    # ── Ringkasan balance ──
    total_moltz = sum(a.get("balance", 0) for a in db["accounts"])
    total_cross = sum(int(a.get("crossBalanceWei","0") or "0") for a in db["accounts"]) / 1e18
    no_wallet   = [a["name"] for a in db["accounts"] if not a.get("walletSynced")]
    moltz_no_cross = [a["name"] for a in db["accounts"]
                      if a.get("balance", 0) > 0 and
                      int(a.get("crossBalanceWei","0") or "0") == 0]

    print(f"\n  {'─'*55}")
    print(f"  {C.BOLD}RINGKASAN BALANCE:{C.RESET}")
    print(f"  Total $Moltz : {C.GREEN}{total_moltz}{C.RESET}")
    print(f"  Total CROSS  : {C.GREEN if total_cross > 0 else C.DIM}{total_cross:.4f}{C.RESET}")

    if no_wallet:
        print(f"\n  {C.RED}⚠ {len(no_wallet)} akun wallet belum di server (tidak dapat reward):{C.RESET}")
        for n in no_wallet:
            print(f"    {C.DIM}• {n}{C.RESET}")

    if moltz_no_cross:
        print(f"\n  {C.YELLOW}⚠ {len(moltz_no_cross)} akun punya $Moltz tapi CROSS = 0:{C.RESET}")
        for n in moltz_no_cross:
            print(f"    {C.DIM}• {n}{C.RESET}")
        print(f"  {C.DIM}  Kemungkinan: wallet belum diset saat game selesai,")
        print(f"  atau Moltz dikumpulkan tapi belum pernah menang.{C.RESET}")


# ─────────────────────────────────────────────
# FLOW: EXPORT / BACKUP
# ─────────────────────────────────────────────
def flow_export():
    db = load_db()
    if not db["accounts"]:
        print(f"{C.YELLOW}Database kosong.{C.RESET}")
        return

    print(f"\nSimpan backup ke mana?")
    print(f"  [1] Desktop           : ~/Desktop/molty_backup.json")
    print(f"  [2] Home folder       : ~/molty_backup.json")
    print(f"  [3] Folder DB         : {DB_DIR}/backup_<timestamp>.json")
    print(f"  [4] Path custom")

    while True:
        raw = safe_input("\nPilih (1-4, 0=kembali): ").strip()
        if raw in ("1", "2", "3", "4", "", "0", "q"):
            break
        print(f"  {C.RED}Masukkan angka 1-4 atau 0 untuk kembali.{C.RESET}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if raw == "1":
        path = os.path.expanduser(f"~/Desktop/molty_backup_{ts}.json")
    elif raw == "2":
        path = os.path.expanduser(f"~/molty_backup_{ts}.json")
    elif raw == "3":
        path = os.path.join(DB_DIR, f"backup_{ts}.json")
    elif raw == "4":
        path = safe_input("Path lengkap: ").strip()
        if not path:
            print("Dibatalkan.")
            return
    elif raw in ("", "0", "q"):
        print(f"{C.YELLOW}  Kembali ke menu.{C.RESET}")
        return
    else:
        print(f"  {C.RED}Pilihan tidak valid. Masukkan 1-4 atau 0 untuk batal.{C.RESET}")
        return

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print(f"\n{C.GREEN}✓ Backup tersimpan!{C.RESET}")
    print(f"  Path  : {C.CYAN}{path}{C.RESET}")
    print(f"  Akun  : {len(db['accounts'])}")
    print(f"  Size  : {os.path.getsize(path)} bytes")


# ─────────────────────────────────────────────
# FLOW: HAPUS AKUN
# ─────────────────────────────────────────────
def flow_delete_account():
    db = load_db()
    if not db["accounts"]:
        print(f"{C.YELLOW}Database kosong.{C.RESET}")
        return

    idx = pick_account(db, "Pilih akun yang dihapus")
    if idx == -1:
        return

    acc = db["accounts"][idx]
    if safe_input(f"\n{C.RED}Ketik 'hapus' untuk konfirmasi: {C.RESET}").strip().lower() == "hapus":
        db["accounts"].pop(idx)
        save_db(db)
        print(f"{C.GREEN}✓ Dihapus dari DB lokal.{C.RESET}")
    else:
        print("Dibatalkan.")


# ─────────────────────────────────────────────
# MENU UTAMA
# ─────────────────────────────────────────────
def print_banner():
    db    = load_db()
    total = len(db["accounts"])
    print(f"\n{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}║      MOLTY ROYALE — Account Manager v1.3             ║{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}╠══════════════════════════════════════════════════════╣{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}║{C.RESET}  DB   : {DB_FILE:<44}{C.BOLD}{C.CYAN}║{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}║{C.RESET}  Akun : {C.BOLD}{str(total):<44}{C.CYAN}║{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}╚══════════════════════════════════════════════════════╝{C.RESET}")



# ─────────────────────────────────────────────
# FLOW: IMPORT AKUN DARI API KEY
# ─────────────────────────────────────────────
def flow_import_account():
    """
    Tambahkan akun ke DB dari API key yang sudah ada.
    Fetch data dari server: nama, accountId, balance, dll.
    """
    print(f"\n{C.BOLD}{'═'*57}{C.RESET}")
    print(f"{C.BOLD}  IMPORT AKUN DARI API KEY{C.RESET}")
    print(f"{C.BOLD}{'═'*57}{C.RESET}")
    print(f"""
{C.DIM}Gunakan fitur ini jika:{C.RESET}
  • Pindah komputer / install ulang
  • DB terhapus tapi masih punya API key
  • Mau sync akun lama ke database baru
  • Punya beberapa API key dan mau dimasukkan semua

{C.DIM}Format API key:{C.RESET} mr_live_xxxxxxxxxxxxxxxxxxxxxxxx
""")

    db = load_db()

    # ── Bisa import satu atau banyak sekaligus ──
    print(f"  {C.BOLD}Mode import:{C.RESET}")
    print(f"  [1] Import satu API key")
    print(f"  [2] Import banyak sekaligus (paste baris per baris)")
    print(f"  [0] Kembali")

    mode = safe_input(f"\n  Pilih (1/2/0): ").strip()

    if mode == "0" or mode == "":
        return
    elif mode == "1":
        api_keys = []
        raw = safe_input(f"\n{C.YELLOW}Masukkan API key{C.RESET} (mr_live_...): ").strip()
        if raw:
            api_keys = [raw]
    elif mode == "2":
        print(f"\n{C.YELLOW}Paste API key satu per baris.{C.RESET}")
        print(f"{C.DIM}Ketik {C.RESET}{C.BOLD}DONE{C.DIM} lalu Enter jika sudah selesai.{C.RESET}\n")
        api_keys = []
        while True:
            line = safe_input(f"  API key [{len(api_keys)+1}]: ").strip()
            if line.upper() == "DONE" or line == "":
                break
            if line:
                api_keys.append(line)
        if not api_keys:
            print(f"{C.YELLOW}Tidak ada API key dimasukkan.{C.RESET}")
            return
    else:
        print(f"{C.RED}Pilihan tidak valid.{C.RESET}")
        return

    # ── Proses tiap API key ──
    print(f"\n{C.CYAN}Memproses {len(api_keys)} API key...{C.RESET}\n")
    print(f"  {'─'*55}")

    results = {"berhasil": 0, "duplikat": 0, "gagal": 0}

    for i, api_key in enumerate(api_keys, 1):
        print(f"\n  [{i}/{len(api_keys)}] {api_key[:20]}...")

        # Validasi format dasar
        if not api_key.startswith("mr_live_"):
            print(f"         {C.RED}✗ Format tidak valid (harus diawali mr_live_){C.RESET}")
            results["gagal"] += 1
            continue

        if len(api_key) < 20:
            print(f"         {C.RED}✗ API key terlalu pendek{C.RESET}")
            results["gagal"] += 1
            continue

        # Fetch dari server — retry sekali jika gagal
        info = None
        err_msg = None
        for attempt in range(1, 3):
            print(f"         Fetching dari server (attempt {attempt}/2)...", end=" ", flush=True)
            info, err_msg = get_account_info(api_key)
            if info:
                print(f"{C.GREEN}✓{C.RESET}")
                break
            else:
                print(f"{C.RED}✗{C.RESET}")
                print(f"         {C.RED}Detail: {err_msg}{C.RESET}")
                if attempt < 2:
                    print(f"         {C.YELLOW}Mencoba ulang...{C.RESET}")

        if not info:
            print(f"\n         {C.RED}✗ Gagal fetch setelah 2 percobaan.{C.RESET}")
            print(f"         {C.YELLOW}Kemungkinan penyebab:{C.RESET}")
            print(f"           • API key salah atau sudah expired")
            print(f"           • Koneksi internet bermasalah")
            print(f"           • Server sedang down")
            results["gagal"] += 1
            continue

        account_id = info.get("id") or info.get("accountId") or info.get("account_id", "")
        if not account_id:
            print(f"         {C.RED}✗ Tidak bisa mendapatkan account ID dari response server{C.RESET}")
            print(f"         {C.DIM}Response fields: {list(info.keys())}{C.RESET}")
            results["gagal"] += 1
            continue
        name       = info.get("name", "unknown")

        # Cek duplikat di DB (by accountId ATAU by API key)
        dup_by_id  = find_account_by_id(db, account_id)
        dup_by_key = find_account_by_apikey(db, api_key)
        dup_by_id  = dup_by_id or dup_by_key

        if dup_by_id:
            print(f"         {C.YELLOW}⚠ Sudah ada di DB: {name} ({account_id[:12]}...){C.RESET}")
            choice = safe_input(f"         Update data akun ini? (y/n): ").strip().lower()
            if choice == "y":
                # Update record yang ada
                for idx2, acc in enumerate(db["accounts"]):
                    if acc["accountId"] == account_id:
                        db["accounts"][idx2].update({
                            "apiKey"      : api_key,
                            "balance"     : info.get("balance", 0),
                            "crossBalanceWei": info.get("crossBalanceWei", "0"),
                            "totalGames"  : info.get("totalGames", 0),
                            "totalWins"   : info.get("totalWins", 0),
                            "currentGames": info.get("currentGames", []),
                            "lastUpdated" : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        })
                        break
                print(f"         {C.GREEN}✓ Data diperbarui.{C.RESET}")
                results["berhasil"] += 1
            else:
                print(f"         {C.YELLOW}Dilewati.{C.RESET}")
                results["duplikat"] += 1
            continue

        # Tampilkan info akun
        print(f"\n         {C.BOLD}Info akun dari server:{C.RESET}")
        print(f"         Nama        : {C.BOLD}{name}{C.RESET}")
        print(f"         Account ID  : {account_id}")
        print(f"         Balance     : {C.GREEN}{info.get('balance', 0)} $Moltz{C.RESET}")
        print(f"         Total Games : {info.get('totalGames', 0)}")
        print(f"         Total Wins  : {info.get('totalWins', 0)}")

        # Wallet
        wallet_from_server = info.get("walletAddress") or info.get("wallet_address", "")
        if wallet_from_server:
            print(f"         Wallet      : {C.GREEN}✓ {wallet_from_server[:10]}...{wallet_from_server[-4:]}{C.RESET}")
        else:
            print(f"         Wallet      : {C.RED}✗ Belum diset di server{C.RESET}")

        # Konfirmasi simpan
        save = safe_input(f"\n         Simpan ke database? (y/n): ").strip().lower()
        if save != "y":
            print(f"         {C.YELLOW}Dilewati.{C.RESET}")
            results["duplikat"] += 1
            continue

        # Tanya wallet jika belum ada
        wallet = wallet_from_server
        wallet_synced = bool(wallet_from_server)

        if not wallet_from_server:
            print(f"\n         {C.YELLOW}Akun ini belum punya wallet.{C.RESET}")
            set_wallet = safe_input("         Set wallet sekarang? (y/n): ").strip().lower()
            if set_wallet == "y":
                while True:
                    w = safe_input("         Wallet (0x...): ").strip()
                    ok, err = validate_wallet(w)
                    if ok:
                        # Coba sync ke server
                        synced = update_wallet_separate(api_key, w)
                        wallet        = w
                        wallet_synced = synced
                        break
                    print(f"         {C.RED}✗ {err}{C.RESET}")

        # Buat record
        record = {
            "accountId"        : account_id,
            "name"             : name,
            "apiKey"           : api_key,
            "verificationCode" : info.get("verificationCode", ""),
            "publicId"         : str(info.get("publicId", "")),
            "walletAddress"    : wallet,
            "walletSynced"     : wallet_synced,
            "balance"          : info.get("balance", 0),
            "crossBalanceWei"  : info.get("crossBalanceWei", "0"),
            "totalGames"       : info.get("totalGames", 0),
            "totalWins"        : info.get("totalWins", 0),
            "currentGames"     : info.get("currentGames", []),
            "createdAt"        : info.get("createdAt", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            "lastUpdated"      : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "notes"            : "imported"
        }

        db["accounts"].append(record)
        print(f"         {C.GREEN}✓ Berhasil ditambahkan ke DB!{C.RESET}")
        results["berhasil"] += 1

    # ── Simpan & Ringkasan ──
    if results["berhasil"] > 0:
        save_db(db)

    print(f"\n  {'─'*55}")
    print(f"  {C.BOLD}HASIL IMPORT:{C.RESET}")
    print(f"  {C.GREEN}✓ Berhasil : {results['berhasil']}{C.RESET}")
    print(f"  {C.YELLOW}⚠ Dilewati : {results['duplikat']}{C.RESET}")
    print(f"  {C.RED}✗ Gagal    : {results['gagal']}{C.RESET}")
    print(f"  Total akun di DB: {C.BOLD}{len(db['accounts'])}{C.RESET}")
    if results["berhasil"] > 0:
        print(f"\n  {C.GREEN}DB tersimpan ke: {DB_FILE}{C.RESET}")


# ─────────────────────────────────────────────
# FLOW: BULK CREATE ACCOUNT
# ─────────────────────────────────────────────
def flow_bulk_create():
    print(f"\n{C.BOLD}{'═'*57}{C.RESET}")
    print(f"{C.BOLD}  BULK CREATE AKUN{C.RESET}")
    print(f"{C.BOLD}{'═'*57}{C.RESET}")
    print(f"  {C.DIM}Buat banyak akun sekaligus. Setiap akun disimpan")
    print(f"  ke DB setelah berhasil dibuat.{C.RESET}\n")

    db = load_db()

    # ── Jumlah akun ──
    while True:
        raw = safe_input(f"  {C.YELLOW}Jumlah akun yang mau dibuat{C.RESET} (1-50): ").strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 50):
            print(f"  {C.RED}✗ Masukkan angka 1–50.{C.RESET}")
            continue
        total = int(raw)
        break

    # ── Mode nama ──
    print(f"\n  {C.BOLD}Mode penamaan:{C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Prefix otomatis  {C.DIM}→ contoh: hero1, hero2, ...{C.RESET}")
    print(f"  {C.YELLOW}[2]{C.RESET} Nama manual      {C.DIM}→ input satu per satu{C.RESET}")
    print(f"  {C.BLUE}[3]{C.RESET} Biarkan server   {C.DIM}→ nama digenerate otomatis{C.RESET}\n")

    while True:
        mode_name = safe_input(f"  Pilih mode nama (1/2/3): ").strip()
        if mode_name in ("1", "2", "3"):
            break
        print(f"  {C.RED}✗ Masukkan 1, 2, atau 3.{C.RESET}")

    names = []
    if mode_name == "1":
        while True:
            prefix = safe_input(f"  {C.YELLOW}Prefix nama{C.RESET} (contoh: hero → hero811, hero812): ").strip()
            if not prefix:
                print(f"  {C.RED}✗ Prefix tidak boleh kosong.{C.RESET}")
                continue
            _, _, prefix = validate_name(prefix)
            if len(prefix) < 2:
                print(f"  {C.RED}✗ Prefix terlalu pendek.{C.RESET}")
                continue
            raw_start = safe_input(f"  {C.YELLOW}Mulai dari angka berapa?{C.RESET} (default: 1): ").strip()
            start_num = int(raw_start) if raw_start.isdigit() else 1
            suffix_len = len(f"{start_num + total - 1}")
            max_prefix = 20 - suffix_len
            if len(prefix) > max_prefix:
                prefix = prefix[:max_prefix]
                print(f"  {C.YELLOW}[AUTO-FIX]{C.RESET} Prefix dipotong jadi: '{prefix}'")
            names = [f"{prefix}{i}" for i in range(start_num, start_num + total)]
            print(f"  {C.DIM}Preview: {', '.join(names[:3])}{'...' if total > 3 else ''}{C.RESET}")
            if safe_input("  Lanjut? (y/n): ").strip().lower() == "y":
                break
    elif mode_name == "2":
        print(f"\n  {C.DIM}Masukkan {total} nama akun satu per satu:{C.RESET}")
        for i in range(1, total + 1):
            while True:
                raw_name = safe_input(f"  Nama akun [{i}/{total}]: ").strip()
                if not raw_name:
                    print(f"  {C.YELLOW}Nama kosong, akan digenerate server.{C.RESET}")
                    names.append("")
                    break
                is_valid, err_msg, fixed = validate_name(raw_name)
                if err_msg:
                    print(f"  {C.YELLOW}[AUTO-FIX]{C.RESET} {err_msg}")
                if find_account_by_name(db, fixed):
                    print(f"  {C.YELLOW}⚠ '{fixed}' sudah ada di DB.{C.RESET}")
                    if safe_input("  Tetap pakai? (y/n): ").strip().lower() != "y":
                        continue
                names.append(fixed)
                break
    else:
        names = [""] * total

    # ── Mode wallet ──
    print(f"\n  {C.BOLD}Mode wallet:{C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Satu wallet untuk semua akun")
    print(f"  {C.YELLOW}[2]{C.RESET} Wallet berbeda tiap akun  {C.DIM}→ input satu per satu{C.RESET}")
    print(f"  {C.BLUE}[3]{C.RESET} Load dari file .txt        {C.DIM}→ satu wallet per baris{C.RESET}\n")

    while True:
        mode_wallet = safe_input(f"  Pilih mode wallet (1/2/3): ").strip()
        if mode_wallet in ("1", "2", "3"):
            break
        print(f"  {C.RED}✗ Masukkan 1, 2, atau 3.{C.RESET}")

    wallets = []
    if mode_wallet == "1":
        while True:
            w = safe_input(f"  {C.YELLOW}Wallet address{C.RESET} (0x...): ").strip()
            ok, err = validate_wallet(w)
            if ok:
                wallets = [w] * total
                print(f"  {C.GREEN}✓ Wallet valid — akan dipakai untuk semua {total} akun.{C.RESET}")
                break
            print(f"  {C.RED}✗ {err}{C.RESET}")

    elif mode_wallet == "2":
        print(f"\n  {C.DIM}Masukkan {total} wallet address:{C.RESET}")
        for i in range(1, total + 1):
            while True:
                w = safe_input(f"  Wallet [{i}/{total}] (0x...): ").strip()
                ok, err = validate_wallet(w)
                if ok:
                    wallets.append(w)
                    break
                print(f"  {C.RED}✗ {err}{C.RESET}")

    else:
        while True:
            path = safe_input(f"  {C.YELLOW}Path file .txt{C.RESET}: ").strip().strip("'\"")
            path = os.path.expanduser(path)
            if not os.path.exists(path):
                print(f"  {C.RED}✗ File tidak ditemukan: {path}{C.RESET}")
                continue
            with open(path, "r") as f:
                raw_lines = [l.strip() for l in f.readlines() if l.strip()]
            valid_wallets = []
            invalid_count = 0
            for line in raw_lines:
                ok, _ = validate_wallet(line)
                if ok:
                    valid_wallets.append(line)
                else:
                    invalid_count += 1
            if invalid_count:
                print(f"  {C.YELLOW}⚠ {invalid_count} baris tidak valid diabaikan.{C.RESET}")
            if len(valid_wallets) == 0:
                print(f"  {C.RED}✗ Tidak ada wallet valid di file.{C.RESET}")
                continue
            if len(valid_wallets) < total:
                print(f"  {C.YELLOW}⚠ File hanya punya {len(valid_wallets)} wallet, tapi mau buat {total} akun.{C.RESET}")
                print(f"  {C.DIM}Wallet akan dipakai berulang (cycling).{C.RESET}")
                wallets = [valid_wallets[i % len(valid_wallets)] for i in range(total)]
            else:
                wallets = valid_wallets[:total]
            print(f"  {C.GREEN}✓ {len(wallets)} wallet siap dipakai.{C.RESET}")
            break

    # ── Delay antar request ──
    print(f"\n  {C.BOLD}Delay antar request:{C.RESET} {C.DIM}(hindari rate limit server){C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Cepat   — 0.5 detik")
    print(f"  {C.YELLOW}[2]{C.RESET} Normal  — 1 detik  {C.DIM}(direkomendasikan){C.RESET}")
    print(f"  {C.BLUE}[3]{C.RESET} Lambat  — 2 detik")
    print(f"  {C.DIM}[4]{C.RESET} Custom\n")

    while True:
        d = safe_input(f"  Pilih delay (1/2/3/4, default=2): ").strip() or "2"
        if   d == "1": delay = 0.5; break
        elif d == "2": delay = 1.0; break
        elif d == "3": delay = 2.0; break
        elif d == "4":
            raw_d = safe_input("  Delay (detik, contoh: 1.5): ").strip()
            try:
                delay = float(raw_d)
                if delay < 0: raise ValueError
                break
            except ValueError:
                print(f"  {C.RED}✗ Masukkan angka positif.{C.RESET}")
        else:
            print(f"  {C.RED}✗ Pilih 1–4.{C.RESET}")

    # ── Konfirmasi ──
    print(f"\n  {'─'*53}")
    print(f"  {C.BOLD}RINGKASAN:{C.RESET}")
    print(f"  Jumlah akun  : {C.BOLD}{total}{C.RESET}")
    print(f"  Mode nama    : {['Prefix otomatis','Manual','Server auto'][int(mode_name)-1]}")
    print(f"  Mode wallet  : {['Satu untuk semua','Per akun','Dari file'][int(mode_wallet)-1]}")
    print(f"  Delay        : {delay} detik/akun  {C.DIM}(est. {total*delay:.0f}s total){C.RESET}")
    print(f"  {'─'*53}\n")

    if safe_input(f"  {C.YELLOW}Mulai buat {total} akun? (y/n):{C.RESET} ").strip().lower() != "y":
        print(f"  {C.YELLOW}Dibatalkan.{C.RESET}")
        return

    # ── Eksekusi ──
    print(f"\n  {C.BOLD}{'═'*57}{C.RESET}")
    results = {"berhasil": 0, "gagal": 0, "records": []}

    for i in range(total):
        name   = names[i]
        wallet = wallets[i]
        label  = name if name else f"(auto_{i+1})"

        print(f"\n  [{i+1}/{total}] {C.BOLD}{label}{C.RESET} | {wallet[:10]}...{wallet[-4:]}", end=" ")

        acc_data = create_account(name, wallet)

        if not acc_data:
            print(f"  {C.RED}✗ GAGAL{C.RESET}")
            results["gagal"] += 1
        else:
            # Verifikasi wallet tersimpan di server via GET /accounts/me
            wallet_synced    = False
            wallet_on_server = ""
            info, _ = get_account_info(acc_data["apiKey"])
            if info:
                wallet_on_server = info.get("walletAddress") or ""
                wallet_synced    = bool(wallet_on_server and
                                        wallet_on_server.lower() == wallet.lower())

            # Kalau wallet belum tersimpan, coba PUT sekali lagi
            if wallet and not wallet_synced:
                if DEBUG_MODE:
                    print(f"\n  {C.DIM}[DEBUG] wallet tidak ada di server, coba PUT...{C.RESET}")
                put_ok = update_wallet_separate(acc_data["apiKey"], wallet)
                if put_ok:
                    info2, _ = get_account_info(acc_data["apiKey"])
                    if info2:
                        wallet_on_server = info2.get("walletAddress") or ""
                        wallet_synced    = bool(wallet_on_server and
                                                wallet_on_server.lower() == wallet.lower())

            record = {
                "accountId"        : acc_data["accountId"],
                "name"             : acc_data["name"],
                "apiKey"           : acc_data["apiKey"],
                "verificationCode" : acc_data.get("verificationCode", ""),
                "publicId"         : str(info.get("publicId", "") if info else acc_data.get("publicId", "")),
                "walletAddress"    : wallet_on_server or wallet,
                "walletSynced"     : wallet_synced,
                "balance"          : acc_data.get("balance", 0),
                "crossBalanceWei"  : acc_data.get("crossBalanceWei", "0"),
                "totalGames"       : 0,
                "totalWins"        : 0,
                "currentGames"     : [],
                "createdAt"        : acc_data.get("createdAt", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
                "lastUpdated"      : datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "notes"            : "bulk_create"
            }
            db["accounts"].append(record)
            save_db(db)
            results["berhasil"] += 1
            results["records"].append(record)

            if wallet_synced:
                wallet_label = f"{C.GREEN}wallet ✓ server{C.RESET}"
            elif wallet:
                wallet_label = f"{C.RED}wallet ✗ belum di server{C.RESET}"
                results.setdefault("wallet_gagal", []).append(acc_data["name"])
            else:
                wallet_label = f"{C.YELLOW}wallet kosong{C.RESET}"
            print(f"\n      {C.GREEN}✓{C.RESET} ID: {acc_data['accountId']} | Key: {acc_data['apiKey'][:18]}... | {wallet_label}")

        if i < total - 1:
            time.sleep(delay)

    # ── Ringkasan akhir ──
    print(f"\n  {'═'*57}")
    print(f"  {C.BOLD}SELESAI — HASIL BULK CREATE:{C.RESET}")
    print(f"  {C.GREEN}✓ Berhasil : {results['berhasil']}{C.RESET}")
    print(f"  {C.RED}✗ Gagal    : {results['gagal']}{C.RESET}")

    wallet_gagal = results.get("wallet_gagal", [])
    if wallet_gagal:
        print(f"\n  {C.RED}⚠ Wallet BELUM tersimpan di server ({len(wallet_gagal)} akun):{C.RESET}")
        for n in wallet_gagal:
            print(f"    {C.DIM}• {n}{C.RESET}")
        print(f"  {C.YELLOW}  → Jalankan Menu [4] atau [5] untuk retry set wallet.{C.RESET}")
        print(f"  {C.RED}  → Akun ini TIDAK akan dapat reward sampai wallet diset!{C.RESET}")
    elif results["berhasil"] > 0:
        print(f"  {C.GREEN}✓ Semua wallet tersimpan di server{C.RESET}")

    print(f"  Total akun di DB: {C.BOLD}{len(db['accounts'])}{C.RESET}")

    if results["records"]:
        print(f"\n  {C.BOLD}Akun baru:{C.RESET}")
        for r in results["records"]:
            synced_tag = f"{C.GREEN}✓{C.RESET}" if r.get("walletSynced") else f"{C.RED}✗{C.RESET}"
            print(f"  {synced_tag} {C.BOLD}{r['name']}{C.RESET} | {r['accountId']} | {r['apiKey'][:22]}...")
        print(f"\n  {C.GREEN}DB tersimpan ke: {DB_FILE}{C.RESET}")


# ─────────────────────────────────────────────
# FLOW: CEK STATUS WALLET SEMUA AKUN
# ─────────────────────────────────────────────
def flow_check_wallets():
    db = load_db()
    if not db["accounts"]:
        print(f"\n  {C.YELLOW}Database kosong.{C.RESET}")
        return

    total = len(db["accounts"])
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  CEK STATUS WALLET — {total} AKUN{C.RESET}")
    print(f"{C.BOLD}{'═'*65}{C.RESET}")
    print(f"  {C.DIM}Mengecek ke server satu per satu...{C.RESET}\n")

    sudah   = []
    belum   = []
    gagal   = []

    for idx, acc in enumerate(db["accounts"]):
        name = acc.get("name", f"akun_{idx+1}")
        print(f"  [{idx+1}/{total}] {C.BOLD}{name}{C.RESET}...", end=" ", flush=True)

        info, err_msg = get_account_info(acc["apiKey"])
        if not info:
            print(f"{C.RED}✗ Gagal ({err_msg[:40]}){C.RESET}")
            gagal.append((idx, acc))
            continue

        server_wallet = (info.get("walletAddress") or "").strip()

        # Sync ke DB
        db["accounts"][idx]["walletAddress"] = server_wallet
        db["accounts"][idx]["walletSynced"]  = bool(server_wallet)
        db["accounts"][idx]["lastUpdated"]   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        if server_wallet:
            print(f"{C.GREEN}✓ {server_wallet[:10]}...{server_wallet[-4:]}{C.RESET}")
            sudah.append((idx, acc, server_wallet))
        else:
            print(f"{C.RED}✗ BELUM DISET{C.RESET}")
            belum.append((idx, acc))

    save_db(db)

    # ── Ringkasan ──
    print(f"\n  {'─'*63}")
    print(f"  {C.BOLD}HASIL:{C.RESET}")
    print(f"  {C.GREEN}✓ Sudah set wallet : {len(sudah)} akun{C.RESET}")
    print(f"  {C.RED}✗ Belum set wallet : {len(belum)} akun{C.RESET}")
    if gagal:
        print(f"  {C.YELLOW}⚠ Gagal cek        : {len(gagal)} akun{C.RESET}")

    # ── Tawarkan set wallet untuk yang belum ──
    if not belum:
        print(f"\n  {C.GREEN}Semua akun sudah punya wallet!{C.RESET}")
        return

    print(f"\n  {'─'*63}")
    print(f"  {C.YELLOW}{len(belum)} akun belum punya wallet — tidak akan dapat reward!{C.RESET}")
    print(f"\n  {C.BOLD}Set wallet sekarang?{C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Set satu wallet untuk semua akun yang belum")
    print(f"  {C.YELLOW}[2]{C.RESET} Set wallet satu per satu")
    print(f"  {C.DIM}[0]{C.RESET} Skip\n")

    while True:
        pilihan = safe_input("  Pilih (1/2/0): ").strip()
        if pilihan in ("0", "1", "2", ""):
            break
        print(f"  {C.RED}Masukkan 0, 1, atau 2.{C.RESET}")

    if pilihan == "0" or pilihan == "":
        return

    if pilihan == "1":
        # Satu wallet untuk semua
        while True:
            w = safe_input(f"\n  {C.YELLOW}Wallet address{C.RESET} untuk semua akun (0x...): ").strip()
            ok, err = validate_wallet(w)
            if ok:
                break
            print(f"  {C.RED}✗ {err}{C.RESET}")

        berhasil = 0
        for idx, acc in belum:
            name = acc.get("name", "?")
            print(f"  Set {C.BOLD}{name}{C.RESET}...", end=" ", flush=True)
            success = update_wallet_separate(acc["apiKey"], w)
            db["accounts"][idx]["walletAddress"] = w
            db["accounts"][idx]["walletSynced"]  = success
            db["accounts"][idx]["lastUpdated"]   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if success:
                print(f"{C.GREEN}✓{C.RESET}")
                berhasil += 1
            else:
                print(f"{C.YELLOW}⚠ Lokal saja{C.RESET}")
        save_db(db)
        print(f"\n  {C.GREEN}✓ Selesai: {berhasil}/{len(belum)} berhasil sync ke server.{C.RESET}")

    elif pilihan == "2":
        # Per akun
        berhasil = 0
        for idx, acc in belum:
            name = acc.get("name", "?")
            print(f"\n  {C.BOLD}[{name}]{C.RESET} (ID: {acc['accountId'][:16]}...)")
            while True:
                w = safe_input(f"  Wallet (0x... / kosong = skip): ").strip()
                if not w:
                    print(f"  {C.DIM}Dilewati.{C.RESET}")
                    break
                ok, err = validate_wallet(w)
                if ok:
                    success = update_wallet_separate(acc["apiKey"], w)
                    db["accounts"][idx]["walletAddress"] = w
                    db["accounts"][idx]["walletSynced"]  = success
                    db["accounts"][idx]["lastUpdated"]   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    label = f"{C.GREEN}✓ Server + DB{C.RESET}" if success else f"{C.YELLOW}✓ DB lokal saja{C.RESET}"
                    print(f"  {label}")
                    if success:
                        berhasil += 1
                    break
                print(f"  {C.RED}✗ {err}{C.RESET}")
        save_db(db)
        print(f"\n  {C.GREEN}✓ Selesai: {berhasil} akun berhasil sync ke server.{C.RESET}")


# ═══════════════════════════════════════════════════
#  FLOW: SETUP SC WALLET & WHITELIST (PAID GAME)
# ═══════════════════════════════════════════════════
def flow_paid_wallet_setup():
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  SETUP PAID GAME — SC WALLET & WHITELIST{C.RESET}")
    print(f"{C.BOLD}{'═'*65}{C.RESET}")
    print(f"""
  {C.DIM}Paid game membutuhkan MoltyRoyaleWallet (smart contract).
  Setup ini hanya perlu dilakukan sekali per akun.

  Alur:{C.RESET}
  {C.GREEN}[Step 1]{C.RESET} Buat SC Wallet      → POST /create/wallet
  {C.GREEN}[Step 2]{C.RESET} Request Whitelist   → POST /whitelist/request
  {C.GREEN}[Step 3]{C.RESET} Owner Approve       → on-chain via private key  {C.DIM}(ATAU manual di web){C.RESET}
  {C.CYAN}[Step 4]{C.RESET} Cek Status          → query on-chain langsung ke SC  {C.DIM}(butuh web3){C.RESET}

  {C.DIM}🔑 Private key owner disimpan di: {ENV_FILE}{C.RESET}
""")

    db = load_db()
    if not db["accounts"]:
        print(f"  {C.YELLOW}Belum ada akun.{C.RESET}")
        return

    print(f"  {C.BOLD}Pilih akun atau proses semua:{C.RESET}")
    print(f"  {C.DIM}[0] Proses SEMUA akun sekaligus{C.RESET}")
    for i, acc in enumerate(db["accounts"], 1):
        sc   = acc.get("scWallet", "")
        wl   = acc.get("whitelistStatus", "")
        pid  = acc.get("publicId", "")
        sc_s = f"{C.CYAN}{sc[:8]}...{C.RESET}" if sc else f"{C.DIM}no SC{C.RESET}"
        wl_s = {
            "approved": f"{C.GREEN}approved{C.RESET}",
            "pending" : f"{C.YELLOW}pending{C.RESET}",
            "rejected": f"{C.RED}rejected{C.RESET}",
        }.get(wl, f"{C.DIM}—{C.RESET}")
        pid_s = f"{C.DIM}pubID:{pid}{C.RESET}" if pid else f"{C.RED}no publicId{C.RESET}"
        print(f"  [{i}] {C.BOLD}{acc['name']}{C.RESET}  SC:{sc_s}  WL:{wl_s}  {pid_s}")

    # Warning kalau ada akun tanpa publicId
    no_pid = [a["name"] for a in db["accounts"] if not a.get("publicId")]
    if no_pid:
        print(f"\n  {C.YELLOW}⚠  {len(no_pid)} akun belum punya publicId: {', '.join(no_pid)}{C.RESET}")
        print(f"  {C.DIM}   publicId diperlukan untuk approve on-chain (Step 3).{C.RESET}")
        print(f"  {C.DIM}   Jalankan Menu [7] Refresh dulu untuk sync publicId dari server.{C.RESET}")

    while True:
        raw = safe_input(f"\n  Pilih (0=semua, 1-{len(db['accounts'])}, k=kelola key, q=batal): ").strip().lower()
        if raw == "q":
            return
        if raw == "k":
            _flow_manage_privkey()
            return
        if raw == "0":
            targets = list(range(len(db["accounts"])))
            break
        if raw.isdigit() and 1 <= int(raw) <= len(db["accounts"]):
            targets = [int(raw) - 1]
            break
        print(f"  {C.RED}Pilihan tidak valid.{C.RESET}")

    print(f"\n  {C.BOLD}Langkah apa yang ingin dilakukan?{C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Step 1 — Buat SC Wallet")
    print(f"  {C.GREEN}[2]{C.RESET} Step 2 — Request Whitelist")
    print(f"  {C.GREEN}[3]{C.RESET} Step 3 — Approve on-chain (via private key owner)")
    print(f"  {C.CYAN}[4]{C.RESET} Step 4 — Cek Status Whitelist")
    print(f"  {C.YELLOW}[5]{C.RESET} Semua (1 → 2 → 3 → 4 otomatis)")

    while True:
        step = safe_input("\n  Pilih langkah (1/2/3/4/5): ").strip()
        if step in ("1", "2", "3", "4", "5"):
            break
        print(f"  {C.RED}Masukkan 1–5.{C.RESET}")

    do_create    = step in ("1", "5")
    do_whitelist = step in ("2", "5")
    do_approve   = step in ("3", "5")
    do_check     = step in ("4", "5")

    # ── owner EOA (untuk create & whitelist) ──
    owner_eoa = ""
    if do_create or do_whitelist:
        # Coba ambil dari DB akun pertama yang sudah ada scOwnerEoa
        for t in targets:
            saved = db["accounts"][t].get("scOwnerEoa", "")
            if saved:
                owner_eoa = saved
                print(f"  {C.DIM}Owner EOA dari DB: {owner_eoa[:10]}...{owner_eoa[-4:]}{C.RESET}")
                break
        if not owner_eoa:
            print(f"\n  {C.BOLD}Owner EOA{C.RESET} {C.DIM}(wallet address owner, bukan agent){C.RESET}")
            while True:
                owner_eoa = safe_input("  Owner wallet (0x...): ").strip()
                ok, err = validate_wallet(owner_eoa)
                if ok:
                    break
                print(f"  {C.RED}✗ {err}{C.RESET}")

    # ── Jika do_approve, privkey diload per-akun di dalam loop (tiap akun bisa beda owner) ──

    print(f"\n  {'─'*63}")

    # Cache privkey per EOA supaya tidak minta ulang untuk akun dengan owner sama
    _privkey_cache: dict = {}

    for idx in targets:
        # Reload akun (mungkin sudah diupdate di iterasi sebelumnya)
        acc  = db["accounts"][idx]
        name = acc.get("name", f"akun_{idx+1}")
        print(f"\n  {C.BOLD}[{name}]{C.RESET}")

        # ── Step 1: Buat SC Wallet ──
        if do_create:
            existing_sc = acc.get("scWallet", "")
            if existing_sc:
                print(f"  {C.DIM}Step 1: SC Wallet sudah ada ({existing_sc[:10]}...) — dilewati.{C.RESET}")
            else:
                print(f"  {C.CYAN}Step 1:{C.RESET} Membuat SC Wallet...", end=" ", flush=True)
                result, err = create_sc_wallet(acc["apiKey"], owner_eoa)
                if result:
                    sc_addr = (result.get("walletAddress") or result.get("contractAddress")
                               or result.get("address") or result.get("scWallet", ""))
                    db["accounts"][idx]["scWallet"]    = sc_addr
                    db["accounts"][idx]["scOwnerEoa"]  = owner_eoa
                    db["accounts"][idx]["lastUpdated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    save_db(db)
                    acc = db["accounts"][idx]
                    print(f"{C.GREEN}✓ {sc_addr[:10]}...{sc_addr[-4:] if len(sc_addr) > 4 else ''}{C.RESET}")
                else:
                    print(f"{C.RED}✗ {err}{C.RESET}")

        # ── Step 2: Request Whitelist ──
        if do_whitelist:
            wl_status = acc.get("whitelistStatus", "")
            if wl_status == "approved":
                print(f"  {C.DIM}Step 2: Whitelist sudah approved — dilewati.{C.RESET}")
            else:
                print(f"  {C.CYAN}Step 2:{C.RESET} Request whitelist...", end=" ", flush=True)
                result, err, status_code = request_whitelist(acc["apiKey"], owner_eoa)
                if status_code == 409:
                    print(f"{C.YELLOW}⚠ Sudah pernah request (pending){C.RESET}")
                    db["accounts"][idx]["whitelistStatus"] = "pending"
                    db["accounts"][idx]["scOwnerEoa"]      = owner_eoa
                elif err is None:
                    print(f"{C.GREEN}✓ Request terkirim{C.RESET}")
                    db["accounts"][idx]["whitelistStatus"] = "pending"
                    db["accounts"][idx]["scOwnerEoa"]      = owner_eoa
                else:
                    print(f"{C.RED}✗ {err}{C.RESET}")
                db["accounts"][idx]["lastUpdated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                save_db(db)
                acc = db["accounts"][idx]

        # ── Step 3: Approve on-chain ──
        if do_approve:
            sc_addr    = acc.get("scWallet", "")
            wallet     = acc.get("walletAddress", "")  # agent EOA
            public_id  = acc.get("publicId", "")
            acct_owner = acc.get("scOwnerEoa", owner_eoa)  # owner EOA akun ini

            # Validasi data yang diperlukan
            missing = []
            if not sc_addr:    missing.append("scWallet (jalankan Step 1 dulu)")
            if not wallet:     missing.append("walletAddress agent (set wallet dulu)")
            if not public_id:  missing.append("publicId (jalankan Refresh dulu dari menu [7])")
            if not acct_owner: missing.append("scOwnerEoa (jalankan Step 1/2 dulu)")

            if missing:
                print(f"  {C.YELLOW}Step 3: Skip — data kurang:{C.RESET}")
                for m in missing:
                    print(f"    {C.DIM}• {m}{C.RESET}")
                continue

            # Load private key — dari cache, file, atau input manual
            if acct_owner.lower() not in _privkey_cache:
                pk = load_privkey_for_eoa(acct_owner)
                if not pk:
                    print(f"  {C.YELLOW}Step 3: Skip {name} — private key tidak tersedia.{C.RESET}")
                    continue
                _privkey_cache[acct_owner.lower()] = pk
            owner_privkey = _privkey_cache[acct_owner.lower()]

            print(f"  {C.CYAN}Step 3:{C.RESET} Approve on-chain...")
            print(f"    {C.DIM}Owner : {acct_owner[:10]}...{acct_owner[-4:]}{C.RESET}")
            print(f"    {C.DIM}SC    : {sc_addr[:10]}...{sc_addr[-4:]}{C.RESET}")
            print(f"    {C.DIM}Agent : {wallet[:10]}...{wallet[-4:]}{C.RESET}")
            print(f"    {C.DIM}PubID : {public_id}{C.RESET}")
            print(f"    {C.DIM}Chain : CROSS Mainnet ({CHAIN_ID}){C.RESET}")
            print(f"  {C.CYAN}  Mengirim transaksi...{C.RESET}", end=" ", flush=True)

            tx_hash, err = onchain_approve_whitelist(
                owner_privkey,
                sc_addr,
                [wallet],
                [int(public_id)]
            )

            if tx_hash:
                db["accounts"][idx]["whitelistStatus"] = "pending_onchain"
                db["accounts"][idx]["onchainTxHash"]   = tx_hash
                db["accounts"][idx]["lastUpdated"]     = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                save_db(db)
                acc = db["accounts"][idx]
                print(f"\n  {C.GREEN}✓ Transaksi terkirim!{C.RESET}")
                print(f"    TX Hash: {C.CYAN}{tx_hash}{C.RESET}")
                print(f"    {C.DIM}Tunggu konfirmasi on-chain, lalu jalankan Step 4 untuk cek status.{C.RESET}")
            else:
                print(f"\n  {C.RED}✗ Gagal: {err}{C.RESET}")
                print(f"\n  {C.YELLOW}  Alternatif — approve manual di web:{C.RESET}")
                print(f"  {C.BOLD}  https://www.moltyroyale.com{C.RESET} → My Agent → Approve")

        # ── Step 4: Cek Status Whitelist (on-chain) ──
        if do_check:
            sc_addr   = acc.get("scWallet", "")
            wallet    = acc.get("walletAddress", "")

            if not sc_addr or not wallet:
                print(f"  {C.YELLOW}Step 4: Skip — scWallet atau walletAddress belum ada.{C.RESET}")
                continue

            print(f"  {C.CYAN}Step 4:{C.RESET} Cek whitelist on-chain...", end=" ", flush=True)

            if not _check_web3():
                print(f"{C.YELLOW}⚠ web3 tidak tersedia — tampilkan status lokal.{C.RESET}")
                local = acc.get("whitelistStatus", "unknown")
                print(f"  Status lokal DB: {C.DIM}{local}{C.RESET}")
                continue

            status, err = get_whitelist_status_onchain(
                sc_addr, wallet,
                tx_hash=acc.get("onchainTxHash", "")
            )
            if status:
                db["accounts"][idx]["whitelistStatus"] = status
                db["accounts"][idx]["lastUpdated"]     = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                save_db(db)
                labels = {
                    "approved"        : f"{C.GREEN}✓ APPROVED — siap main paid game!{C.RESET}",
                    "pending"         : f"{C.YELLOW}⏳ Belum di-approve{C.RESET}",
                    "pending_onchain" : f"{C.YELLOW}⏳ TX on-chain sukses, menunggu konfirmasi{C.RESET}",
                    "tx_failed"       : f"{C.RED}✗ TX on-chain GAGAL — coba approve ulang{C.RESET}",
                }
                print(labels.get(status, f"{C.DIM}{status}{C.RESET}"))
                if acc.get("onchainTxHash"):
                    sc = acc.get("scWallet", "")
                    print(f"    {C.DIM}TX: https://explorer.crosstoken.io/612055/tx/{acc['onchainTxHash']}{C.RESET}")
            else:
                # ABI tidak ketemu — tampilkan status lokal + link explorer
                local = acc.get("whitelistStatus", "unknown")
                local_label = {
                    "approved"        : f"{C.GREEN}✓ approved (lokal){C.RESET}",
                    "pending"         : f"{C.YELLOW}⏳ pending (lokal){C.RESET}",
                    "pending_onchain" : f"{C.YELLOW}⏳ TX terkirim, belum terkonfirmasi (lokal){C.RESET}",
                    "tx_failed"       : f"{C.RED}✗ TX gagal (lokal){C.RESET}",
                    "rejected"        : f"{C.RED}✗ rejected (lokal){C.RESET}",
                }.get(local, f"{C.DIM}{local} (lokal){C.RESET}")
                print(f"{C.YELLOW}⚠ {err}{C.RESET}")
                print(f"  Status lokal DB: {local_label}")
                if acc.get("onchainTxHash"):
                    print(f"  TX: {C.CYAN}https://explorer.crosstoken.io/612055/tx/{acc['onchainTxHash']}{C.RESET}")

    print(f"\n  {C.GREEN}✓ Selesai.{C.RESET}")


def _flow_manage_privkey():
    """Sub-menu kelola private key owner per EOA (.owner.env)."""
    while True:
        print(f"\n{C.BOLD}{'═'*60}{C.RESET}")
        print(f"{C.BOLD}  KELOLA PRIVATE KEY OWNER{C.RESET}")
        print(f"  File : {C.CYAN}{ENV_FILE}{C.RESET}")
        print(f"{C.BOLD}{'═'*60}{C.RESET}\n")

        env_data = _load_env_file()

        # Tampilkan semua key yang tersimpan
        if not env_data:
            print(f"  {C.DIM}Belum ada private key tersimpan.{C.RESET}\n")
        else:
            print(f"  {C.BOLD}Key tersimpan ({len(env_data)}):{C.RESET}")
            eoa_list = list(env_data.keys())
            for i, eoa in enumerate(eoa_list, 1):
                # Tampilkan owner EOA + akun mana yang pakai EOA ini
                db = load_db()
                akun_pakai = [a["name"] for a in db["accounts"]
                              if a.get("scOwnerEoa", "").lower() == eoa]
                akun_str = f"  {C.DIM}→ dipakai: {', '.join(akun_pakai)}{C.RESET}" if akun_pakai else ""
                print(f"  [{i}] {C.CYAN}{eoa[:10]}...{eoa[-4:]}{C.RESET}{akun_str}")
            print()

        print(f"  {C.GREEN}[a]{C.RESET} Tambah / update key untuk owner EOA")
        if env_data:
            print(f"  {C.RED}[d]{C.RESET} Hapus key untuk owner EOA tertentu")
            print(f"  {C.RED}[x]{C.RESET} Hapus SEMUA key (hapus file)")
        print(f"  {C.DIM}[0]{C.RESET} Kembali\n")

        choice = safe_input("  Pilih: ").strip().lower()

        if choice == "0":
            return

        elif choice == "a":
            # Bisa pilih dari EOA yang sudah ada di DB akun
            db = load_db()
            known_eoas = list({
                a.get("scOwnerEoa", "").lower()
                for a in db["accounts"]
                if a.get("scOwnerEoa")
            })
            if known_eoas:
                print(f"\n  {C.BOLD}Owner EOA dari DB akun:{C.RESET}")
                for i, eoa in enumerate(known_eoas, 1):
                    akun = [a["name"] for a in db["accounts"]
                            if a.get("scOwnerEoa", "").lower() == eoa]
                    has_key = eoa in env_data
                    status  = f"{C.GREEN}✓ ada key{C.RESET}" if has_key else f"{C.YELLOW}belum ada key{C.RESET}"
                    print(f"  [{i}] {eoa[:10]}...{eoa[-4:]}  {status}  {C.DIM}({', '.join(akun)}){C.RESET}")
                print(f"  [m] Input manual EOA baru\n")
                sel = safe_input(f"  Pilih (1-{len(known_eoas)} / m): ").strip().lower()
                if sel == "m":
                    owner_eoa = safe_input("  Owner EOA (0x...): ").strip()
                elif sel.isdigit() and 1 <= int(sel) <= len(known_eoas):
                    owner_eoa = known_eoas[int(sel) - 1]
                else:
                    print(f"  {C.RED}Pilihan tidak valid.{C.RESET}")
                    continue
            else:
                owner_eoa = safe_input("  Owner EOA (0x...): ").strip()

            if not owner_eoa:
                continue
            ok, err = validate_wallet(owner_eoa)
            if not ok:
                print(f"  {C.RED}✗ {err}{C.RESET}")
                continue

            import getpass
            try:
                key = getpass.getpass(f"  Private key untuk {owner_eoa[:10]}... (0x...): ").strip()
            except Exception:
                key = safe_input(f"  Private key untuk {owner_eoa[:10]}... (0x...): ").strip()

            if not key:
                print(f"  {C.YELLOW}Kosong — tidak disimpan.{C.RESET}")
                continue
            if not key.startswith("0x") and len(key) == 64:
                key = "0x" + key
            clean = key[2:] if key.startswith("0x") else key
            if len(clean) != 64:
                print(f"  {C.RED}✗ Private key tidak valid.{C.RESET}")
                continue
            save_privkey_for_eoa(owner_eoa, key)

        elif choice == "d" and env_data:
            eoa_list = list(env_data.keys())
            print(f"\n  Hapus key untuk EOA mana?")
            for i, eoa in enumerate(eoa_list, 1):
                print(f"  [{i}] {eoa[:10]}...{eoa[-4:]}")
            sel = safe_input(f"  Pilih (1-{len(eoa_list)}): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(eoa_list):
                target_eoa = eoa_list[int(sel) - 1]
                if safe_input(f"  {C.RED}Yakin hapus key {target_eoa[:10]}...? (y/n):{C.RESET} ").strip().lower() == "y":
                    delete_privkey_for_eoa(target_eoa)
            else:
                print(f"  {C.RED}Pilihan tidak valid.{C.RESET}")

        elif choice == "x" and env_data:
            if safe_input(f"  {C.RED}Yakin hapus SEMUA key di {os.path.basename(ENV_FILE)}? (y/n):{C.RESET} ").strip().lower() == "y":
                delete_all_privkeys()

        else:
            print(f"  {C.RED}Pilihan tidak valid.{C.RESET}")

        safe_input(f"\n  {C.YELLOW}[Tekan Enter lanjut...]{C.RESET}")



def get_join_paid_message(api_key: str, game_id: str) -> tuple:
    """
    GET /games/{gameId}/join-paid/message
    Return: (eip712_data | None, error_msg | None)
    """
    data = _do_request("get", f"/games/{game_id}/join-paid/message", api_key=api_key)
    if data.get("success"):
        return data.get("data"), None
    err = data.get("error", {})
    return None, f"{err.get('message','?')} ({err.get('code','?')})"


def submit_join_paid(api_key: str, game_id: str, deadline: str, signature: str) -> tuple:
    """
    POST /games/{gameId}/join-paid
    Body: {"deadline": "...", "signature": "0x..."}
    Return: (data | None, error_msg | None)
    """
    payload = {"deadline": deadline, "signature": signature}
    data = _do_request("post", f"/games/{game_id}/join-paid", payload, api_key=api_key)
    if data.get("success"):
        return data.get("data"), None
    err = data.get("error", {})
    return None, f"{err.get('message','?')} ({err.get('code','?')})"


def sign_eip712_data(private_key: str, eip712: dict) -> str | None:
    """
    Sign EIP-712 typed data dengan agent private key.
    Butuh eth_account (sudah include di web3).
    Return: hex signature string atau None jika gagal.
    """
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        signed = Account.sign_typed_data(private_key, full_message=eip712)
        return signed.signature.hex()
    except ImportError:
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"\n{C.DIM}[DEBUG] sign_eip712 error: {e}{C.RESET}")
        return None


def flow_join_paid_game():
    """
    Menu [15] — Join Paid Game.
    Flow baru (server relay):
    1. GET /games/{gameId}/join-paid/message → EIP-712 data
    2. Sign dengan agent EOA private key
    3. POST /games/{gameId}/join-paid {deadline, signature} → server handle on-chain
    """
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  JOIN PAID GAME{C.RESET}")
    print(f"{C.BOLD}{'═'*65}{C.RESET}")
    print(f"""
  {C.DIM}Masuk ke paid game dengan server relay (tidak perlu TX sendiri).
  Server yang handle on-chain setelah kamu sign EIP-712.

  Syarat:{C.RESET}
  {C.GREEN}✓{C.RESET} Akun sudah punya {C.BOLD}walletAddress{C.RESET} (agent EOA)
  {C.GREEN}✓{C.RESET} Whitelist sudah {C.BOLD}approved{C.RESET} (via Menu [12])
  {C.GREEN}✓{C.RESET} Punya {C.BOLD}private key agent EOA{C.RESET} untuk sign EIP-712
  {C.GREEN}✓{C.RESET} Ada paid game dengan status {C.BOLD}waiting{C.RESET}
""")

    if not _check_web3():
        print(f"  {C.RED}✗ eth_account tidak tersedia.{C.RESET}")
        print(f"  {C.DIM}Install: pip install web3{C.RESET}")
        return

    db = load_db()
    if not db["accounts"]:
        print(f"  {C.YELLOW}Belum ada akun.{C.RESET}")
        return

    # ── Pilih akun ──
    print(f"  {C.BOLD}Pilih akun:{C.RESET}")
    eligible = []
    for i, acc in enumerate(db["accounts"]):
        wl  = acc.get("whitelistStatus", "")
        ok  = wl == "approved" and acc.get("walletAddress")
        tag = f"{C.GREEN}✓{C.RESET}" if ok else f"{C.YELLOW}⚠{C.RESET}"
        wl_s = f"{C.GREEN}approved{C.RESET}" if wl == "approved" else f"{C.YELLOW}{wl or '—'}{C.RESET}"
        print(f"  [{i+1}] {tag} {C.BOLD}{acc['name']}{C.RESET}  WL:{wl_s}")
        if ok:
            eligible.append(i)

    if not eligible:
        print(f"\n  {C.YELLOW}Tidak ada akun yang sudah approved.{C.RESET}")
        print(f"  {C.DIM}Jalankan Menu [12] dulu untuk setup whitelist.{C.RESET}")
        return

    while True:
        raw = safe_input(f"\n  Pilih akun (1-{len(db['accounts'])}, q=batal): ").strip().lower()
        if raw == "q": return
        if raw.isdigit() and 1 <= int(raw) <= len(db["accounts"]):
            acc_idx = int(raw) - 1
            break
        print(f"  {C.RED}Tidak valid.{C.RESET}")

    acc = db["accounts"][acc_idx]

    if not acc.get("walletAddress"):
        print(f"  {C.RED}✗ Akun ini belum punya walletAddress.{C.RESET}")
        return

    # ── Input Game ID ──
    print(f"\n  {C.BOLD}Game ID{C.RESET} {C.DIM}(dari GET /games?status=waiting atau URL game){C.RESET}")
    game_id = safe_input("  Game ID: ").strip()
    if not game_id:
        print(f"  {C.RED}✗ Game ID tidak boleh kosong.{C.RESET}")
        return

    # ── Step 1: Get EIP-712 message ──
    print(f"\n  {C.CYAN}[1/3]{C.RESET} Mengambil EIP-712 message dari server...", end=" ", flush=True)
    eip712, err = get_join_paid_message(acc["apiKey"], game_id)
    if not eip712:
        print(f"{C.RED}✗{C.RESET}")
        print(f"  {C.RED}Error: {err}{C.RESET}")
        return
    print(f"{C.GREEN}✓{C.RESET}")

    deadline = str(eip712.get("message", {}).get("deadline", ""))
    if DEBUG_MODE:
        print(f"\n{C.DIM}[DEBUG] EIP-712:\n{json.dumps(eip712, indent=2)}{C.RESET}")

    # Tampilkan ringkasan EIP-712 untuk konfirmasi
    msg = eip712.get("message", {})
    print(f"\n  {C.BOLD}Detail join:{C.RESET}")
    print(f"  Game ID   : {game_id}")
    print(f"  Agent     : {acc['name']}  ({acc.get('walletAddress','?')[:10]}...)")
    print(f"  uuid      : {msg.get('uuid','?')}")
    print(f"  agentId   : {msg.get('agentId','?')}")
    print(f"  player    : {msg.get('player','?')}")
    print(f"  deadline  : {deadline}")
    print(f"  Entry fee : 100 Moltz (ERC-20, dihandle server)")

    if safe_input(f"\n  {C.YELLOW}Lanjut sign & submit? (y/n):{C.RESET} ").strip().lower() != "y":
        print(f"  {C.DIM}Dibatalkan.{C.RESET}")
        return

    # ── Step 2: Sign EIP-712 dengan agent private key ──
    print(f"\n  {C.CYAN}[2/3]{C.RESET} Sign EIP-712 dengan agent EOA...")
    print(f"  {C.DIM}⚠ Ini menggunakan private key AGENT (bukan owner).{C.RESET}")

    import getpass
    agent_wallet = acc.get("walletAddress", "").lower()

    # Coba load dari .owner.env dulu (mungkin tersimpan dengan key agent)
    agent_privkey = load_privkey_for_eoa(agent_wallet) if agent_wallet else None
    if not agent_privkey:
        try:
            agent_privkey = getpass.getpass(f"  Private key agent EOA (0x...): ").strip()
        except Exception:
            agent_privkey = safe_input(f"  Private key agent EOA (0x...): ").strip()

    if not agent_privkey:
        print(f"  {C.RED}✗ Private key tidak diisi.{C.RESET}")
        return

    signature = sign_eip712_data(agent_privkey, eip712)
    if not signature:
        print(f"  {C.RED}✗ Gagal sign — pastikan web3/eth_account terinstall dan private key valid.{C.RESET}")
        return
    print(f"  {C.GREEN}✓ Signed.{C.RESET}")

    # ── Step 3: Submit ke server ──
    print(f"\n  {C.CYAN}[3/3]{C.RESET} Submit ke server...", end=" ", flush=True)
    result, err = submit_join_paid(acc["apiKey"], game_id, deadline, "0x" + signature if not signature.startswith("0x") else signature)

    if result:
        tx_hash  = result.get("txHash", "")
        agent_id = result.get("agentId", "")
        print(f"{C.GREEN}✓{C.RESET}")
        print(f"\n  {C.GREEN}{'═'*63}{C.RESET}")
        print(f"  {C.GREEN}✓ BERHASIL JOIN PAID GAME!{C.RESET}")
        print(f"  {'═'*63}")
        print(f"  TX Hash  : {C.CYAN}{tx_hash}{C.RESET}")
        print(f"  Agent ID : {C.BOLD}{agent_id}{C.RESET}")
        print(f"  Game ID  : {game_id}")
        print(f"\n  {C.DIM}Simpan Agent ID untuk aksi in-game.{C.RESET}")
        print(f"  {C.DIM}Jika Agent ID hilang, cek: GET /accounts/me → currentGames[].agentId{C.RESET}")

        # Update DB
        db["accounts"][acc_idx]["lastUpdated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if "currentGames" not in db["accounts"][acc_idx]:
            db["accounts"][acc_idx]["currentGames"] = []
        save_db(db)
    else:
        print(f"{C.RED}✗{C.RESET}")
        code = err or "?"
        if "GEO_RESTRICTED" in code:
            print(f"\n  {C.RED}✗ GEO_RESTRICTED — request diblokir dari region ini.{C.RESET}")
            print(f"  {C.DIM}Endpoint ini punya IP geo-restriction.{C.RESET}")
        else:
            print(f"\n  {C.RED}✗ Error: {code}{C.RESET}")


def flow_batch_approve():
    """
    Menu [14] — Batch Approve: 1 SC, 1 owner, semua agent dalam 1 TX.
    Semua akun harus punya scOwnerEoa yang SAMA (1 SC wallet bersama).
    """
    print(f"\n{C.BOLD}{'═'*65}{C.RESET}")
    print(f"{C.BOLD}  BATCH APPROVE — 1 TX untuk semua agent{C.RESET}")
    print(f"{C.BOLD}{'═'*65}{C.RESET}")
    print(f"""
  {C.DIM}Cocok untuk: 1 owner wallet, 1 SC MoltyRoyaleWallet,
  banyak akun agent — semua di-approve sekaligus dalam 1 transaksi.

  Syarat tiap akun:{C.RESET}
  {C.GREEN}✓{C.RESET} Sudah punya {C.BOLD}walletAddress{C.RESET}   (agent EOA)
  {C.GREEN}✓{C.RESET} Sudah punya {C.BOLD}publicId{C.RESET}         (sync via Menu [7])
  {C.GREEN}✓{C.RESET} Sudah punya {C.BOLD}scOwnerEoa{C.RESET}       (sama semua)
  {C.GREEN}✓{C.RESET} Status whitelist {C.BOLD}pending{C.RESET}     (sudah request, belum approve)
""")

    db = load_db()
    if not db["accounts"]:
        print(f"  {C.YELLOW}Belum ada akun.{C.RESET}")
        return

    # ── Scan akun: cek kelayakan & group by scOwnerEoa ──
    groups: dict[str, list] = {}  # scOwnerEoa → [acc_idx, ...]
    skipped = []

    for i, acc in enumerate(db["accounts"]):
        issues = []
        if not acc.get("walletAddress"):  issues.append("no walletAddress")
        if not acc.get("publicId"):       issues.append("no publicId")
        if not acc.get("scOwnerEoa"):     issues.append("no scOwnerEoa")
        if not acc.get("scWallet"):       issues.append("no scWallet")

        if issues:
            skipped.append((acc["name"], issues))
            continue

        eoa = acc["scOwnerEoa"].lower()
        groups.setdefault(eoa, []).append(i)

    if skipped:
        print(f"  {C.YELLOW}Akun yang tidak memenuhi syarat (dilewati):{C.RESET}")
        for name, issues in skipped:
            print(f"    {C.DIM}• {name}: {', '.join(issues)}{C.RESET}")
        print()

    if not groups:
        print(f"  {C.RED}Tidak ada akun yang memenuhi syarat.{C.RESET}")
        print(f"  {C.DIM}Jalankan Menu [12] Step 1 & 2 dulu untuk setup SC dan request whitelist.{C.RESET}")
        return

    # ── Tampilkan grup yang tersedia ──
    print(f"  {C.BOLD}Grup owner yang tersedia:{C.RESET}\n")
    group_list = list(groups.items())

    for g_idx, (eoa, acc_idxs) in enumerate(group_list, 1):
        accs       = [db["accounts"][i] for i in acc_idxs]
        sc_wallet  = accs[0].get("scWallet", "")
        already_ok = [a for a in accs if a.get("whitelistStatus") == "approved"]
        pending    = [a for a in accs if a.get("whitelistStatus") != "approved"]

        print(f"  {C.BOLD}[{g_idx}] Owner: {eoa[:10]}...{eoa[-4:]}{C.RESET}")
        print(f"       SC Wallet : {sc_wallet[:10]}...{sc_wallet[-4:] if sc_wallet else '?'}")
        print(f"       Total akun: {len(accs)} | "
              f"{C.GREEN}approved: {len(already_ok)}{C.RESET} | "
              f"{C.YELLOW}pending: {len(pending)}{C.RESET}")
        for a in accs:
            wl  = a.get("whitelistStatus", "—")
            wl_c = (f"{C.GREEN}✓{C.RESET}" if wl == "approved"
                    else f"{C.YELLOW}⏳{C.RESET}" if "pending" in wl
                    else f"{C.DIM}—{C.RESET}")
            pid = a.get("publicId", "?")
            print(f"       {wl_c} {a['name']}  {C.DIM}(pubID:{pid}  addr:{a.get('walletAddress','?')[:8]}...){C.RESET}")
        print()

    # ── Pilih grup ──
    while True:
        sel = safe_input(f"  Pilih grup (1-{len(group_list)}, q=batal): ").strip().lower()
        if sel == "q":
            return
        if sel.isdigit() and 1 <= int(sel) <= len(group_list):
            chosen_eoa, chosen_idxs = group_list[int(sel) - 1]
            break
        print(f"  {C.RED}Pilihan tidak valid.{C.RESET}")

    chosen_accs = [db["accounts"][i] for i in chosen_idxs]
    sc_wallet   = chosen_accs[0].get("scWallet", "")

    # ── Pilih akun mana yang di-approve ──
    print(f"\n  {C.BOLD}Approve akun mana?{C.RESET}")
    print(f"  [1] Semua akun dalam grup ({len(chosen_idxs)} akun)")
    pending_only = [i for i in chosen_idxs
                    if db["accounts"][i].get("whitelistStatus") != "approved"]
    print(f"  [2] Hanya yang belum approved ({len(pending_only)} akun)")
    print(f"  [3] Pilih manual")

    while True:
        mode = safe_input("  Pilih (1/2/3): ").strip()
        if mode in ("1", "2", "3"):
            break

    if mode == "1":
        target_idxs = chosen_idxs
    elif mode == "2":
        target_idxs = pending_only
        if not target_idxs:
            print(f"  {C.GREEN}Semua akun sudah approved!{C.RESET}")
            return
    else:
        target_idxs = []
        print(f"\n  {C.BOLD}Pilih akun (pisah koma, contoh: 1,3,5):{C.RESET}")
        for j, i in enumerate(chosen_idxs, 1):
            acc = db["accounts"][i]
            wl  = acc.get("whitelistStatus", "—")
            print(f"  [{j}] {acc['name']}  {C.DIM}status:{wl}{C.RESET}")
        raw = safe_input("  Nomor: ").strip()
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(chosen_idxs):
                target_idxs.append(chosen_idxs[int(part) - 1])
        if not target_idxs:
            print(f"  {C.RED}Tidak ada akun dipilih.{C.RESET}")
            return

    # ── Siapkan data untuk TX ──
    requestors = []
    agent_ids  = []
    for i in target_idxs:
        acc = db["accounts"][i]
        requestors.append(acc["walletAddress"])
        agent_ids.append(int(acc["publicId"]))

    print(f"\n  {C.BOLD}Ringkasan TX yang akan dikirim:{C.RESET}")
    print(f"  SC Wallet  : {C.CYAN}{sc_wallet}{C.RESET}")
    print(f"  Owner EOA  : {C.CYAN}{chosen_eoa}{C.RESET}")
    print(f"  Chain      : CROSS Mainnet ({CHAIN_ID})")
    print(f"  Fungsi     : approveAddWhitelists(address[{len(requestors)}], uint256[{len(agent_ids)}])")
    print(f"  Agent list :")
    for i, (addr, pid) in enumerate(zip(requestors, agent_ids)):
        print(f"    [{i+1}] {addr[:10]}...{addr[-4:]}  publicId:{pid}")

    print()
    confirm = safe_input(f"  {C.YELLOW}Kirim TX? (y/n):{C.RESET} ").strip().lower()
    if confirm != "y":
        print(f"  {C.DIM}Dibatalkan.{C.RESET}")
        return

    # ── Load private key ──
    owner_privkey = load_privkey_for_eoa(chosen_eoa)
    if not owner_privkey:
        print(f"  {C.RED}Private key tidak tersedia — batalkan.{C.RESET}")
        return

    # ── Kirim TX ──
    print(f"\n  {C.CYAN}Mengirim batch TX...{C.RESET}", end=" ", flush=True)
    tx_hash, err = onchain_approve_whitelist(
        owner_privkey,
        sc_wallet,
        requestors,
        agent_ids,
    )

    if tx_hash:
        print(f"\n  {C.GREEN}✓ TX terkirim!{C.RESET}")
        print(f"  TX Hash: {C.CYAN}{tx_hash}{C.RESET}")
        print(f"  {C.DIM}https://explorer.crosstoken.io/612055/tx/{tx_hash}{C.RESET}")

        # Update semua akun yang di-approve
        for i in target_idxs:
            db["accounts"][i]["whitelistStatus"] = "pending_onchain"
            db["accounts"][i]["onchainTxHash"]   = tx_hash
            db["accounts"][i]["lastUpdated"]      = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        save_db(db)
        print(f"\n  {C.GREEN}✓ DB diperbarui. Jalankan Menu [12] Step 4 untuk cek status setelah TX dikonfirmasi.{C.RESET}")
    else:
        print(f"\n  {C.RED}✗ TX gagal: {err}{C.RESET}")
        print(f"  {C.YELLOW}Alternatif: approve manual di https://www.moltyroyale.com → My Agent{C.RESET}")


def main_menu():
    global DEBUG_MODE
    migrate_old_db()  # Auto-migrasi dari lokasi lama jika ada

    while True:
        print_banner()
        print(f"""
  {C.BOLD}MENU:{C.RESET}
  {C.GREEN}[1]{C.RESET} Buat akun baru
  {C.GREEN}[2]{C.RESET} Bulk create akun     {C.DIM}← buat banyak akun sekaligus{C.RESET}
  {C.YELLOW}[3]{C.RESET} Import dari API key  {C.DIM}← tambah akun yang sudah ada{C.RESET}
  {C.BLUE}[4]{C.RESET} Update wallet akun
  {C.CYAN}[5]{C.RESET} Cek status wallet    {C.DIM}← cek & set wallet semua akun{C.RESET}
  {C.CYAN}[6]{C.RESET} Lihat semua akun
  {C.YELLOW}[7]{C.RESET} Refresh data dari server

  {C.BOLD}── PAID GAME ──{C.RESET}
  {C.MAGENTA}[12]{C.RESET} Setup SC Wallet & Whitelist  {C.DIM}← create/wallet + whitelist + approve{C.RESET}
  {C.MAGENTA}[14]{C.RESET} Batch Approve (1 TX semua)   {C.DIM}← 1 owner, 1 SC, approve semua agent sekaligus{C.RESET}
  {C.MAGENTA}[15]{C.RESET} Join Paid Game               {C.DIM}← sign EIP-712, server handle on-chain{C.RESET}
  {C.DIM}[13]{C.RESET} Kelola Private Key Owner     {C.DIM}← simpan/hapus .owner.env{C.RESET}

  {C.MAGENTA}[8]{C.RESET} Export / Backup database
  {C.RED}[9]{C.RESET} Hapus akun dari DB lokal
  {C.GREEN}[10]{C.RESET} Tampilkan isi JSON database
  {C.BLUE}[11]{C.RESET} Info & lokasi file database
  {C.DIM}[d]{C.RESET} Toggle debug ({C.GREEN+'ON' if DEBUG_MODE else 'OFF'}{C.RESET})
  {C.BOLD}[0]{C.RESET} Keluar
""")
        choice = safe_input(f"  {C.BOLD}Pilih:{C.RESET} ").strip().lower()

        if   choice == "1":  flow_create_account()
        elif choice == "2":  flow_bulk_create()
        elif choice == "3":  flow_import_account()
        elif choice == "4":  flow_update_wallet()
        elif choice == "5":  flow_check_wallets()
        elif choice == "6":  flow_list_accounts()
        elif choice == "7":  flow_refresh_all()
        elif choice == "8":  flow_export()
        elif choice == "9":  flow_delete_account()
        elif choice == "10": flow_show_db()
        elif choice == "11": flow_db_info()
        elif choice == "12": flow_paid_wallet_setup()
        elif choice == "13": _flow_manage_privkey()
        elif choice == "14": flow_batch_approve()
        elif choice == "15": flow_join_paid_game()
        elif choice == "d":
            DEBUG_MODE = not DEBUG_MODE
            print(f"\n  Debug: {C.GREEN+'ON' if DEBUG_MODE else C.YELLOW+'OFF'}{C.RESET}")
        elif choice == "0":
            print(f"\n{C.GREEN}Sampai jumpa!{C.RESET}\n")
            sys.exit(0)
        else:
            print(f"\n{C.RED}Pilihan tidak valid.{C.RESET}")

        if choice != "0":
            safe_input(f"\n  {C.YELLOW}[Tekan Enter untuk kembali ke menu...]{C.RESET}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def run():
    """Entry point dengan global error handling."""
    try:
        parser = argparse.ArgumentParser(description="Molty Royale Account Manager")
        parser.add_argument("--create",  action="store_true")
        parser.add_argument("--bulk",    action="store_true")
        parser.add_argument("--list",    action="store_true")
        parser.add_argument("--refresh", action="store_true")
        parser.add_argument("--export",  action="store_true")
        parser.add_argument("--showdb",  action="store_true")
        parser.add_argument("--debug",   action="store_true")
        args = parser.parse_args()

        if args.debug:
            global DEBUG_MODE
            DEBUG_MODE = True

        migrate_old_db()

        if   args.create  : flow_create_account()
        elif args.bulk    : flow_bulk_create()
        elif args.list    : flow_list_accounts()
        elif args.refresh : flow_refresh_all()
        elif args.export  : flow_export()
        elif args.showdb  : flow_show_db()
        else              : main_menu()

    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Keluar... Sampai jumpa!{C.RESET}\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n{C.RED}[ERROR TIDAK TERDUGA]{C.RESET} {e}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run()
