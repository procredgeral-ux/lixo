-- Script para remover todos os dados de backtest do banco de dados
-- Execute este script no PostgreSQL

-- Verificar quantos registros serão afetados
SELECT 'Estratégias com backtest no nome ou ID' as tipo, COUNT(*) as quantidade 
FROM strategies 
WHERE name ILIKE '%backtest%' OR id ILIKE '%backtest%';

SELECT 'Trades com backtest' as tipo, COUNT(*) as quantidade 
FROM trades 
WHERE strategy_id ILIKE '%backtest%';

SELECT 'Signals com backtest' as tipo, COUNT(*) as quantidade 
FROM signals 
WHERE strategy_id ILIKE '%backtest%';

-- Remover trades com strategy_id de backtest
DELETE FROM trades WHERE strategy_id ILIKE '%backtest%';

-- Remover signals com strategy_id de backtest
DELETE FROM signals WHERE strategy_id ILIKE '%backtest%';

-- Remover estratégias com nome ou id de backtest
DELETE FROM strategies WHERE name ILIKE '%backtest%' OR id ILIKE '%backtest%';

-- Remover configurações de autotrade órfãs (que não têm estratégia válida)
DELETE FROM autotrade_configs 
WHERE strategy_id NOT IN (SELECT id FROM strategies);

-- Verificar se há mais registros de backtest
SELECT 'Trades restantes com backtest' as tipo, COUNT(*) as quantidade 
FROM trades 
WHERE strategy_id ILIKE '%backtest%';

SELECT 'Estratégias restantes com backtest' as tipo, COUNT(*) as quantidade 
FROM strategies 
WHERE name ILIKE '%backtest%' OR id ILIKE '%backtest%';

SELECT 'Configurações órfãs removidas' as status;
