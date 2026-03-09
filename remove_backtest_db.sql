
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
