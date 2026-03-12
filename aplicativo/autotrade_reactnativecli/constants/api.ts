import AsyncStorage from '@react-native-async-storage/async-storage';

const SERVER_URL_KEY = '@autotrade:serverUrl';

// URL padrão embutido no código
const DEFAULT_BASE_URL = '' as string;

// Função assíncrona para obter URL efetivo
export async function getEffectiveBaseUrl(): Promise<string> {
  try {
    const savedUrl = await AsyncStorage.getItem(SERVER_URL_KEY);
    if (savedUrl && savedUrl.trim() !== '') {
      return savedUrl.trim().replace(/\/$/, '');
    }
  } catch (error) {
    console.error('Erro ao obter URL do servidor:', error);
  }
  return DEFAULT_BASE_URL;
}

// Função síncrona para uso quando não pode esperar (fallback)
export function getDefaultBaseUrl(): string {
  return DEFAULT_BASE_URL;
}

// API Configuration
export const API_CONFIG = {
  // Backend URL - Railway Production
  BASE_URL: 'https://lixo-production.up.railway.app' as string,
  API_PREFIX: '/api/v1',

  // URLs locais para detecção automática (fallback)
  LOCAL_URLS: [
    'http://localhost:8000',
    'http://10.0.2.2:8000', // Android emulator
    'http://192.168.1.100:8000', // Rede local
  ] as string[],

  // Endpoints API
  ENDPOINTS: {
    HEALTH: '/health',
    AUTH: {
      LOGIN: '/auth/login',
      REGISTER: '/auth/register',
      REFRESH: '/auth/refresh',
    },
    STRATEGIES: '/strategies',
    AUTOTRADE: '/autotrade',
    ACCOUNTS: '/accounts',
    TRADES: '/trades',
    SIGNALS: '/signals',
  },
} as const;
  
// Helper function para URLs completas
export const getApiUrl = (endpoint: string): string => {
  return `${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}${endpoint}`;
};
