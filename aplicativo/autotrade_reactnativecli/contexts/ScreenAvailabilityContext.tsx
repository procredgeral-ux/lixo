import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from '../services/api';

export interface ScreenAvailabilityState {
  dashboard: boolean;
  estrategias: boolean;
  sinais: boolean;
  historico: boolean;
  configuracoes: boolean;
}

interface ScreenAvailabilityContextType {
  screenStates: ScreenAvailabilityState;
  isScreenEnabled: (screenId: string) => boolean;
  setScreenEnabled: (screenId: string, enabled: boolean) => Promise<void>;
  setAllScreens: (states: ScreenAvailabilityState) => Promise<void>;
  refreshScreenStates: () => Promise<void>;
  isLoaded: boolean;
  isSyncing: boolean;
}

const defaultState: ScreenAvailabilityState = {
  dashboard: true,
  estrategias: true,
  sinais: true,
  historico: true,
  configuracoes: true,
};

const STORAGE_KEY = '@tunestrade_screen_availability';

const ScreenAvailabilityContext = createContext<ScreenAvailabilityContextType | undefined>(undefined);

export function ScreenAvailabilityProvider({ children }: { children: ReactNode }) {
  const [screenStates, setScreenStates] = useState<ScreenAvailabilityState>(defaultState);
  const [isLoaded, setIsLoaded] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  // Buscar estado do backend (endpoint público)
  const fetchScreenStatesFromBackend = async (): Promise<ScreenAvailabilityState | null> => {
    try {
      const response = await apiClient.get<any>('/admin/screens/availability/public');
      if (response && response.screens) {
        return response.screens as ScreenAvailabilityState;
      }
    } catch (error) {
      console.log('[ScreenAvailability] Backend não disponível, usando estado padrão');
      // Não falhar completamente, apenas usar estado padrão
    }
    return defaultState;
  };

  // Carregar estado inicial (AsyncStorage primeiro, depois backend)
  useEffect(() => {
    const loadStates = async () => {
      try {
        // Primeiro tentar carregar do AsyncStorage (cache local)
        const stored = await AsyncStorage.getItem(STORAGE_KEY);
        let initialState = defaultState;
        
        if (stored) {
          const parsed = JSON.parse(stored);
          initialState = { ...defaultState, ...parsed };
          setScreenStates(initialState);
        }
        
        setIsLoaded(true);
        
        // Depois buscar do backend e atualizar se diferente
        const backendState = await fetchScreenStatesFromBackend();
        if (backendState) {
          const hasChanges = JSON.stringify(initialState) !== JSON.stringify(backendState);
          if (hasChanges) {
            setScreenStates(backendState);
            await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(backendState));
          }
        }
      } catch (error) {
        console.error('[ScreenAvailability] Erro ao carregar estado:', error);
        setIsLoaded(true);
      }
    };
    
    loadStates();
    
    // Polling a cada 30 segundos para manter sincronizado
    const interval = setInterval(() => {
      refreshScreenStates();
    }, 30000);
    
    return () => clearInterval(interval);
  }, []);

  // Salvar no AsyncStorage quando mudar (backup local)
  useEffect(() => {
    if (isLoaded) {
      const saveStates = async () => {
        try {
          await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(screenStates));
        } catch (error) {
          console.error('[ScreenAvailability] Erro ao salvar no AsyncStorage:', error);
        }
      };
      saveStates();
    }
  }, [screenStates, isLoaded]);

  const isScreenEnabled = (screenId: string): boolean => {
    return screenStates[screenId as keyof ScreenAvailabilityState] ?? true;
  };

  // Atualizar estado de uma tela no backend e local
  const setScreenEnabled = async (screenId: string, enabled: boolean) => {
    setIsSyncing(true);
    try {
      // Atualizar backend primeiro (se falhar, não atualiza local)
      await apiClient.post('/admin/screens/availability/toggle', {
        screen_id: screenId,
        enabled: enabled,
      });
      
      // Se backend OK, atualizar estado local
      setScreenStates(prev => ({
        ...prev,
        [screenId]: enabled,
      }));
    } catch (error) {
      console.error('[ScreenAvailability] Erro ao sincronizar com backend:', error);
      throw error;
    } finally {
      setIsSyncing(false);
    }
  };

  // Atualizar todas as telas no backend e local
  const setAllScreens = async (states: ScreenAvailabilityState) => {
    setIsSyncing(true);
    try {
      // Atualizar backend primeiro
      await apiClient.post('/admin/screens/availability/update-all', states);
      
      // Se backend OK, atualizar estado local
      setScreenStates(states);
    } catch (error) {
      console.error('[ScreenAvailability] Erro ao sincronizar todas as telas:', error);
      throw error;
    } finally {
      setIsSyncing(false);
    }
  };

  // Buscar estado atual do backend
  const refreshScreenStates = async () => {
    try {
      const backendState = await fetchScreenStatesFromBackend();
      if (backendState) {
        setScreenStates(backendState);
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(backendState));
      }
    } catch (error) {
      console.error('[ScreenAvailability] Erro ao refresh:', error);
    }
  };

  return (
    <ScreenAvailabilityContext.Provider
      value={{
        screenStates,
        isScreenEnabled,
        setScreenEnabled,
        setAllScreens,
        refreshScreenStates,
        isLoaded,
        isSyncing,
      }}
    >
      {children}
    </ScreenAvailabilityContext.Provider>
  );
}

export function useScreenAvailability() {
  const context = useContext(ScreenAvailabilityContext);
  if (context === undefined) {
    throw new Error('useScreenAvailability deve ser usado dentro de ScreenAvailabilityProvider');
  }
  return context;
}
