import json
import random
import string
import time
import os
import requests

# Import fungsi dari account manager
from molty_account_manager import load_db, save_db, create_account, validate_name

WALLET_FILE = "wallet50.txt"
OUTPUT_FILE = "API_KEYS.txt"

def generate_unique_username():
    prefixes = ['Cyber', 'Neon', 'Quantum', 'Pixel', 'Crypto', 'Void', 'Nova', 'Echo', 'Nexus', 'Apex', 'Zenith', 'Chrono', 'Aero', 'Vex', 'Zero']
    suffixes = ['Bot', 'Runner', 'Striker', 'Ghost', 'Phantom', 'Wolf', 'Dragon', 'Ninja', 'Rogue', 'Titan']
    
    # 3-4 random digits
    digits = ''.join(random.choices(string.digits, k=random.randint(3, 4)))
    
    name = f"{random.choice(prefixes)}{random.choice(suffixes)}{digits}"
    return name[:20]

def main():
    print("Mulai proses pembuatan 50 akun bot...")
    
    # Baca wallet list
    with open(WALLET_FILE, 'r') as f:
        wallets = [line.strip() for line in f if line.strip()]
        
    print(f"Ditemukan {len(wallets)} wallet address.")
    
    db = load_db()
    api_keys = []
    
    for i, wallet in enumerate(wallets):
        while True:
            name = generate_unique_username()
            valid, _, fixed = validate_name(name)
            if valid:
                name = fixed
                break
                
        print(f"[{i+1}/{len(wallets)}] Membuat akun: {name} | Wallet: {wallet[:6]}...")
        
        # Panggil API create account
        acc_data = create_account(name, wallet)
        
        if acc_data:
            record = {
                "accountId": acc_data["accountId"],
                "name": acc_data["name"],
                "apiKey": acc_data["apiKey"],
                "verificationCode": acc_data.get("verificationCode", ""),
                "publicId": str(acc_data.get("publicId", "")),
                "walletAddress": acc_data.get("walletAddress") or wallet,
                "walletSynced": True,
                "balance": acc_data.get("balance", 0),
                "crossBalanceWei": acc_data.get("crossBalanceWei", "0"),
                "totalGames": 0,
                "totalWins": 0,
                "currentGames": [],
                "createdAt": acc_data.get("createdAt", ""),
                "lastUpdated": acc_data.get("lastUpdated", ""),
                "notes": "auto_generated"
            }
            db["accounts"].append(record)
            api_keys.append(acc_data["apiKey"])
            
            # Save tiap kali berhasil untuk menghindari lose data
            save_db(db)
        else:
            print(f"  -> GAGAL membuat akun {name}")
            
        # Jeda dikit biar gak kena rate limit
        time.sleep(1.5)
        
    print(f"\nSelesai! Berhasil membuat {len(api_keys)} akun.")
    
    # Simpan API_KEYS.txt dipisahkan oleh koma
    if api_keys:
        with open(OUTPUT_FILE, 'w') as f:
            f.write(",".join(api_keys))
        print(f"API Keys berhasil diekspor ke {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
