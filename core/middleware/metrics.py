"""
Middleware para coleta de métricas de API
Rastreia latência, status codes e requisições HTTP
"""
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from loguru import logger

from services.unified_metrics import get_unified_metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware para coletar métricas de API em tempo real"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.metrics = get_unified_metrics()
    
    async def dispatch(self, request: Request, call_next):
        """Processa requisição e coleta métricas"""
        # Ignora rotas de health check
        if request.url.path in ['/health', '/api/v1/health']:
            return await call_next(request)
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Calcula latência em ms
            latency_ms = (time.time() - start_time) * 1000
            
            # Registra métricas no sistema unificado
            self.metrics.record_api_request(latency_ms, response.status_code)
            
            return response
            
        except Exception as e:
            # Calcula latência mesmo em erro
            latency_ms = (time.time() - start_time) * 1000
            
            # Registra como erro 500
            self.metrics.record_api_request(latency_ms, 500)
            
            logger.error(f"✗ [MetricsMiddleware] Erro na requisição {request.url.path}: {e}")
            raise


def setup_metrics_middleware(app: ASGIApp):
    """Configura o middleware de métricas na aplicação FastAPI"""
    app.add_middleware(MetricsMiddleware)
    logger.info("✓ [MetricsMiddleware] Middleware de métricas configurado")
