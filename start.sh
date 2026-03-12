#!/bin/bash
# Script de inicialização combinado para Railway
# Executa: 1) init_database.py, 2) start_railway.py

echo "🚀 Iniciando setup do banco de dados..."
python railway_prod_setup.py

if [ $? -eq 0 ]; then
    echo "✅ Banco configurado, iniciando servidor..."
    exec python start_railway.py
else
    echo "⚠️  Init falhou, tentando iniciar servidor mesmo assim..."
    exec python start_railway.py
fi
