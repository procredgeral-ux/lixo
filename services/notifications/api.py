"""
API endpoints para métricas de notificações
Integração com o dashboard admin
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from core.security import get_current_superuser
from models import User
from services.notifications.telegram_v2 import telegram_service_v2
from services.notifications.queue_manager import notification_queue_manager

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/metrics")
async def get_notification_metrics(
    current_user: User = Depends(get_current_superuser),
) -> Dict[str, Any]:
    """
    Obtém métricas completas do sistema de notificações.
    
    Retorna:
    - Estado do serviço Telegram
    - Tamanho das filas (local e Redis)
    - Métricas de envio (sucesso/falha)
    - Taxa de sucesso
    - Tempo médio de resposta
    """
    try:
        # Métricas do serviço Telegram
        telegram_metrics = await telegram_service_v2.health_check()
        
        # Métricas da fila
        queue_metrics = await notification_queue_manager.get_metrics()
        
        return {
            "telegram": telegram_metrics,
            "queue": queue_metrics,
            "system_status": {
                "enabled": telegram_service_v2.enabled,
                "workers": telegram_service_v2._num_workers,
                "batch_enabled": telegram_service_v2._batch_enabled,
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao obter métricas: {str(e)}"
        )


@router.post("/reset-offline-chats")
async def reset_offline_chats(
    current_user: User = Depends(get_current_superuser),
) -> Dict[str, Any]:
    """Reseta lista de chats offline (permite retry manual)"""
    try:
        await telegram_service_v2.reset_offline_chats()
        return {"success": True, "message": "Lista de chats offline resetada"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao resetar chats: {str(e)}"
        )
