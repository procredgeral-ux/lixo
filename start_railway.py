#!/usr/bin/env python3
"""
Script de startup para Railway
Usa a variável de ambiente PORT corretamente
"""
import os
import sys
import uvicorn
from api.main import app
from core.config import settings
import sys
import os
from dotenv import load_dotenv

def main():
    # Carregar variáveis de ambiente do .env
    load_dotenv()
    
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
