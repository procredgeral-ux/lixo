// API Configuration
export const API_CONFIG = {
  // Backend URL - Produção Railway
  BASE_URL: 'https://web-production-640f.up.railway.app', // URL fixa do Railway
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