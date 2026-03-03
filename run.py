"""
Backend execution script
Run this file to start the FastAPI backend server
"""
import uvicorn
from api.main import app
from core.config import settings
import sys
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env
load_dotenv()

if __name__ == "__main__":
    print("=" * 60)
    print("Iniciando Backend AutoTrade")
    print("=" * 60)
    print(f"API Host: {settings.API_HOST}")
    
    # Usar PORT do Railway se disponível, senão usar API_PORT
    port = int(os.getenv("PORT", settings.API_PORT))
    print(f"API Port: {port}")
    print(f"Debug Mode: {settings.DEBUG}")
    
    print("=" * 60)
    
    uvicorn.run(
        app,
        host=settings.API_HOST,
        port=port,
        reload=settings.DEBUG,
        access_log=settings.LOG_LEVEL.upper() == "DEBUG",  # Access log so em DEBUG
        log_level=settings.LOG_LEVEL.lower(),  # Usar LOG_LEVEL do .env
        use_colors=True
    )
    
    print("=" * 60)
    print("Backend AutoTrade parado")
    print("=" * 60)
