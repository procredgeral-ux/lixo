#!/usr/bin/env python3
"""Simple startup script for Railway"""
import os
import sys
import subprocess

# Run database setup first
print("🚀 Running database setup...")
result = subprocess.run([sys.executable, "init_database.py"], cwd="/app")
print(f"Database setup completed with exit code: {result.returncode}")

# Start the application
print("🚀 Starting application...")
port = int(os.getenv("PORT", 8000))
host = "0.0.0.0"

print(f"Starting uvicorn on {host}:{port}")

# Use uvicorn directly with the app
import uvicorn
from api.main import app

uvicorn.run(
    app,
    host=host,
    port=port,
    access_log=True,
    log_level="info"
)
