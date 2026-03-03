import { useEffect, useRef, useState } from 'react';
import { useNavigation } from '@react-navigation/native';
import { API_CONFIG } from '../constants/api';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface MaintenanceMessage {
  type: string;
  is_under_maintenance?: boolean;
  connection_id?: string;
}

export function useMaintenanceWebSocket() {
  const navigation = useNavigation();
  const [isConnected, setIsConnected] = useState(false);
  const [isUnderMaintenance, setIsUnderMaintenance] = useState(false);
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

        const wsUrl = `${API_CONFIG.BASE_URL.replace('http', 'ws')}/ws/maintenance?token=${token}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[MaintenanceWebSocket] Conectado');
          setIsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const message: MaintenanceMessage = JSON.parse(event.data);
            
            if (message.type === 'maintenance_status' && message.is_under_maintenance !== undefined) {
              setIsUnderMaintenance(message.is_under_maintenance);
              
              if (message.is_under_maintenance && isMountedRef.current) {
                navigation.reset({
                  index: 0,
                  routes: [{ name: 'Maintenance' as never }],
                });
              }
            }
          } catch (error) {
            console.error('[MaintenanceWebSocket] Erro ao processar mensagem:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('[MaintenanceWebSocket] Erro:', error);
          setIsConnected(false);
        };

        ws.onclose = () => {
          console.log('[MaintenanceWebSocket] Desconectado');
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
        console.error('[MaintenanceWebSocket] Erro ao conectar:', error);
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
  }, [navigation]);

  return { isConnected, isUnderMaintenance };
}
