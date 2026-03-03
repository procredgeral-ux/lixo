#!/usr/bin/env python3
"""Simple startup script for Railway"""
import os
import sys
import subprocess
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env
load_dotenv()

# Importar settings após carregar .env
from core.config import settings

# Run database setup first
print("🚀 Running database setup...")
result = subprocess.run([sys.executable, "init_database.py"], cwd="/app")
print(f"Database setup completed with exit code: {result.returncode}")

# Start the application
print("🚀 Starting application...")
port = int(os.getenv("PORT", settings.API_PORT))
host = settings.API_HOST

print(f"Starting uvicorn on {host}:{port} (Log Level: {settings.LOG_LEVEL})")

# Use uvicorn directly with the app
import uvicorn
from api.main import app

uvicorn.run(
    app,
    host=host,
    port=port,
    access_log=settings.LOG_LEVEL.upper() == "DEBUG",
    log_level=settings.LOG_LEVEL.lower()
)
