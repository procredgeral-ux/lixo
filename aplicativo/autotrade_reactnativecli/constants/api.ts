import AsyncStorage from '@react-native-async-storage/async-storage';

const SERVER_URL_KEY = '@autotrade:serverUrl';

// URL padrão embutido no código
const DEFAULT_BASE_URL = '' as string;
const DEFAULT_PORT = 8000;

// Função para garantir que a URL tenha porta
function ensurePort(url: string): string {
  if (!url) return url;
  url = url.trim().replace(/\/$/, '');
  // Verificar se já tem porta
  const hasPort = /:\d+$/.test(url);
  if (!hasPort && !url.includes('/')) {
    // Adicionar porta padrão se não tiver
    return `${url}:${DEFAULT_PORT}`;
  }
  return url;
}

// Função assíncrona para obter URL efetivo
export async function getEffectiveBaseUrl(): Promise<string> {
  try {
    const savedUrl = await AsyncStorage.getItem(SERVER_URL_KEY);
    if (savedUrl && savedUrl.trim() !== '') {
      return ensurePort(savedUrl.trim());
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
  // Backend URL - Deixe vazio para detecção automática (desenvolvimento)
  // Produção: https://lixo-production.up.railway.app
  BASE_URL: '' as string,
  API_PREFIX: '/api/v1',

  // URLs locais para detecção automática (fallback)
  LOCAL_URLS: [
    'http://10.234.170.209:8000',
  ] as string[],

  // Ngrok discovery (Google Sheets)
  // OBS: Para leitura pública funcionar, a planilha deve estar publicada/compartilhada.
  NGROK_SHEET_ID: '1Jd2Hyriq_L5g7G4jaT4bFIvkwi56JoBXuScM-BOoIbo',
  NGROK_SHEET_PUBLIC_URL:
    'https://docs.google.com/spreadsheets/d/1Jd2Hyriq_L5g7G4jaT4bFIvkwi56JoBXuScM-BOoIbo/export?format=tsv',
  // Opcional: URLs locais para buscar /connection/ngrok-url quando a detecção local estiver habilitada
  NGROK_DISCOVERY_URLS: [] as string[],

  // Simular manutenção para testes (set to true para ativar modo manutenção manual)
  SIMULATE_MAINTENANCE: false,

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
