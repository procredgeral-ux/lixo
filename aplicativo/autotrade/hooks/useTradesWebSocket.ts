import { useEffect, useRef, useState } from 'react';
import { API_CONFIG } from '../constants/api';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface TradeMessage {
  type: string;
  trade?: any;
  connection_id?: string;
}

export function useTradesWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [newTrade, setNewTrade] = useState<any>(null);
  const [updatedTrade, setUpdatedTrade] = useState<any>(null);
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

        const wsUrl = `${API_CONFIG.BASE_URL.replace('http', 'ws')}/ws/trades?token=${token}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[TradesWebSocket] Conectado');
          setIsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const message: TradeMessage = JSON.parse(event.data);
            
            if (message.type === 'new_trade' && message.trade) {
              setNewTrade(message.trade);
            } else if (message.type === 'trade_updated' && message.trade) {
              setUpdatedTrade(message.trade);
            }
          } catch (error) {
            console.error('[TradesWebSocket] Erro ao processar mensagem:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('[TradesWebSocket] Erro:', error);
          setIsConnected(false);
        };

        ws.onclose = () => {
          console.log('[TradesWebSocket] Desconectado');
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
        console.error('[TradesWebSocket] Erro ao conectar:', error);
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

  return { isConnected, newTrade, updatedTrade };
}
