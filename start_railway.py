#!/usr/bin/env python3
"""
Script de startup para Railway
Usa a variável de ambiente PORT corretamente
"""
import os
import sys
import asyncio

# Ensure production environment
os.environ['ENVIRONMENT'] = 'production'

# Run database setup first
print("🚀 Iniciando setup do banco de dados...")
try:
    # Import and run the setup
    from railway_prod_setup import setup_database
    asyncio.run(setup_database())
    print("✅ Setup do banco concluído!")
except Exception as e:
    print(f"⚠️  Setup do banco falhou ou já existe: {e}")
    # Continue anyway - server might still work if tables exist

import uvicorn
from api.main import app
from core.config import settings

def main():    
    print("=" * 60)
    print("Iniciando Backend AutoTrade - Railway")
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
        reload=False,  # Railway não usa reload
        access_log=False,  # Desabilitar access log no Railway
        log_level="error",  # Só mostrar logs de erro no Railway
    )

if __name__ == '__main__':
    main()
