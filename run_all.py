import os
import sys
from threading import Thread
import time

def run_bot():
    """Run the Telegram bot"""
    print("🤖 Starting Telegram Bot...")
    os.system("python main.py")

def run_web():
    """Run the web server"""
    time.sleep(2)  # Give bot a moment to start
    print("🌐 Starting Web Server on port 5000...")
    os.system("python web_server.py")

if __name__ == "__main__":
    # Start bot in a separate thread
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start web server in main thread
    run_web()
