#!/usr/bin/env python3
"""Script para cadastrar indicadores padrão via API do Railway"""

import requests
import json

# URL do Railway
API_URL = "https://web-production-640f.up.railway.app"
ENDPOINT = f"{API_URL}/api/v1/indicators/seed-defaults"

# Token de autenticação - você precisa fornecer um token válido
# Obtenha o token fazendo login via app ou API
TOKEN = input("Digite seu token JWT (ou deixe em branco se o endpoint não precisar de auth): ").strip()

headers = {
    "Content-Type": "application/json"
}

if TOKEN:
    headers["Authorization"] = f"Bearer {TOKEN}"

try:
    print("🌱 Enviando requisição para cadastrar indicadores...")
    print(f"URL: {ENDPOINT}")
    
    response = requests.post(ENDPOINT, headers=headers, json={}, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Sucesso! {result.get('message', 'Indicadores cadastrados')}")
    elif response.status_code == 401:
        print("❌ Não autorizado. Token JWT necessário.")
        print("Faça login no app e copie o token, ou use um token de admin.")
    else:
        print(f"❌ Erro {response.status_code}: {response.text}")
        
except requests.exceptions.ConnectionError:
    print("❌ Erro de conexão. Verifique se a URL está correta.")
except Exception as e:
    print(f"❌ Erro: {e}")

print("\nPressione Enter para sair...")
input()
