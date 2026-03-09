import re

# Ler o arquivo
with open('aplicativo/autotrade_reactnativecli/screens/AdminScreen.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Padrões para remover estados de backtest
patterns = [
    # Estados de backtest (linhas 76-99 aproximadamente)
    r'\n  // Estados para BACKTEST.*?const \[checkingWsConnection.*?= useState\(false\);',
    
    # Funções de backtest
    r'\n  // Funções de BACKTEST.*?\n\n',
    r'\n  // Carregar usuários para backtest.*?\n\n',
    r'\n  // Buscar contas de backtest.*?\n\n',
    r'\n  // Iniciar backtest manual.*?\n\n',
    r'\n  // Iniciar backtest automático.*?\n\n',
    r'\n  // Parar backtest.*?\n\n',
    r'\n  // Verificar status do backtest.*?\n\n',
    r'\n  // Verificar conexão WebSocket.*?\n\n',
    
    # Renderização do card de backtest
    r'\n          \{(/\* Backtest Card \*/|// Card de Backtest).*?\n          \}',
    
    # Imports relacionados a backtest
    r'import.*?backtest.*?\n',
    
    # Referências a backtest em geral
    r'backtest',
    r'Backtest',
    r'BACKTEST',
]

# Aplicar substituições
for pattern in patterns:
    content = re.sub(pattern, '', content, flags=re.DOTALL | re.IGNORECASE)

# Salvar
with open('aplicativo/autotrade_reactnativecli/screens/AdminScreen.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ AdminScreen.tsx limpo")
