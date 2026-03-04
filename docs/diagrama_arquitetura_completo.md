# Diagrama Arquitetural Completo - TunesTrade

> Diagrama em formato Mermaid. Para visualizar:
> - Use: https://mermaid.live
> - Ou extensão Mermaid no VS Code
> - Ou GitHub (renderiza automaticamente)

## 1. Diagrama de Arquitetura de Alto Nível

```mermaid
flowchart TB
    subgraph External["🌐 EXTERNO"]
        PO["PocketOption API<br/>WebSocket Binary"]
        TG["Telegram API<br/>Notificações"]
    end

    subgraph Users["👥 USUÁRIOS"]
        Mobile["App React Native<br/>iOS / Android"]
        Admin["Painel Admin<br/>Web/Mobile"]
    end

    subgraph Backend["⚙️ BACKEND - FastAPI"]
        subgraph APILayer["🛡️ API Layer"]
            Routers["16 Routers<br/>REST + WebSocket"]
            Security["Security<br/>JWT | Rate Limit | API Keys"]
            Middleware["Middleware<br/>CORS | CSRF | Audit"]
        end

        subgraph CoreServices["🔧 Core Services"]
            DataCollector["DataCollector<br/>realtime.py (3.3K linhas)"]
            TradeExecutor["TradeExecutor<br/>(2.7K linhas)"]
            ConnectionMgr["ConnectionManager<br/>(1.5K linhas)"]
            Analysis["Analysis Engine<br/>37 Indicadores"]
        end

        subgraph PocketInt["🔗 PocketOption Integration"]
            POClient["WebSocket Client<br/>client.py (66KB)"]
            KeepAlive["Keep Alive<br/>(48KB)"]
            Maintenance["Maintenance Checker"]
        end

        subgraph BusinessLogic["📊 Business Logic"]
            Strategies["Strategies<br/>CRUD + Backtest"]
            Indicators["Indicators<br/>37 Técnicos"]
            Signals["Signals<br/>Processamento"]
            Config["AutoTrade Config<br/>Gerenciamento"]
        end

        subgraph Notifications["🔔 Notifications"]
            Telegram["Telegram v2<br/>(36KB)"]
        end
    end

    subgraph DataLayer["💾 DATA LAYER"]
        PostgreSQL[("PostgreSQL<br/>Async | SQLAlchemy 2.0")]
        Redis[("Redis<br/>Cache L2")]
        LocalCache["Cache L1<br/>Memória Local"]
    end

    subgraph Infrastructure["🏗️ INFRAESTRUTURA"]
        Docker["Docker<br/>Containerização"]
        Railway["Railway<br/>Deploy"]
        Logs["Logs<br/>Estruturados"]
    end

    %% Fluxos principais
    Mobile <-->|"HTTPS + JWT"| Routers
    Admin <-->|"HTTPS + JWT"| Routers
    
    Routers --> Security
    Routers --> Middleware
    Routers --> CoreServices
    Routers --> BusinessLogic
    
    DataCollector -->|"WebSocket"| POClient
    POClient <-->|"Binary WebSocket"| PO
    POClient --> KeepAlive
    POClient --> Maintenance
    
    TradeExecutor -->|"Executa Ordens"| POClient
    TradeExecutor -->|"Notifica"| Telegram
    Telegram -->|"API"| TG
    
    DataCollector -->|"Ticks/Candles"| Analysis
    Analysis -->|"Sinais"| Signals
    Signals -->|"Trigger"| TradeExecutor
    
    BusinessLogic -->|"Persiste"| PostgreSQL
    CoreServices -->|"Cache"| Redis
    CoreServices -->|"Buffer"| LocalCache
    
    ConnectionMgr -->|"Gerencia"| DataCollector
    ConnectionMgr -->|"Gerencia"| POClient
```

---

## 2. Diagrama de Fluxo de Dados (Data Flow)

```mermaid
sequenceDiagram
    participant PO as PocketOption
    participant CM as ConnectionManager
    participant DC as DataCollector
    participant TE as TradeExecutor
    participant AN as Analysis Engine
    participant DB as PostgreSQL
    participant API as FastAPI Routers
    participant APP as App Mobile
    participant TG as Telegram

    Note over PO,APP: FLUXO DE DADOS EM TEMPO REAL

    loop WebSocket Connection
        PO->>CM: Ticks Binários (cada 1s)
        CM->>DC: Raw Data
        DC->>DC: Agregação de Candles
        DC->>DB: Persistir Candles
    end

    Note over DC,AN: ANÁLISE TÉCNICA

    DC->>AN: Candles (OHLCV)
    AN->>AN: Calcular 37 Indicadores
    AN->>AN: Detectar Padrões
    AN->>DB: Salvar Sinais

    Note over AN,TE: EXECUÇÃO DE TRADES

    AN->>API: WebSocket: Novo Sinal
    API->>APP: Push: Sinal Detectado
    
    alt Auto-Trade Ativado
        AN->>TE: Executar Trade
        TE->>TE: Validar Risco
        TE->>PO: Enviar Ordem
        PO-->>TE: Confirmação
        TE->>DB: Salvar Trade
        TE->>TG: Notificação
    end

    Note over PO,TE: MONITORAMENTO

    loop Callback Loop
        PO-->>TE: Resultado do Trade
        TE->>DB: Atualizar Trade
        TE->>TE: Aplicar Soros/Martingale
        TE->>APP: WebSocket: Trade Fechado
    end
```

---

## 3. Diagrama de Componentes do Backend

```mermaid
flowchart TB
    subgraph FastAPI["🚀 FastAPI Application"]
        direction TB
        
        subgraph Routers["📡 Routers (16)"]
            strategies["strategies.py<br/>28KB"]
            websocket["websocket.py<br/>21KB"]
            users["users.py<br/>14KB"]
            indicators["indicators.py<br/>14KB"]
            trades["trades.py<br/>12KB"]
            admin["admin.py<br/>11KB"]
            auth["auth.py"]
            autotrade["autotrade_config.py"]
            accounts["accounts.py"]
            candles["candles.py"]
            signals["signals.py"]
            reports["reports.py"]
            maintenance["maintenance.py"]
            health["health_resilience.py"]
            assets["assets.py"]
            connection["connection.py"]
            helpers["helpers.py"]
        end

        subgraph Core["🔧 Core"]
            config["config.py<br/>Configurações"]
            database["database.py<br/>PostgreSQL Async"]
            cache["cache.py<br/>Redis"]
            security["security/<br/>JWT | API Keys | Audit"]
            middleware["middleware/<br/>CORS | CSRF | Metrics"]
        end

        subgraph Models["🗄️ Models SQLAlchemy (11)"]
            user["User"]
            account["Account"]
            asset["Asset"]
            trade["Trade"]
            strategy["Strategy"]
            signal["Signal"]
            autotradeconfig["AutoTradeConfig<br/>75+ campos"]
            indicator["Indicator"]
            monitoring["MonitoringAccount"]
            snapshot["StrategyPerformanceSnapshot"]
            summary["DailySummary"]
        end
    end

    subgraph Services["⚙️ Services"]
        direction TB
        
        subgraph DataCollectorSvc["📊 Data Collector"]
            realtime["realtime.py<br/>171KB | 3.3K linhas"]
            connmgr["connection_manager.py<br/>73KB | 1.5K linhas"]
            localstorage["local_storage.py"]
            reconnection["reconnection_manager.py"]
        end

        subgraph PocketOptionSvc["🔗 PocketOption"]
            poclient["client.py<br/>66KB | WebSocket"]
            keepalive["keep_alive.py<br/>48KB"]
            maintenancechecker["maintenance_checker.py"]
            powebsocket["websocket.py<br/>20KB"]
            pomodels["models.py"]
        end

        subgraph TradeSvc["💼 Trade Services"]
            tradeexecutor["trade_executor.py<br/>150KB | 2.7K linhas"]
            performance["performance_monitor.py<br/>41KB"]
        end

        subgraph AnalysisSvc["📈 Analysis"]
            indicatorsbase["indicators/base.py"]
            rsi["indicators/rsi.py<br/>37KB"]
            zonas["indicators/zonas.py<br/>56KB"]
            stochastic["indicators/stochastic.py<br/>17KB"]
            macd["indicators/macd.py<br/>15KB"]
            bollinger["indicators/bollinger.py<br/>14KB"]
            other["+32 outros indicadores"]
        end

        subgraph NotificationSvc["🔔 Notifications"]
            telegramv2["telegram_v2.py<br/>36KB"]
            telegram["telegram.py<br/>32KB"]
        end

        subgraph StrategySvc["🎯 Strategies"]
            strategiesvc["strategies/"]
            backtest["backtest/"]
        end

        subgraph EngineSvc["🔨 Engine"]
            hft["HFT_INTEGRATION_CODE.py"]
            integration["INTEGRATION_GUIDE.py"]
            resumo["RESUMO_IMPLEMENTACAO.py"]
        end

        subgraph OtherSvc["🛠️ Outros"]
            aggregation["aggregation_job.py"]
            auth_svc["auth_service.py"]
            candles_svc["candles_service.py"]
            account_svc["account_service.py"]
            cache_svc["autotrade_config_cache.py"]
        end
    end

    Routers --> Services
    Services --> Models
    Core --> Services
    Core --> Models
```

---

## 4. Diagrama de Deploy/Infraestrutura

```mermaid
flowchart TB
    subgraph ClientLayer["🌍 Client Layer"]
        MobileApp["📱 App React Native<br/>Expo / RN CLI"]
        WebDashboard["💻 Dashboard Web<br/>(futuro)"]
    end

    subgraph EdgeLayer["🌐 Edge Layer"]
        Cloudflare["Cloudflare<br/>CDN + DDoS"]
        Ngrok["Ngrok<br/>Dev Tunnel"]
    end

    subgraph ApplicationLayer["⚙️ Application Layer"]
        subgraph DockerContainer["🐳 Docker Container"]
            FastAPI["FastAPI App<br/>Python 3.11<br/>Uvicorn + Gunicorn"]
            
            subgraph InternalServices["Internal Services"]
                WSManager["WebSocket Manager<br/>ConnectionManager"]
                BackgroundJobs["Background Jobs<br/>Cleanup VIP"]
            end
        end
    end

    subgraph DataLayer["💾 Data Layer"]
        PostgreSQL[("PostgreSQL<br/>Asyncpg<br/>Produção")]
        RedisCache[("Redis<br/>Cache + Pub/Sub")]
        SQLite[("SQLite<br/>Local/Dev")]
    end

    subgraph ExternalServices["🔌 External Services"]
        PocketOptionWS["PocketOption<br/>WebSocket Binary"]
        TelegramAPI["Telegram Bot API<br/>Notificações"]
    end

    subgraph Monitoring["📊 Observabilidade"]
        Logs["Loguru<br/>Logs Estruturados"]
        Metrics["Performance Metrics"]
        Audit["Audit Trail"]
    end

    subgraph DevOps["🚀 DevOps"]
        Railway["Railway.app<br/>Deploy Principal"]
        GitHub["GitHub<br/>CI/CD"]
        DockerHub["Docker Hub<br/>Registry"]
    end

    MobileApp -->|"HTTPS / WS"| Cloudflare
    WebDashboard -->|"HTTPS / WS"| Cloudflare
    
    Cloudflare -->|"Proxy"| Railway
    Ngrok -->|"Dev Only"| FastAPI
    
    Railway -->|"Container"| DockerContainer
    
    FastAPI -->|"Async SQLAlchemy"| PostgreSQL
    FastAPI -->|"Redis-py"| RedisCache
    
    WSManager -->|"WebSocket Binary"| PocketOptionWS
    WSManager -->|"Bot API"| TelegramAPI
    
    FastAPI -->|"Loguru"| Logs
    FastAPI -->|"Métricas"| Metrics
    FastAPI -->|"Audit"| Audit
    
    GitHub -->|"Deploy"| Railway
    DockerHub -->|"Pull"| Railway
```

---

## 5. Diagrama de Entidades de Banco de Dados

```mermaid
erDiagram
    USER ||--o{ ACCOUNT : "possui"
    USER ||--o{ STRATEGY : "cria"
    USER ||--o{ AUTOTRADE_CONFIG : "configura"
    USER ||--o{ TRADE : "executa"
    
    ACCOUNT ||--o{ TRADE : "executa"
    ACCOUNT ||--o{ AUTOTRADE_CONFIG : "vinculado"
    
    STRATEGY ||--o{ INDICATOR : "usa"
    STRATEGY ||--o{ AUTOTRADE_CONFIG : "configura"
    STRATEGY ||--o{ SIGNAL : "gera"
    STRATEGY ||--o{ STRATEGY_PERFORMANCE_SNAPSHOT : "métricas"
    
    ASSET ||--o{ TRADE : "negociado"
    ASSET ||--o{ SIGNAL : "associado"
    ASSET ||--o{ CANDLE : "dados"
    
    AUTOTRADE_CONFIG ||--o{ TRADE : "gerencia"
    
    SIGNAL ||--o{ TRADE : "resulta"
    
    USER {
        int id PK
        string email
        string password_hash
        string name
        boolean is_vip
        date vip_expires_at
        string telegram_chat_id
        timestamp created_at
        timestamp updated_at
    }
    
    ACCOUNT {
        int id PK
        int user_id FK
        string ssid
        enum type "demo|real"
        decimal balance
        boolean is_active
        timestamp created_at
    }
    
    STRATEGY {
        int id PK
        int user_id FK
        string name
        text description
        json config
        boolean is_active
        timestamp created_at
    }
    
    INDICATOR {
        int id PK
        int strategy_id FK
        string name
        string type
        json parameters
        int weight
    }
    
    AUTOTRADE_CONFIG {
        int id PK
        int account_id FK
        int strategy_id FK
        boolean is_active
        decimal amount
        decimal min_confidence
        string timeframe
        
        %% Risk Settings
        int stop1
        int stop2
        decimal stop_amount_win
        decimal stop_amount_loss
        
        %% Progression
        boolean soros_enabled
        int soros_count
        boolean martingale_enabled
        int martingale_count
        
        %% Smart Reduction
        boolean smart_reduction_enabled
        int smart_reduction_activation
        int smart_reduction_stop
        int smart_reduction_count
        
        %% State Counters
        int consecutive_wins
        int consecutive_losses
        int daily_trades
        decimal daily_profit
        
        %% Timestamps
        timestamp last_trade_at
        timestamp last_win_at
        timestamp last_loss_at
        timestamp created_at
        timestamp updated_at
    }
    
    TRADE {
        int id PK
        int account_id FK
        int autotrade_config_id FK
        int signal_id FK
        string asset
        enum direction "call|put"
        decimal amount
        decimal payout
        enum status "pending|open|won|lost"
        timestamp placed_at
        timestamp expires_at
        timestamp closed_at
        decimal result_amount
    }
    
    SIGNAL {
        int id PK
        int strategy_id FK
        string asset
        enum direction "call|put"
        decimal confidence
        timestamp created_at
        timestamp executed_at
        boolean was_executed
    }
    
    ASSET {
        string id PK
        string name
        string type
        boolean otc
        boolean active
        decimal payout
    }
    
    CANDLE {
        int id PK
        string asset_id FK
        string timeframe
        timestamp timestamp
        decimal open
        decimal high
        decimal low
        decimal close
        bigint volume
    }
    
    STRATEGY_PERFORMANCE_SNAPSHOT {
        int id PK
        int strategy_id FK
        date date
        int total_trades
        int wins
        int losses
        decimal win_rate
        decimal profit
        decimal max_drawdown
    }
    
    DAILY_SUMMARY {
        int id PK
        date date
        int total_users
        int total_trades
        int vip_users
        decimal total_volume
    }
```

---

## 6. Diagrama de Camadas (Layered Architecture)

```mermaid
flowchart TB
    subgraph Presentation["🎨 PRESENTATION LAYER"]
        direction TB
        Mobile["Mobile App<br/>React Native<br/>TypeScript"]
        WebSocketClient["WebSocket Client<br/>Hooks"]
        RESTClient["REST Client<br/>Axios/Fetch"]
    end

    subgraph API["🔌 API LAYER"]
        direction TB
        REST["REST Endpoints<br/>16 Routers"]
        WebSocket["WebSocket Endpoints<br/>Real-time"]
        GraphQL["GraphQL<br/>(futuro)"]
    end

    subgraph Application["⚙️ APPLICATION LAYER"]
        direction TB
        UseCases["Use Cases<br/>Services"]
        DTOs["DTOs<br/>Pydantic Schemas"]
        Validators["Validators<br/>Business Rules"]
    end

    subgraph Domain["🏛️ DOMAIN LAYER"]
        direction TB
        Entities["Entities<br/>SQLAlchemy Models"]
        ValueObjects["Value Objects<br/>Price, Amount, etc"]
        DomainServices["Domain Services<br/>Indicadores, Calculadoras"]
        RepositoryInterfaces["Repository Interfaces"]
    end

    subgraph Infrastructure["🏗️ INFRASTRUCTURE LAYER"]
        direction TB
        
        subgraph DataAccess["Data Access"]
            PostgreSQLImpl["PostgreSQL<br/>SQLAlchemy"]
            RedisImpl["Redis<br/>Cache"]
            FileStorage["File Storage<br/>Logs, CSV"]
        end
        
        subgraph ExternalServices["External Services"]
            PocketOptionAPI["PocketOption API<br/>WebSocket Client"]
            TelegramAPI["Telegram API<br/>Bot"]
        end
        
        subgraph CrossCutting["Cross-Cutting"]
            Logging["Logging<br/>Loguru"]
            Security["Security<br/>JWT, Rate Limit"]
            Caching["Caching<br/>L1 + L2"]
            Messaging["Messaging<br/>WebSocket"]
        end
    end

    Presentation --> API
    API --> Application
    Application --> Domain
    Domain --> Infrastructure

    style Presentation fill:#e1f5fe
    style API fill:#fff3e0
    style Application fill:#e8f5e9
    style Domain fill:#fce4ec
    style Infrastructure fill:#f3e5f5
```

---

## Como Usar

1. **Copie qualquer diagrama** acima (tudo entre as tags ```mermaid)
2. **Cole em:** https://mermaid.live
3. Ou use a **extensão Mermaid** no VS Code
4. Ou salve como `.md` no GitHub (renderiza automaticamente)

---

**Gerado em:** Março 2026  
**Versão:** 1.0  
**Projeto:** TunesTrade AutoTrade System
