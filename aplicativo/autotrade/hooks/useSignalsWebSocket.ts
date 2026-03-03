import { useEffect, useRef, useState } from 'react';
import { API_CONFIG } from '../constants/api';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface SignalMessage {
  type: string;
  signal?: any;
  connection_id?: string;
}

export function useSignalsWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [newSignal, setNewSignal] = useState<any>(null);
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

        const wsUrl = `${API_CONFIG.BASE_URL.replace('http', 'ws')}/ws/signals?token=${token}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[SignalsWebSocket] Conectado');
          setIsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const message: SignalMessage = JSON.parse(event.data);
            
            if (message.type === 'new_signal' && message.signal) {
              setNewSignal(message.signal);
            }
          } catch (error) {
            console.error('[SignalsWebSocket] Erro ao processar mensagem:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('[SignalsWebSocket] Erro:', error);
          setIsConnected(false);
        };

        ws.onclose = () => {
          console.log('[SignalsWebSocket] Desconectado');
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
        console.error('[SignalsWebSocket] Erro ao conectar:', error);
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

  return { isConnected, newSignal };
}
