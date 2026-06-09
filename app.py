import os
import sys
import shutil
import subprocess

# 1. Get the repository and branch from environment variables (defaults to SunilRoy-dev's repository)
REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com/SunilRoy-dev/stremio-telegram-debrid.git")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

SRC_DIR = "stremio_app_source"

print(f"[*] Bootstrapping Stremio-Telegram addon from {REPO_URL} (branch: {BRANCH})...")

# 2. Clean old source if it exists from a previous run
if os.path.exists(SRC_DIR):
    try:
        shutil.rmtree(SRC_DIR)
    except Exception as e:
        print(f"[!] Warning: failed to remove existing {SRC_DIR} directory: {e}")

# 3. Clone the latest repository code
try:
    subprocess.run(["git", "clone", "--branch", BRANCH, "--depth", "1", REPO_URL, SRC_DIR], check=True)
except Exception as e:
    print(f"[!] Git clone failed: {e}")
    sys.exit(1)

# 4. Install requirements from requirements.txt
req_path = os.path.join(SRC_DIR, "requirements.txt")
if os.path.exists(req_path):
    print("[*] Installing requirements from cloned repository...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], check=True)
    except Exception as e:
        print(f"[!] Failed to install requirements: {e}")
        sys.exit(1)

# 5. Add to python path, change directory, and run the server
sys.path.append(os.path.abspath(SRC_DIR))
os.chdir(SRC_DIR)

print("[*] Launching addon.py...")
port = os.getenv("PORT", "7860")
os.system(f"{sys.executable} -m uvicorn addon:app --host 0.0.0.0 --port {port}")
