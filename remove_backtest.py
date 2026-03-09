"""
Script para remover completamente o backtest do sistema TunesTrade
"""
import re
import os
import glob

# Arquivos a modificar
FILES_TO_MODIFY = [
    "api/routers/admin.py",
    "api/routers/strategies.py", 
    "services/trade_executor.py",
    "services/strategies/custom_strategy.py",
    "services/strategies/manager.py",
    "services/strategies/base.py",
    "schemas/__init__.py",
    "core/config.py",
]

# Padrões para remover (regex)
PATTERNS_TO_REMOVE = [
    # Classes de backtest
    (r'class BacktestJob.*?# Global backtest manager instance\nbacktest_manager = BacktestManager\(\)', '', re.DOTALL),
    (r'class BacktestManager:.*?(?=\nclass |\n# |\n@router|\Z)', '', re.DOTALL),
    (r'class BacktestStartRequest.*?message: str\n\n\n', '', re.DOTALL),
    (r'class BacktestStopResponse.*?message: str\n\n\n', '', re.DOTALL),
    (r'class BacktestListResponse.*?running: int\n\n\n', '', re.DOTALL),
    
    # Endpoints de backtest
    (r'@router\.post\("/backtest/start".*?raise HTTPException\(status_code=500, detail=f"Erro ao iniciar backtest: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    (r'@router\.post\("/backtest/stop/\{job_id\}".*?raise HTTPException\(status_code=500, detail=f"Erro ao interromper backtest: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    (r'@router\.post\("/backtest/stop".*?raise HTTPException\(status_code=500, detail=f"Erro ao interromper backtest: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    (r'@router\.get\("/backtest/status/\{job_id\}".*?raise HTTPException\(status_code=500, detail=f"Erro ao obter status: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    (r'@router\.get\("/backtest/list".*?raise HTTPException\(status_code=500, detail=f"Erro ao listar backtests: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    (r'@router\.delete\("/backtest/\{job_id\}".*?raise HTTPException\(status_code=500, detail=f"Erro: \{str\(e\)\}"\)\n\n\n', '', re.DOTALL),
    
    # Imports de backtest
    (r'from services\.backtest_service import backtest_service\n', '', 0),
    (r'from services\.backtest_service import \*\n', '', 0),
    (r'import backtest_service\n', '', 0),
    
    # Enum BacktestStatus
    (r'class BacktestStatus\(Enum\):.*?\n\n', '', re.DOTALL),
    
    # Referências a backtest em código
    (r'# 🚀 BACKTEST FIX:.*?\n', '', re.DOTALL),
    (r'if is_backtest:.*?logger\..*?\n', '', re.DOTALL),
    (r'is_backtest = .*?\n', '', 0),
    (r'if strategy_id in \("backtest".*?\n', '', 0),
    (r'if trade\.strategy_id == "backtest".*?logger\..*?\n', '', re.DOTALL),
    (r'strategy_id="backtest_pure",', '', 0),
    
    # Comentários de backtest
    (r'#.*[Bb]acktest.*\n', '', 0),
    (r'""".*[Bb]acktest.*?"""\n', '', re.DOTALL),
]

def remove_backtest_from_file(filepath):
    """Remove referências de backtest de um arquivo"""
    if not os.path.exists(filepath):
        print(f"⚠️ Arquivo não encontrado: {filepath}")
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    
    for pattern, replacement, flags in PATTERNS_TO_REMOVE:
        content = re.sub(pattern, replacement, content, flags=flags)
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Atualizado: {filepath}")
    else:
        print(f"⏭️ Sem alterações: {filepath}")

def clean_database():
    """Limpa dados de backtest do banco"""
    print("\n🗄️ Limpando banco de dados...")
    
    script = """
-- Remover trades com strategy_id de backtest
DELETE FROM trades WHERE strategy_id LIKE '%backtest%';

-- Remover estratégias com nome ou id de backtest  
DELETE FROM strategies WHERE name LIKE '%backtest%' OR id LIKE '%backtest%';

-- Remover signals relacionados a estratégias de backtest
DELETE FROM signals WHERE strategy_id LIKE '%backtest%';

-- Verificar se há mais referências
SELECT 'Trades com backtest' as check_type, COUNT(*) as count FROM trades WHERE strategy_id LIKE '%backtest%'
UNION ALL
SELECT 'Strategies com backtest', COUNT(*) FROM strategies WHERE name LIKE '%backtest%' OR id LIKE '%backtest%'
UNION ALL
SELECT 'Signals com backtest', COUNT(*) FROM signals WHERE strategy_id LIKE '%backtest%';
"""
    
    with open('remove_backtest_db.sql', 'w') as f:
        f.write(script)
    
    print("✅ Script SQL criado: remove_backtest_db.sql")
    print("Execute: psql -U seu_user -d seu_db -f remove_backtest_db.sql")

def main():
    print("🔥 Iniciando remoção completa do backtest...\n")
    
    for filepath in FILES_TO_MODIFY:
        remove_backtest_from_file(filepath)
    
    clean_database()
    
    print("\n✅ Remoção concluída!")
    print("📋 Próximos passos:")
    print("   1. Execute o script SQL no banco de dados")
    print("   2. Verifique se há erros de importação")
    print("   3. Reinicie o servidor")

if __name__ == "__main__":
    main()
