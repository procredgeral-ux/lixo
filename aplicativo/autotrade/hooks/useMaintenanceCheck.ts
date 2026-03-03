import { useEffect, useRef } from 'react';
import { useNavigation } from '@react-navigation/native';
import { API_CONFIG } from '../constants/api';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useMaintenanceWebSocket } from './useMaintenanceWebSocket';

// Persistir status offline
const MAINTENANCE_STATUS_KEY = 'maintenance_status';

async function loadPersistedStatus(): Promise<boolean | null> {
  try {
    const status = await AsyncStorage.getItem(MAINTENANCE_STATUS_KEY);
    return status === 'true' ? true : status === 'false' ? false : null;
  } catch {
    return null;
  }
}

async function persistStatus(status: boolean): Promise<void> {
  try {
    await AsyncStorage.setItem(MAINTENANCE_STATUS_KEY, status.toString());
  } catch {
    // Ignorar erro de persistência
  }
}

export function useMaintenanceCheck() {
  const navigation = useNavigation();
  const isMountedRef = useRef(true);
  const { isUnderMaintenance } = useMaintenanceWebSocket();

  useEffect(() => {
    // Carregar status persistido ao montar
    loadPersistedStatus().then(status => {
      if (status !== null && status && isMountedRef.current) {
        navigation.reset({
          index: 0,
          routes: [{ name: 'Maintenance' as never }],
        });
      }
    });
  }, []);

  // Monitorar mudanças no status de manutenção via WebSocket
  useEffect(() => {
    if (isUnderMaintenance && isMountedRef.current) {
      navigation.reset({
        index: 0,
        routes: [{ name: 'Maintenance' as never }],
      });
    }
  }, [isUnderMaintenance, navigation]);

  useEffect(() => {
    isMountedRef.current = false;
  }, []);
}
