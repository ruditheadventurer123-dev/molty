import os
import glob
import subprocess
import time
import sys
import threading

def run_party(party_num, api_keys):
    env = os.environ.copy()
    env["MR_ROOM_TYPE"] = "free"
    env["MR_ROOM_NAME"] = f"Party-{party_num}"
    env["MR_API_KEYS"] = ",".join(api_keys)
    
    print(f"[Party-{party_num}] Starting with {len(api_keys)} bots...")
    
    # Run the multi_runner script
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "src.multi_runner"],
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        process.wait()
    except Exception as e:
        print(f"[Party-{party_num}] Error: {e}")

def main():
    print("=======================================================")
    print("      MOLTY ROYALE - RAILWAY MULTI-PARTY RUNNER        ")
    print("=======================================================")
    
    files = glob.glob('accounts_group_*.txt')
    if not files:
        print("No accounts_group_*.txt files found. Please generate them first.")
        return

    threads = []
    
    for f in files:
        parts = f.split('_')
        if len(parts) >= 3:
            party_num = parts[2].split('.')[0]
            
            with open(f, 'r') as file:
                lines = file.readlines()
            
            api_keys = []
            for line in lines:
                if line.startswith('API Key:'):
                    api_keys.append(line.split('API Key:')[1].strip())
                    
            if api_keys:
                # Start each party in its own thread so they all run concurrently
                t = threading.Thread(target=run_party, args=(party_num, api_keys))
                t.daemon = True # Allow main program to exit, but we'll join anyway
                threads.append(t)
                t.start()
                
                # Small stagger between party startups
                time.sleep(2)
                
    print(f"\nAll {len(threads)} parties have been started in the background.\n")
    
    # Keep the main process alive
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nShutting down all parties...")

if __name__ == "__main__":
    main()
