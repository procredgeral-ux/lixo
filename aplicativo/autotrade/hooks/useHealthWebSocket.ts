import { useEffect, useRef, useState } from 'react';
import { API_CONFIG } from '../constants/api';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface HealthMessage {
  type: string;
  is_healthy?: boolean;
  connection_id?: string;
}

export function useHealthWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    const connectWebSocket = async () => {
      try {
        const token = await AsyncStorage.getItem('token');
        if (!token) {
          return;
        }

        const wsUrl = `${API_CONFIG.BASE_URL.replace('http', 'ws')}/ws/health?token=${token}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[HealthWebSocket] Conectado');
          setIsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const message: HealthMessage = JSON.parse(event.data);
            
            if (message.type === 'health_status' && message.is_healthy !== undefined) {
              setIsHealthy(message.is_healthy);
            }
          } catch (error) {
            console.error('[HealthWebSocket] Erro ao processar mensagem:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('[HealthWebSocket] Erro:', error);
          setIsConnected(false);
        };

        ws.onclose = () => {
          console.log('[HealthWebSocket] Desconectado');
          setIsConnected(false);
          wsRef.current = null;
          
          // Tentar reconectar após 5 segundos
          if (isMountedRef.current) {
            reconnectTimeoutRef.current = setTimeout(() => {
              connectWebSocket();
            }, 5000);
          }
        };

        wsRef.current = ws;
      } catch (error) {
        console.error('[HealthWebSocket] Erro ao conectar:', error);
      }
    };

    connectWebSocket();

    return () => {
      isMountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return { isConnected, isHealthy };
}
