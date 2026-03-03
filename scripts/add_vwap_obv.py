#!/usr/bin/env python3
"""Cadastrar VWAP e OBV via API do Railway"""

import requests
import time

API_URL = "https://web-production-640f.up.railway.app"

# VWAP e OBV que faltam
indicators = [
    {
        "name": "VWAP",
        "type": "vwap",
        "description": "Volume Weighted Average Price - volume-based price benchmark",
        "parameters": {"period": 14},
        "is_default": True
    },
    {
        "name": "OBV",
        "type": "obv", 
        "description": "On Balance Volume - cumulative volume flow indicator",
        "parameters": {},
        "is_default": True
    }
]

print("🌱 Cadastrando VWAP e OBV no Railway...")
print(f"URL: {API_URL}\n")

for ind in indicators:
    try:
        print(f"➡️  Cadastrando {ind['name']}...", end=" ")
        
        response = requests.post(
            f"{API_URL}/api/v1/indicators/",
            json=ind,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 201:
            print(f"✅ Criado!")
        elif response.status_code == 400:
            # Pode ser que já existe ou erro de validação
            print(f"⚠️  {response.json().get('detail', 'Erro 400')}")
        elif response.status_code in (401, 403):
            print(f"🔒 Precisa de autenticação (crie o indicador manualmente)")
        else:
            print(f"❌ Erro {response.status_code}")
            
        time.sleep(0.5)  # Pequeno delay entre requisições
            
    except requests.exceptions.Timeout:
        print(f"⏱️  Timeout")
    except Exception as e:
        print(f"❌ Erro: {e}")

print("\n" + "="*50)
print("✅ Processo concluído!")
print("Verifique no app se VWAP e OBV aparecem na lista")
print("="*50)
input("\nPressione Enter para sair...")
