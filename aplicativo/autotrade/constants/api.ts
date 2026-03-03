// API Configuration
export const API_CONFIG = {
  // Backend URL - usar IP local por padrão (será atualizado pelo ngrok se disponível)
  BASE_URL: 'https://web-production-640f.up.railway.app',
  WS_URL: 'wss://web-production-640f.up.railway.app/ws',
  API_PREFIX: '/api/v1',

  // URLs locais para detecção automática (fallback)
  LOCAL_URLS: [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
  ] as string[],

  // Ngrok discovery (Google Sheets)
  NGROK_SHEET_ID: '1Jd2Hyriq_L5g7G4jaT4bFIvkwi56JoBXuScM-BOoIbo',
  NGROK_SHEET_PUBLIC_URL:
    'https://docs.google.com/spreadsheets/d/1Jd2Hyriq_L5g7G4jaT4bFIvkwi56JoBXuScM-BOoIbo/export?format=tsv',
  NGROK_DISCOVERY_URLS: [] as string[],

  // Simular manutenção para testes
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
  },
} as const;

// Helper function para URLs completas
export const getApiUrl = (endpoint: string): string => {
  return `${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}${endpoint}`;
};