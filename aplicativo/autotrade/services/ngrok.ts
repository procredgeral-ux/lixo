import { apiClient } from './api';

export interface NgrokUrlResponse {
  url: string | null;
  message: string;
}

export interface ConnectionHealth {
  google_sheets_connected: boolean;
  ngrok_running: boolean;
  ngrok_url: string | null;
  google_sheets_url: string | null;
}

class NgrokService {
  private baseUrl: string = 'http://localhost:8000';
  private cachedUrl: string | null = null;
  private lastUpdate: number = 0;
  private cacheDuration: number = 60000; // 1 minuto em ms

  /**
   * Obtém URL do ngrok do backend (que lê do Google Sheets)
   */
  async getNgrokUrl(): Promise<string | null> {
    try {
      const response = await apiClient.get<NgrokUrlResponse>('/connection/ngrok-url');
      
      if (response.url) {
        this.cachedUrl = response.url;
        this.lastUpdate = Date.now();
        console.log('[NgrokService] URL do ngrok obtido:', response.url);
        return response.url;
      }
      
      console.log('[NgrokService] Nenhum URL do ngrok encontrado');
      return null;
    } catch (error) {
      console.error('[NgrokService] Erro ao obter URL do ngrok:', error);
      return null;
    }
  }

  /**
   * Força atualização do URL do ngrok
   */
  async updateNgrokUrl(): Promise<boolean> {
    try {
      await apiClient.post('/connection/update-ngrok-url');
      console.log('[NgrokService] URL do ngrok atualizado com sucesso');
      return true;
    } catch (error) {
      console.error('[NgrokService] Erro ao atualizar URL do ngrok:', error);
      return false;
    }
  }

  /**
   * Verifica saúde da conexão
   */
  async checkConnectionHealth(): Promise<ConnectionHealth | null> {
    try {
      const response = await apiClient.get<ConnectionHealth>('/connection/health');
      console.log('[NgrokService] Saúde da conexão:', response);
      return response;
    } catch (error) {
      console.error('[NgrokService] Erro ao verificar saúde da conexão:', error);
      return null;
    }
  }

  /**
   * Obtém URL do ngrok com cache
   */
  async getNgrokUrlWithCache(): Promise<string | null> {
    const now = Date.now();
    
    // Se tem cache válido, retorna
    if (this.cachedUrl && (now - this.lastUpdate) < this.cacheDuration) {
      console.log('[NgrokService] Usando URL em cache:', this.cachedUrl);
      return this.cachedUrl;
    }
    
    // Caso contrário, busca novo URL
    return await this.getNgrokUrl();
  }

  /**
   * Inicializa conexão automática
   */
  async initializeConnection(): Promise<string | null> {
    console.log('[NgrokService] Inicializando conexão automática...');
    
    // Verifica saúde da conexão
    const health = await this.checkConnectionHealth();
    
    if (!health) {
      console.log('[NgrokService] Não foi possível verificar saúde da conexão');
      return null;
    }
    
    console.log('[NgrokService] Status da conexão:', {
      googleSheetsConnected: health.google_sheets_connected,
      ngrokRunning: health.ngrok_running,
      ngrokUrl: health.ngrok_url
    });
    
    if (health.ngrok_url) {
      this.cachedUrl = health.ngrok_url;
      this.lastUpdate = Date.now();
      console.log('[NgrokService] URL do ngrok obtido:', health.ngrok_url);
      return health.ngrok_url;
    }
    
    console.log('[NgrokService] Nenhum URL do ngrok encontrado');
    return null;
  }

  /**
   * Limpa cache
   */
  clearCache(): void {
    this.cachedUrl = null;
    this.lastUpdate = 0;
    console.log('[NgrokService] Cache limpo');
  }
}

export const ngrokService = new NgrokService();
