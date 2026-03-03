#!/usr/bin/env python3
"""
Script de startup para Railway
Usa a variável de ambiente PORT corretamente
"""
import os
import sys
import subprocess

def main():
    # Obter PORT das variáveis de ambiente do Railway
    port = os.environ.get('PORT', '8000')
    
    print(f"🚀 Starting server on port {port}")
    
    # Executar uvicorn com o port correto
    cmd = [
        sys.executable, '-m', 'uvicorn',
        'api.main:app',
        '--host', '0.0.0.0',
        '--port', port,
        '--workers', '1'
    ]
    
    subprocess.run(cmd)

if __name__ == '__main__':
    main()
