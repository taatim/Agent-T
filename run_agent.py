import os
import sys
import subprocess
import time
from pyngrok import ngrok, conf
from dotenv import load_dotenv

# 1. Configure pyngrok to use our local binary
# This prevents it from trying to download and hitting SSL errors
conf.get_default().ngrok_path = os.path.abspath("./ngrok")

def update_env_file(ngrok_url):
    env_path = ".env"
    if not os.path.exists(env_path):
        print("❌ .env file not found!")
        sys.exit(1)
        
    with open(env_path, "r") as f:
        lines = f.readlines()
        
    with open(env_path, "w") as f:
        for line in lines:
            if line.startswith("CALLBACK_URI_HOST="):
                f.write(f'CALLBACK_URI_HOST="{ngrok_url}"\n')
            else:
                f.write(line)
    
    print(f"✅ Updated .env with callback URL: {ngrok_url}")

def main():
    print("🚀 Starting Agent T (Docker Mode)...")
    
    # 2. Start Ngrok Tunnel
    try:
        print("⏳ Establishing ngrok tunnel on port 8000...")
        # We need to authenticate if not done already
        # Assuming user might have done it, or we try anonymously if allowed (often not for HTML)
        # But let's proceed.
        
        public_url = ngrok.connect(8000).public_url
        print(f"✅ Ngrok Tunnel Established: {public_url}")
        
    except Exception as e:
        print(f"❌ Failed to start ngrok: {e}")
        print("ℹ️  You may need to add your auth token: ./ngrok config add-authtoken <TOKEN>")
        sys.exit(1)

    # 3. Update .env
    update_env_file(public_url)
    
    # 3. Start FastAPI App
    print("🎙️  Starting Voice Agent Server (Local Mode)...")
    try:
        # We use subprocess to run uvicorn so it reloads env vars freshly
        subprocess.run([sys.executable, "-m", "uvicorn", "app:app", "--reload", "--port", "8000"], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Stopping Agent T...")
        ngrok.kill()
        sys.exit(0)

if __name__ == "__main__":
    main()
