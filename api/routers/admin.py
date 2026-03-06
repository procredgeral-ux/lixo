from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, delete
from sqlalchemy.orm import selectinload
from loguru import logger
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pydantic import BaseModel
from zoneinfo import ZoneInfo
import psutil
import time

# Timezone de Brasília (UTC-3)
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

def get_brasilia_time():
    """Retorna datetime atual no timezone de Brasília"""
    return datetime.now(BRASILIA_TZ)

from core.database import get_db, engine
from core.security.unified import get_security_health
from models import User, Account, Strategy, Signal, Trade, Asset, StrategyPerformanceSnapshot, MonitoringAccount, AutoTradeConfig, Indicator
from models.daily_summary import DailySignalSummary, AggregationJobLog
from api.dependencies import get_current_active_user, get_current_superuser
from schemas import UserResponse, UserAdminResponse
from services.unified_metrics import get_unified_metrics
from api.cache import cache, cached, invalidate_cache_pattern

router = APIRouter(tags=["admin"])

# Instância unificada de métricas (mesma lógica do dashboard.log)
metrics = get_unified_metrics()


class UserPlanResponse(BaseModel):
    """Response schema for user plan update"""
    role: str
    vip_start_date: datetime | None
    vip_end_date: datetime | None
    message: str


class PerformanceMetricsResponse(BaseModel):
    """Response schema for system performance metrics"""
    sistema: Dict[str, Any]
    api: Dict[str, Any]
    rede: Dict[str, Any]
    trades: Dict[str, Any]
    database: Dict[str, Any]
    processamento: Dict[str, Any]
    ativos: Dict[str, Any]
    lastUpdate: str


class DatabaseTableInfo(BaseModel):
    """Informações sobre uma tabela do banco de dados"""
    name: str
    count: int
    description: str
    size_bytes: int | None = None
    last_updated: datetime | None = None


class DatabaseTablesResponse(BaseModel):
    """Resposta com lista de tabelas"""
    tables: List[DatabaseTableInfo]
    total_tables: int
    total_records: int


class TableDataResponse(BaseModel):
    """Resposta com dados de uma tabela"""
    table_name: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int


# ... (manter endpoints existentes de users, plan, performance) ...


@router.get("/database/tables", response_model=DatabaseTablesResponse)
async def get_database_tables(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Listar todas as tabelas do banco de dados com contagens - COM CACHE"""
    cache_key = "admin:database:tables"
    
    # Tentar obter do cache
    cached_result = await cache.get(cache_key)
    if cached_result:
        logger.debug("[CACHE HIT] Database tables")
        return DatabaseTablesResponse(**cached_result)
    
    try:
        tables_info = [
            {"name": "users", "description": "Usuários do sistema", "model": User},
            {"name": "accounts", "description": "Contas de trading", "model": Account},
            {"name": "strategies", "description": "Estratégias de trading", "model": Strategy},
            {"name": "signals", "description": "Sinais gerados", "model": Signal},
            {"name": "trades", "description": "Trades executados", "model": Trade},
            {"name": "assets", "description": "Ativos disponíveis", "model": Asset},
            {"name": "strategy_performance_snapshots", "description": "Snapshots de performance", "model": StrategyPerformanceSnapshot},
            {"name": "monitoring_accounts", "description": "Contas de monitoramento", "model": MonitoringAccount},
            {"name": "autotrade_configs", "description": "Configurações de autotrade", "model": AutoTradeConfig},
            {"name": "indicators", "description": "Indicadores técnicos", "model": Indicator},
            {"name": "daily_signal_summary", "description": "Resumos diários", "model": DailySignalSummary},
        ]
        
        tables = []
        total_records = 0
        
        for table_info in tables_info:
            try:
                count = await db.scalar(select(func.count()).select_from(table_info["model"]))
                
                tables.append(DatabaseTableInfo(
                    name=table_info["name"],
                    count=count or 0,
                    description=table_info["description"],
                    size_bytes=None,
                    last_updated=get_brasilia_time()
                ))
                total_records += count or 0
            except Exception as e:
                logger.warning(f"Erro ao contar tabela {table_info['name']}: {e}")
                tables.append(DatabaseTableInfo(
                    name=table_info["name"],
                    count=0,
                    description=table_info["description"] + " (erro)",
                    size_bytes=None,
                    last_updated=None
                ))
        
        result = {
            "tables": [t.model_dump() for t in tables],
            "total_tables": len(tables),
            "total_records": total_records
        }
        
        # Salvar no cache (60 segundos)
        await cache.set(cache_key, result, ttl=60)
        
        logger.info(f"✓ [ADMIN] Database tables listadas por {current_user.email}")
        return DatabaseTablesResponse(**result)
        
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro ao listar tabelas: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao listar tabelas: {str(e)}")


@router.get("/database/tables/{table_name}", response_model=TableDataResponse)
async def get_table_data(
    table_name: str,
    page: int = Query(1, ge=1, description="Página de resultados"),
    page_size: int = Query(10, ge=1, le=100, description="Itens por página"),
    filter_text: str = Query(None, description="Texto para filtrar resultados"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Obter dados de uma tabela específica com paginação"""
    try:
        # Mapeamento de tabelas permitidas (evitar SQL injection) - TODAS as colunas
        allowed_tables = {
            "users": {"model": User, "columns": ["id", "email", "name", "hashed_password", "telegram_chat_id", "telegram_username", "is_active", "is_superuser", "role", "vip_start_date", "vip_end_date", "maintenance_logout_at", "created_at", "updated_at"]},
            "accounts": {"model": Account, "columns": ["id", "user_id", "ssid_demo", "ssid_real", "name", "autotrade_demo", "autotrade_real", "uid", "platform", "balance_demo", "balance_real", "currency", "is_active", "last_connected", "created_at", "updated_at"]},
            "strategies": {"model": Strategy, "columns": ["id", "user_id", "account_id", "name", "description", "type", "parameters", "assets", "indicators", "is_active", "total_trades", "winning_trades", "losing_trades", "total_profit", "total_loss", "created_at", "updated_at", "last_executed"]},
            "signals": {"model": Signal, "columns": ["id", "strategy_id", "asset_id", "timeframe", "signal_type", "confidence", "price", "indicators", "confluence", "signal_source", "is_executed", "trade_id", "created_at", "executed_at"]},
            "trades": {"model": Trade, "columns": ["id", "account_id", "asset_id", "strategy_id", "order_id", "connection_type", "direction", "amount", "entry_price", "exit_price", "duration", "status", "profit", "payout", "placed_at", "expires_at", "closed_at", "signal_confidence", "signal_indicators"]},
            "assets": {"model": Asset, "columns": ["id", "symbol", "name", "type", "is_active", "payout", "min_order_amount", "max_order_amount", "min_duration", "max_duration", "available_timeframes", "created_at", "updated_at"]},
            "strategy_performance_snapshots": {"model": StrategyPerformanceSnapshot, "columns": ["id", "user_id", "strategy_id", "period", "start_date", "end_date", "total_trades", "winning_trades", "losing_trades", "win_rate", "total_profit", "total_loss", "net_profit", "profit_factor", "max_drawdown", "sharpe_ratio", "avg_win", "avg_loss", "largest_win", "largest_loss", "consecutive_wins", "consecutive_losses", "monthly_returns", "calculated_at", "created_at", "updated_at"]},
            "monitoring_accounts": {"model": MonitoringAccount, "columns": ["id", "ssid", "account_type", "name", "is_active", "uid", "platform", "created_at", "updated_at"]},
            "autotrade_configs": {"model": AutoTradeConfig, "columns": ["id", "account_id", "strategy_id", "amount", "stop1", "stop2", "no_hibernate_on_consecutive_stop", "stop_amount_win", "stop_amount_loss", "soros", "martingale", "timeframe", "min_confidence", "cooldown_seconds", "trade_timing", "execute_all_signals", "all_win_percentage", "highest_balance", "initial_balance", "is_active", "daily_trades_count", "last_trade_date", "last_trade_time", "consecutive_stop_cooldown_until", "last_activity_timestamp", "soros_level", "soros_amount", "martingale_level", "martingale_amount", "loss_consecutive", "win_consecutive", "total_wins", "total_losses", "smart_reduction_enabled", "smart_reduction_loss_trigger", "smart_reduction_win_restore", "smart_reduction_percentage", "smart_reduction_active", "smart_reduction_base_amount", "smart_reduction_loss_count", "smart_reduction_win_count", "smart_reduction_cascading", "smart_reduction_cascade_level", "created_at", "updated_at"]},
            "indicators": {"model": Indicator, "columns": ["id", "name", "type", "description", "parameters", "is_active", "is_default", "version", "created_at", "updated_at"]},
            "daily_signal_summary": {"model": DailySignalSummary, "columns": ["id", "date", "strategy_id", "asset_id", "timeframe", "total_signals", "buy_signals", "sell_signals", "hold_signals", "executed_signals", "avg_confidence", "avg_confluence", "min_confidence", "max_confidence", "updated_at"]},
            "aggregation_job_log": {"model": AggregationJobLog, "columns": ["id", "job_name", "started_at", "completed_at", "status", "records_processed", "error_message"]},
        }
        
        if table_name not in allowed_tables:
            raise HTTPException(status_code=400, detail=f"Tabela '{table_name}' não permitida ou não existe")
        
        table_config = allowed_tables[table_name]
        model = table_config["model"]
        columns = table_config["columns"]
        
        # Calcular offset
        offset = (page - 1) * page_size
        
        # Query base
        query = select(model)
        
        # Aplicar filtro se fornecido
        if filter_text and hasattr(model, 'name'):
            query = query.where(model.name.ilike(f"%{filter_text}%"))
        elif filter_text and hasattr(model, 'email'):
            query = query.where(model.email.ilike(f"%{filter_text}%"))
        
        # Ordenar por data de criação decrescente
        if hasattr(model, 'created_at'):
            query = query.order_by(model.created_at.desc())
        
        # Paginação
        query = query.offset(offset).limit(page_size)
        
        # Executar query
        result = await db.execute(query)
        
        # Obter todos os resultados de uma vez (dentro do contexto async)
        rows_fetched = result.fetchall()
        
        # Converter resultados para dicionários imediatamente
        rows = []
        for row in rows_fetched:
            # row é uma tupla (Modelo,) - o objeto está em row[0]
            obj = row[0]
            row_dict = {}
            for col in columns:
                try:
                    value = getattr(obj, col, None)
                    # Converter datetime para string
                    if isinstance(value, datetime):
                        value = value.strftime("%Y-%m-%d %H:%M:%S")
                    row_dict[col] = value
                except Exception:
                    row_dict[col] = None
            rows.append(row_dict)
        
        # Contar total
        count_query = select(func.count()).select_from(model)
        count_result = await db.execute(count_query)
        total_count = count_result.scalar()
        
        logger.info(f"✓ [ADMIN] Dados da tabela {table_name} retornados: {len(rows)} registros (página {page})")
        
        return TableDataResponse(
            table_name=table_name,
            columns=columns,
            rows=rows,
            total_count=total_count or 0,
            page=page,
            page_size=page_size
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro ao obter dados da tabela {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter dados: {str(e)}")


@router.get("/users")
async def list_all_users(
    search: str = Query(None, description="Buscar por nome, email, plano ou telegram username"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Listar todos os usuários com saldos - COM CACHE"""
    cache_key = f"admin:users:list:{search or 'all'}"
    
    # Tentar obter do cache
    cached_result = await cache.get(cache_key)
    if cached_result:
        logger.debug("[CACHE HIT] Users list")
        return cached_result
    
    result = await db.execute(select(User))
    users = result.unique().scalars().all()
    
    # Filtrar se houver termo de busca
    if search and search.strip():
        search_lower = search.lower().strip()
        users = [u for u in users if 
            (u.name and search_lower in u.name.lower()) or
            (u.email and search_lower in u.email.lower()) or
            (u.role and search_lower in u.role.lower()) or
            (u.telegram_username and search_lower in u.telegram_username.lower())
        ]
    
    # Buscar todas as contas para calcular saldos
    accounts_result = await db.execute(select(Account))
    accounts = accounts_result.unique().scalars().all()
    
    # Agrupar contas por user_id
    accounts_by_user = {}
    for acc in accounts:
        if acc.user_id not in accounts_by_user:
            accounts_by_user[acc.user_id] = []
        accounts_by_user[acc.user_id].append(acc)
    
    # Construir resposta com saldos
    response = []
    for user in users:
        user_accounts = accounts_by_user.get(user.id, [])
        
        demo_balance = 0.0
        real_balance = 0.0
        for acc in user_accounts:
            if acc.ssid_demo:
                demo_balance += acc.balance_demo or 0.0
            if acc.ssid_real:
                real_balance += acc.balance_real or 0.0
        
        response.append(UserAdminResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
            telegram_chat_id=user.telegram_chat_id,
            telegram_username=user.telegram_username,
            role=user.role or 'free',
            vip_start_date=user.vip_start_date,
            vip_end_date=user.vip_end_date,
            demo_balance=demo_balance,
            real_balance=real_balance
        ))
    
    # Salvar no cache (30 segundos)
    response_dict = [r.model_dump() for r in response]
    await cache.set(cache_key, response_dict, ttl=30)
    
    return response


@router.get("/users/search")
async def search_user_by_email(
    email: str = Query(..., description="Email do usuário a buscar"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Buscar usuário por email (apenas superusuários)"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
        role=user.role or 'free',
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date
    )


@router.put("/users/{user_id}/plan", response_model=UserPlanResponse)
async def update_user_plan_admin(
    user_id: str,
    role: str = Query(..., description="Plano do usuário: 'free', 'vip', 'vip_plus'"),
    duration_days: int = Query(7, description="Duração em dias para VIP/VIP+"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Atualizar plano do usuário (apenas superusuários)"""
    # Validar role
    valid_roles = ['free', 'vip', 'vip_plus']
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Role inválido. Valores válidos: {', '.join(valid_roles)}"
        )
    
    # Buscar usuário
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado"
        )
    
    # Calcular datas de VIP
    now = get_brasilia_time()
    vip_start_date = None
    vip_end_date = None
    
    if role in ['vip', 'vip_plus']:
        vip_start_date = now
        vip_end_date = now + timedelta(days=duration_days)
    elif role == 'free':
        # Para plano free, remover datas VIP
        vip_start_date = None
        vip_end_date = None
    
    # Atualizar usuário
    user.role = role
    user.vip_start_date = vip_start_date
    user.vip_end_date = vip_end_date
    user.updated_at = now
    
    await db.commit()
    await db.refresh(user)
    
    logger.info(f"✓ [ADMIN] Plano do usuário {user.email} atualizado para {role.upper()}")
    
    return UserPlanResponse(
        role=user.role,
        vip_start_date=user.vip_start_date,
        vip_end_date=user.vip_end_date,
        message=f"Plano atualizado para {role.upper()}"
    )


@router.get("/performance", response_model=PerformanceMetricsResponse)
async def get_performance_metrics(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Obter métricas de performance do sistema - usa mesma lógica do dashboard.log"""
    try:
        # Coletar métricas de sistema (mesma lógica do performance_monitor.py)
        system = metrics.get_system_metrics()
        api = metrics.get_api_metrics()
        ws = metrics.get_websocket_metrics()
        database = metrics.get_database_metrics()
        cache = metrics.get_cache_metrics()
        batch = metrics.get_batch_metrics()
        
        # Contagens do banco de dados
        users_count = await db.scalar(select(func.count()).select_from(User))
        accounts_count = await db.scalar(select(func.count()).select_from(Account))
        strategies_count = await db.scalar(select(func.count()).select_from(Strategy))
        signals_count = await db.scalar(select(func.count()).select_from(Signal))
        trades_count = await db.scalar(select(func.count()).select_from(Trade))
        assets_count = await db.scalar(select(func.count()).select_from(Asset))
        
        # Contagens de hoje
        today = get_brasilia_time().replace(hour=0, minute=0, second=0, microsecond=0)
        # Remover timezone para compatibilidade com TIMESTAMP WITHOUT TIME ZONE no PostgreSQL
        today_naive = today.replace(tzinfo=None)
        trades_today = await db.scalar(
            select(func.count()).select_from(Trade).where(Trade.placed_at >= today_naive)
        )
        signals_today = await db.scalar(
            select(func.count()).select_from(Signal).where(Signal.created_at >= today_naive)
        )
        
        # Montar resposta no formato esperado pelo frontend
        performance_data = {
            "sistema": {
                "uptime": system['uptime'],
                "memoriaAtual": f"{system['memory_mb']:.1f} MB",
                "memoriaMedia": f"{system['avg_memory_mb']:.1f} MB (últimos 5min)",
                "cpuAtual": f"{system['cpu_percent']:.1f}%",
                "cpuMedia": f"{system['avg_cpu_percent']:.1f}% (últimos 5min)",
                "threads": system['threads'],
                "discoUso": f"{system['disk_usage_percent']:.1f}%",
                "discoIO": f"↓ {system['disk_read_mb']:.2f} MB ↑ {system['disk_write_mb']:.2f} MB",
                "networkIO": f"↓ {system['network_recv_mb']:.2f} MB ↑ {system['network_sent_mb']:.2f} MB",
                "loadAverage": f"{system['load_avg_1m']:.2f} / {system['load_avg_5m']:.2f} / {system['load_avg_15m']:.2f}",
                "swap": f"{system['swap_used_mb']:.1f} / {system['swap_total_mb']:.1f} MB",
            },
            "api": {
                "totalRequisicoes": api['total_requests'],
                "sucessos": f"{api['successful_requests']} ({api['success_rate']:.1f}%)",
                "falhas": api['failed_requests'],
                "erros4xx": api['http_4xx_errors'],
                "erros5xx": api['http_5xx_errors'],
                "rpsAtual": f"{api['rps_current']:.1f}/s",
                "rpsPico": f"{api['rps_current']:.1f}/s",  # Simplificado
                "latenciaMedia": f"{api['avg_latency_ms']:.1f} ms",
                "latenciaP95": f"{api['latency_p95_ms']:.1f} ms",
                "latenciaP99": f"{api['latency_p99_ms']:.1f} ms",
                "latenciaMaxima": f"{api['max_latency_ms']:.1f} ms",
            },
            "rede": {
                "conexoesUsuarios": ws['user_connections'],
                "conexoesMonitoramento": ws['monitoring_connections'],
                "totalConexoesWS": ws['ws_connections'],
                "contasAtivas": ws['active_accounts'],
                "mensagensWSEnviadas": ws['ws_messages_sent'],
                "mensagensWSRecebidas": ws['ws_messages_recv'],
                "reconexoes": ws['ws_reconnections'],
                "latenciaCorretora": f"{ws['broker_latency_ms']:.1f} ms",
            },
            "trades": {
                "tradesExecutados": trades_today,
                "tradesPendentes": 0,
                "taxaSucessoTrades": "0.0%",
                "sinaisGerados": signals_today,
                "sinaisExecutados": trades_today,
                "sinaisBaixaConf": 0,
            },
            "database": {
                "queriesExecutadas": database['db_queries'],
                "select": database['db_selects'],
                "insert": database['db_inserts'],
                "update": database['db_updates'],
                "delete": database['db_deletes'],
                "errosDB": database['db_errors'],
                "queriesLentas": database['db_slow_queries'],
                "tempoMedioQuery": f"{database['db_avg_time_ms']:.1f} ms",
                "tempoTotalQueries": f"{database['db_total_time_ms']:.1f} ms",
            },
            "processamento": {
                "cacheHits": cache['cache_hits'],
                "cacheMisses": cache['cache_misses'],
                "cacheHitRate": f"{cache['cache_hit_rate']:.1f}%",
                "batchFila": batch['batch_signals_queued'],
                "batchSalvos": batch['batch_signals_saved'],
                "batchErros": batch['batch_save_errors'],
                "batchTempoMedio": "0.0 ms",  # TODO
                "batchThroughput": "0.0 sinais/s",  # TODO
                "batchUltimoSave": batch['batch_last_save_time'],
                "agregacaoUltima": get_brasilia_time().strftime("%Y-%m-%d %H:%M:%S"),
                "agregacaoStatus": "running",
            },
            "ativos": {
                "ativosDisponiveis": assets_count,
                "ativosComDados": strategies_count,
                "ativosDesatualizados": 0,
                "atrasoMaximo": "0 ms",
                "atrasoMedio": "0 ms",
            },
            "lastUpdate": get_brasilia_time().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        
        logger.info(f"✓ [ADMIN] Métricas solicitadas por {current_user.email}")
        return performance_data
        
    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@router.get("/security/health", response_model=Dict[str, Any])
async def get_security_system_health(
    current_user: User = Depends(get_current_superuser)
):
    """Health check do sistema de segurança (sessões, blacklist, auditoria)"""
    try:
        health = await get_security_health()
        
        # Adicionar status interpretável
        redis_status = "healthy" if health['redis']['redis_connected'] else "degraded"
        overall_status = "healthy" if health['redis']['redis_connected'] else "operational"
        
        response = {
            "status": overall_status,
            "redis_status": redis_status,
            "initialized": health['initialized'],
            "components": {
                "sessions": {
                    "status": "healthy",
                    "redis_hits": health['sessions'].get('redis_hits', 0),
                    "memory_hits": health['sessions'].get('memory_hits', 0),
                    "misses": health['sessions'].get('misses', 0),
                    "memory_sessions": health['sessions'].get('memory_sessions', 0)
                },
                "token_blacklist": {
                    "status": "healthy",
                    "redis_hits": health['token_blacklist'].get('redis_hits', 0),
                    "memory_entries": health['token_blacklist'].get('memory_entries', 0)
                },
                "audit": {
                    "status": "healthy",
                    "redis_writes": health['audit'].get('redis_writes', 0),
                    "db_writes": health['audit'].get('db_writes', 0),
                    "buffer_size": health['audit'].get('buffer_size', 0),
                    "stream_length": health['audit'].get('redis_stream_length', 0)
                }
            },
            "timestamp": get_brasilia_time().isoformat()
        }
        
        logger.info(f"🔒 [SECURITY] Health check solicitado por {current_user.email}")
        return response
        
    except Exception as e:
        logger.error(f"✗ [SECURITY] Erro no health check: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


@router.get("/strategies/all")
async def get_all_users_strategies(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """
    Retorna estratégias de TODOS os usuários em uma única requisição.
    Otimizado com cache Redis.
    """
    cache_key = "admin:strategies:all"
    
    # Tentar obter do cache
    cached_result = await cache.get(cache_key)
    if cached_result:
        logger.debug("[CACHE HIT] All strategies")
        return cached_result
    
    from sqlalchemy import select
    from models import AutoTradeConfig
    
    logger.info(f"[ADMIN BATCH] {current_user.email} buscando estratégias de todos os usuários")
    
    try:
        query = (
            select(Strategy, User.id.label('user_id'), User.email, User.name,
                   AutoTradeConfig.is_active.label('autotrade_active'))
            .join(User, Strategy.user_id == User.id)
            .outerjoin(AutoTradeConfig, Strategy.id == AutoTradeConfig.strategy_id)
            .order_by(User.id, Strategy.created_at.desc())
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        strategies_by_user = {}
        
        for row in rows:
            strategy = row.Strategy
            user_id = str(row.user_id)
            autotrade_active = row.autotrade_active
            
            actual_is_active = autotrade_active if autotrade_active is not None else strategy.is_active
            
            if user_id not in strategies_by_user:
                strategies_by_user[user_id] = []
            
            strategies_by_user[user_id].append({
                "id": str(strategy.id),
                "name": strategy.name,
                "is_active": actual_is_active,
                "type": strategy.type,
                "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
                "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None,
                "total_trades": strategy.total_trades,
                "winning_trades": strategy.winning_trades,
                "losing_trades": strategy.losing_trades,
                "total_profit": float(strategy.total_profit) if strategy.total_profit else 0.0,
                "total_loss": float(strategy.total_loss) if strategy.total_loss else 0.0,
            })
        
        total_strategies = len(rows)
        total_users = len(strategies_by_user)
        active_strategies = sum(1 for r in rows if r.autotrade_active or r.Strategy.is_active)
        
        result = {
            "strategies_by_user": strategies_by_user,
            "total_strategies": total_strategies,
            "total_users": total_users,
            "active_strategies": active_strategies,
            "timestamp": get_brasilia_time().isoformat()
        }
        
        # Salvar no cache (10 segundos - dados mudam frequentemente)
        await cache.set(cache_key, result, ttl=10)
        
        logger.info(f"[ADMIN BATCH] ✓ {total_strategies} estratégias de {total_users} usuários")
        return result
        
    except Exception as e:
        logger.error(f"[ADMIN BATCH] ✗ Erro ao buscar estratégias: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar estratégias: {str(e)}")


# ============================================
# ENDPOINTS DE DELETE COM VERIFICAÇÃO DE DEPENDÊNCIAS
# ============================================

@router.delete("/database/tables/{table_name}/{record_id}")
async def delete_table_record(
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """
    Excluir um registro de uma tabela específica com CASCADE DELETE manual.
    Exclui automaticamente as dependências na ordem correta.
    """
    try:
        # Mapeamento de dependências por tabela (ordem importa - excluir filhos primeiro)
        deps_config = {
            "users": [
                {"model": AutoTradeConfig, "fk": "account_id", "name": "autotrade_configs", "requires_parent": "accounts"},
                {"model": StrategyPerformanceSnapshot, "fk": "user_id", "name": "performance_snapshots"},
                {"model": Signal, "fk": "user_id", "name": "signals"},
                {"model": Trade, "fk": "user_id", "name": "trades"},
                {"model": Strategy, "fk": "user_id", "name": "strategies"},
                {"model": Account, "fk": "user_id", "name": "accounts"},
            ],
            "accounts": [
                {"model": AutoTradeConfig, "fk": "account_id", "name": "autotrade_configs"},
                {"model": Trade, "fk": "account_id", "name": "trades"},
                {"model": Strategy, "fk": "account_id", "name": "strategies"},
            ],
            "strategies": [
                {"model": Signal, "fk": "strategy_id", "name": "signals"},
                {"model": Trade, "fk": "strategy_id", "name": "trades"},
                {"model": StrategyPerformanceSnapshot, "fk": "strategy_id", "name": "performance_snapshots"},
            ],
            "assets": [
                {"model": Signal, "fk": "asset_id", "name": "signals"},
                {"model": Trade, "fk": "asset_id", "name": "trades"},
            ],
            "indicators": [
                {"table": "strategy_indicators", "name": "strategy_indicators", "fk": "indicator_id"}
            ],
        }
        
        # Mapeamento de tabelas permitidas
        allowed_tables = {
            "users": {"model": User, "pk": "id"},
            "accounts": {"model": Account, "pk": "id"},
            "strategies": {"model": Strategy, "pk": "id"},
            "trades": {"model": Trade, "pk": "id"},
            "signals": {"model": Signal, "pk": "id"},
            "assets": {"model": Asset, "pk": "id"},
            "indicators": {"model": Indicator, "pk": "id"},
            "autotrade_configs": {"model": AutoTradeConfig, "pk": "id"},
            "monitoring_accounts": {"model": MonitoringAccount, "pk": "id"},
            "strategy_performance_snapshots": {"model": StrategyPerformanceSnapshot, "pk": "id"},
            "daily_signal_summary": {"model": DailySignalSummary, "pk": "id"},
            "aggregation_job_log": {"model": AggregationJobLog, "pk": "id"},
        }
        
        if table_name not in allowed_tables:
            raise HTTPException(status_code=400, detail=f"Tabela '{table_name}' não permitida ou não existe")
        
        config = allowed_tables[table_name]
        model = config["model"]
        pk_field = config["pk"]
        
        # Verificar se registro existe
        query = select(model).where(getattr(model, pk_field) == record_id)
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        
        if not record:
            raise HTTPException(status_code=404, detail=f"Registro {record_id} não encontrado na tabela {table_name}")
        
        deleted_deps = []
        
        # Excluir dependências primeiro (CASCADE DELETE manual)
        if table_name in deps_config:
            for dep in deps_config[table_name]:
                try:
                    if "table" in dep and dep["table"] == "strategy_indicators":
                        # Excluir da tabela de junção
                        delete_query = text(f"""
                            DELETE FROM strategy_indicators 
                            WHERE indicator_id = :record_id
                        """)
                        result = await db.execute(delete_query, {"record_id": record_id})
                        deleted_deps.append({"name": dep["name"], "count": result.rowcount})
                    else:
                        # Excluir registros do modelo
                        dep_model = dep["model"]
                        fk_field = dep["fk"]
                        
                        # Contar quantos serão excluídos
                        count_query = select(func.count()).select_from(dep_model).where(getattr(dep_model, fk_field) == record_id)
                        count_result = await db.execute(count_query)
                        count = count_result.scalar()
                        
                        if count > 0:
                            # Excluir os registros
                            delete_query = delete(dep_model).where(getattr(dep_model, fk_field) == record_id)
                            await db.execute(delete_query)
                            deleted_deps.append({"name": dep["name"], "count": count})
                except Exception as e:
                    logger.error(f"[ADMIN DELETE] Erro ao excluir dependência {dep['name']}: {e}")
                    # Continuar com outras dependências
        
        # Excluir registro principal
        await db.delete(record)
        await db.commit()
        
        logger.warning(f"🗑️ [ADMIN DELETE] {current_user.email} excluiu registro {record_id} da tabela {table_name} com {len(deleted_deps)} dependências")
        
        return {
            "success": True,
            "message": f"Registro {record_id} excluído com sucesso da tabela {table_name}",
            "table": table_name,
            "record_id": record_id,
            "deleted_dependencies": deleted_deps,
            "total_deleted": sum(d["count"] for d in deleted_deps) + 1
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"✗ [ADMIN DELETE] Erro ao excluir {record_id} de {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao excluir registro: {str(e)}")


@router.get("/database/tables/{table_name}/{record_id}/dependencies")
async def check_record_dependencies(
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Verificar dependências de um registro antes de excluir"""
    try:
        # Mapeamento de dependências por tabela
        deps_config = {
            "assets": [
                {"model": Trade, "fk": "asset_id", "name": "trades"},
                {"model": Signal, "fk": "asset_id", "name": "signals"}
            ],
            "indicators": [
                {"table": "strategy_indicators", "name": "strategies"}
            ],
            "users": [
                {"model": Account, "fk": "user_id", "name": "accounts"},
                {"model": Strategy, "fk": "user_id", "name": "strategies"}
            ],
            "accounts": [
                {"model": Trade, "fk": "account_id", "name": "trades"},
                {"model": Strategy, "fk": "account_id", "name": "strategies"},
                {"model": AutoTradeConfig, "fk": "account_id", "name": "autotrade_configs"}
            ],
            "strategies": [
                {"model": Signal, "fk": "strategy_id", "name": "signals"},
                {"model": Trade, "fk": "strategy_id", "name": "trades"},
                {"model": StrategyPerformanceSnapshot, "fk": "strategy_id", "name": "performance_snapshots"}
            ]
        }
        
        if table_name not in deps_config:
            return {"table": table_name, "record_id": record_id, "dependencies": [], "can_delete": True}
        
        dependencies = []
        total_deps = 0
        
        for dep in deps_config[table_name]:
            if "table" in dep and dep["table"] == "strategy_indicators":
                # Verificar tabela de junção
                check_query = text("""
                    SELECT COUNT(*) FROM strategy_indicators 
                    WHERE indicator_id = :record_id
                """)
                result = await db.execute(check_query, {"record_id": record_id})
                count = result.scalar()
                if count > 0:
                    dependencies.append({"name": dep["name"], "count": count})
                    total_deps += count
            else:
                dep_model = dep["model"]
                fk_field = dep["fk"]
                
                check_query = select(func.count()).select_from(dep_model).where(getattr(dep_model, fk_field) == record_id)
                count = await db.scalar(check_query)
                
                if count > 0:
                    dependencies.append({"name": dep["name"], "count": count})
                    total_deps += count
        
        return {
            "table": table_name,
            "record_id": record_id,
            "dependencies": dependencies,
            "total_dependencies": total_deps,
            "can_delete": total_deps == 0
        }
        
    except Exception as e:
        logger.error(f"✗ [ADMIN DEPS] Erro ao verificar dependências: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao verificar dependências: {str(e)}")


@router.put("/database/tables/{table_name}/{record_id}")
async def update_table_record(
    table_name: str,
    record_id: str,
    data: Dict[str, Any],
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """
    Atualizar um registro de uma tabela específica.
    PERMITE EDITAR TODOS OS CAMPOS exceto id, created_at e campos de sistema protegidos.
    """
    try:
        # Mapeamento de tabelas permitidas - agora todos os campos são editáveis por padrão
        allowed_tables = {
            "users": {"model": User, "pk": "id", "protected": ["id", "created_at", "hashed_password"]},
            "accounts": {"model": Account, "pk": "id", "protected": ["id", "created_at", "user_id"]},
            "strategies": {"model": Strategy, "pk": "id", "protected": ["id", "created_at", "user_id"]},
            "trades": {"model": Trade, "pk": "id", "protected": ["id", "created_at", "placed_at"]},
            "signals": {"model": Signal, "pk": "id", "protected": ["id", "created_at"]},
            "assets": {"model": Asset, "pk": "id", "protected": ["id", "created_at"]},
            "indicators": {"model": Indicator, "pk": "id", "protected": ["id", "created_at", "version"]},
            "autotrade_configs": {"model": AutoTradeConfig, "pk": "id", "protected": ["id", "created_at"]},
            "monitoring_accounts": {"model": MonitoringAccount, "pk": "id", "protected": ["id", "created_at"]},
            "strategy_performance_snapshots": {"model": StrategyPerformanceSnapshot, "pk": "id", "protected": ["id", "created_at"]},
            "daily_signal_summary": {"model": DailySignalSummary, "pk": "id", "protected": ["id", "created_at"]},
            "aggregation_job_log": {"model": AggregationJobLog, "pk": "id", "protected": ["id", "started_at"]},
        }
        
        if table_name not in allowed_tables:
            raise HTTPException(status_code=400, detail=f"Tabela '{table_name}' não permitida ou não existe")
        
        config = allowed_tables[table_name]
        model = config["model"]
        pk_field = config["pk"]
        protected_fields = config.get("protected", ["id", "created_at"])
        
        # Verificar se registro existe
        query = select(model).where(getattr(model, pk_field) == record_id)
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        
        if not record:
            raise HTTPException(status_code=404, detail=f"Registro {record_id} não encontrado na tabela {table_name}")
        
        # Atualizar TODOS os campos enviados, exceto os protegidos
        updated_fields = {}
        for field, value in data.items():
            # Pular campos protegidos
            if field in protected_fields:
                continue
                
            if hasattr(record, field):
                try:
                    # Converter tipos se necessário
                    current_value = getattr(record, field)
                    
                    # Tratar None - manter None se o valor for vazio
                    if value is None or value == '':
                        if current_value is None:
                            setattr(record, field, None)
                            updated_fields[field] = None
                        continue
                    
                    # Tratar booleans
                    if isinstance(current_value, bool):
                        if isinstance(value, bool):
                            new_value = value
                        elif isinstance(value, str):
                            new_value = value.lower() in ('true', '1', 'yes', 'sim')
                        else:
                            new_value = bool(value)
                        setattr(record, field, new_value)
                        updated_fields[field] = new_value
                    # Tratar integers
                    elif isinstance(current_value, int) and not isinstance(current_value, bool):
                        try:
                            new_value = int(value)
                            setattr(record, field, new_value)
                            updated_fields[field] = new_value
                        except (ValueError, TypeError):
                            continue
                    # Tratar floats
                    elif isinstance(current_value, float):
                        try:
                            new_value = float(value)
                            setattr(record, field, new_value)
                            updated_fields[field] = new_value
                        except (ValueError, TypeError):
                            continue
                    # Tratar datetime - converter string para datetime
                    elif isinstance(current_value, datetime):
                        try:
                            if isinstance(value, str):
                                # Tentar diferentes formatos de data
                                from datetime import date
                                try:
                                    # Formato ISO: 2026-03-06T14:30:00
                                    new_value = datetime.fromisoformat(value.replace('Z', '+00:00').replace('+00:00', ''))
                                except ValueError:
                                    try:
                                        # Formato: 2026-03-06 14:30:00
                                        new_value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                                    except ValueError:
                                        try:
                                            # Formato data apenas: 2026-03-06
                                            new_value = datetime.strptime(value, '%Y-%m-%d')
                                        except ValueError:
                                            # Manter valor original se não conseguir converter
                                            continue
                            elif isinstance(value, datetime):
                                new_value = value
                            else:
                                continue
                            
                            setattr(record, field, new_value)
                            updated_fields[field] = new_value.isoformat() if isinstance(new_value, datetime) else new_value
                        except Exception as e:
                            logger.warning(f"[ADMIN UPDATE] Erro ao converter data {field}: {e}")
                            continue
                    # Tratar date (apenas data, sem hora)
                    elif isinstance(current_value, date) and not isinstance(current_value, datetime):
                        try:
                            if isinstance(value, str):
                                new_value = date.fromisoformat(value)
                            elif isinstance(value, date):
                                new_value = value
                            else:
                                continue
                            setattr(record, field, new_value)
                            updated_fields[field] = str(new_value)
                        except Exception as e:
                            logger.warning(f"[ADMIN UPDATE] Erro ao converter date {field}: {e}")
                            continue
                    # Tratar strings e outros tipos
                    else:
                        setattr(record, field, value)
                        updated_fields[field] = value
                        
                except Exception as e:
                    logger.warning(f"[ADMIN UPDATE] Erro ao atualizar campo {field}: {e}")
                    continue
        
        # Atualizar updated_at automaticamente se existir
        if hasattr(record, 'updated_at'):
            record.updated_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info(f"✏️ [ADMIN UPDATE] {current_user.email} atualizou registro {record_id} da tabela {table_name}: {list(updated_fields.keys())}")
        
        return {
            "success": True,
            "message": f"Registro {record_id} atualizado com sucesso",
            "table": table_name,
            "record_id": record_id,
            "updated_fields": updated_fields
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"✗ [ADMIN UPDATE] Erro ao atualizar {record_id} de {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar registro: {str(e)}")


class AccountModeUpdate(BaseModel):
    """Schema para atualização do modo demo/real da conta"""
    autotrade_demo: bool
    autotrade_real: bool


@router.put("/users/{user_id}/account-mode")
async def update_user_account_mode(
    user_id: str,
    mode_update: AccountModeUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """
    Atualizar modo demo/real da conta de um usuário específico (apenas superusuários).
    Alterna entre conta demo e real para autotrade.
    """
    try:
        # Buscar conta do usuário
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()

        if not account:
            # Criar conta automaticamente se não existir
            target_user_result = await db.execute(
                select(User).where(User.id == user_id)
            )
            target_user = target_user_result.scalar_one_or_none()
            
            if not target_user:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")
            
            account = Account(
                user_id=user_id,
                name=f"Conta de {target_user.name}",
                autotrade_demo=True,
                autotrade_real=False,
                uid=0,
                platform=0
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)
            logger.info(f"[ADMIN] Conta criada automaticamente para usuário {user_id}")

        # Detectar mudança de modo
        old_demo = account.autotrade_demo
        old_real = account.autotrade_real

        # Alternar corretamente autotrade_demo e autotrade_real
        if mode_update.autotrade_demo is True and mode_update.autotrade_real is False:
            account.autotrade_demo = True
            account.autotrade_real = False
            mode_label = "DEMO"
        elif mode_update.autotrade_real is True and mode_update.autotrade_demo is False:
            account.autotrade_demo = False
            account.autotrade_real = True
            mode_label = "REAL"
        else:
            # Se ambos são True ou ambos são False, manter valores atuais ou definir demo como padrão
            if not account.autotrade_demo and not account.autotrade_real:
                account.autotrade_demo = True
                account.autotrade_real = False
                mode_label = "DEMO (padrão)"
            else:
                mode_label = "DEMO" if account.autotrade_demo else "REAL"

        account.updated_at = datetime.utcnow().replace(tzinfo=None)

        await db.commit()
        await db.refresh(account)

        # Se o modo mudou, desconectar a conexão anterior
        if old_demo != account.autotrade_demo or old_real != account.autotrade_real:
            from services.data_collector.realtime import data_collector
            from models import Strategy, AutoTradeConfig
            from sqlalchemy import update as sql_update, select as sql_select, and_

            # Desativar todas as estratégias do usuário para evitar conflitos
            await db.execute(
                sql_update(Strategy).where(Strategy.user_id == user_id).values(is_active=False)
            )
            
            # Desativar configs de autotrade
            config_ids_result = await db.execute(
                sql_select(AutoTradeConfig.id).join(Account, AutoTradeConfig.account_id == Account.id)
                .where(Account.user_id == user_id)
            )
            config_ids = [row[0] for row in config_ids_result.fetchall()]
            if config_ids:
                # Usar datetime sem timezone para o PostgreSQL
                now_naive = datetime.utcnow().replace(tzinfo=None)
                await db.execute(
                    sql_update(AutoTradeConfig).where(AutoTradeConfig.id.in_(config_ids)).values(
                        is_active=False,
                        win_consecutive=0,
                        loss_consecutive=0,
                        soros_level=0,
                        martingale_level=0,
                        updated_at=now_naive
                    )
                )
            await db.commit()

            # Determinar de onde e para onde estamos mudando
            from_type = 'real' if old_real else 'demo'
            to_type = 'real' if account.autotrade_real else 'demo'
            ssid = account.ssid_real if account.autotrade_real else account.ssid_demo

            # Se houve mudança e temos SSID para conectar
            if ssid:
                try:
                    await data_collector.connection_manager.switch_connection(
                        account.id, from_type, to_type, ssid
                    )
                except Exception as e:
                    logger.error(f"[ADMIN] Erro ao alternar conexão: {e}")

        logger.info(f"✓ [ADMIN] Modo da conta do usuário {user_id} atualizado para {mode_label} por {current_user.email}")

        return {
            "success": True,
            "message": f"Modo da conta atualizado para {mode_label}",
            "user_id": user_id,
            "account_id": account.id,
            "autotrade_demo": account.autotrade_demo,
            "autotrade_real": account.autotrade_real,
            "mode": "demo" if account.autotrade_demo else "real"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"✗ [ADMIN] Erro ao atualizar modo da conta: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar modo: {str(e)}")


@router.get("/users/{user_id}/account")
async def get_user_account(
    user_id: str,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """
    Obter dados da conta de um usuário específico (apenas superusuários).
    """
    try:
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()

        if not account:
            return {
                "user_id": user_id,
                "exists": False,
                "autotrade_demo": True,
                "autotrade_real": False,
                "mode": "demo"
            }

        return {
            "user_id": user_id,
            "exists": True,
            "account_id": account.id,
            "name": account.name,
            "autotrade_demo": account.autotrade_demo,
            "autotrade_real": account.autotrade_real,
            "balance_demo": account.balance_demo,
            "balance_real": account.balance_real,
            "ssid_demo": bool(account.ssid_demo),
            "ssid_real": bool(account.ssid_real),
            "mode": "demo" if account.autotrade_demo else "real",
            "updated_at": account.updated_at.isoformat() if account.updated_at else None
        }

    except Exception as e:
        logger.error(f"✗ [ADMIN] Erro ao buscar conta do usuário: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar conta: {str(e)}")


# ============================================
# ENDPOINTS DE CACHE
# ============================================

from pydantic import BaseModel

class CacheInvalidateRequest(BaseModel):
    """Schema para invalidação de cache"""
    pattern: str = "admin:*"


@router.post("/cache/invalidate")
async def invalidate_cache(
    request: CacheInvalidateRequest,
    current_user: User = Depends(get_current_superuser),
):
    """Invalidar cache por pattern (apenas superusuários)"""
    try:
        deleted = await cache.delete_pattern(request.pattern)
        logger.info(f"[ADMIN CACHE] {current_user.email} invalidou {deleted} chaves com pattern '{request.pattern}'")
        return {
            "success": True,
            "pattern": request.pattern,
            "deleted_keys": deleted,
            "message": f"{deleted} chaves removidas do cache"
        }
    except Exception as e:
        logger.error(f"[ADMIN CACHE] Erro ao invalidar cache: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao invalidar cache: {str(e)}")


@router.get("/cache/stats")
async def get_cache_stats(
    current_user: User = Depends(get_current_superuser),
):
    """Obter estatísticas do cache Redis (apenas superusuários)"""
    try:
        if not cache._is_connected:
            return {
                "connected": False,
                "message": "Redis não conectado"
            }
        
        # Contar chaves do admin
        admin_keys = await cache._client.keys("admin:*")
        
        return {
            "connected": True,
            "admin_keys_count": len(admin_keys),
            "keys_preview": [k.decode() if isinstance(k, bytes) else k for k in admin_keys[:10]]
        }
    except Exception as e:
        logger.error(f"[ADMIN CACHE] Erro ao obter stats: {e}")
        return {
            "connected": False,
            "error": str(e)
        }
