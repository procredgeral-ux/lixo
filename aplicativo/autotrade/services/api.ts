import { API_CONFIG } from '../constants/api';
import { connectionDetector } from './connectionDetector';

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  name: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  telegram_chat_id?: string;
  telegram_username?: string;
  is_active: boolean;
  is_superuser: boolean;
  maintenance_logout_at?: string;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  user: User;
  tokens: TokenResponse;
}

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

export interface IndicatorCombinationRanking {
  combination: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_profit: number;
  avg_profit: number;
}

export interface IndicatorRankingsResponse {
  rankings: IndicatorCombinationRanking[];
  total_combinations: number;
}

class ApiClient {
  private baseURL: string;
  private accessToken: string | null = null;
  private connectionInitialized: boolean = false;

  constructor() {
    this.baseURL = API_CONFIG.BASE_URL;
    this.accessToken = null;
  }

  setAccessToken(token: string | null) {
    this.accessToken = token;
  }

  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Inicializa conexão - usa BASE_URL diretamente se configurado
   */
  async initializeConnection(): Promise<void> {
    if (this.connectionInitialized) {
      return;
    }

    console.log('[apiClient] Inicializando conexão...');

    // Se BASE_URL está configurado (produção), usar diretamente
    if (API_CONFIG.BASE_URL && API_CONFIG.BASE_URL.trim() !== '') {
      this.baseURL = API_CONFIG.BASE_URL;
      console.log('[apiClient] ✓ Usando BASE_URL fixo:', this.baseURL);
      this.connectionInitialized = true;
      return;
    }

    // Fallback: detectar conexão automática (desenvolvimento)
    try {
      const connectionMethod = await connectionDetector.detectConnectionMethod();

      if (connectionMethod.reachable && connectionMethod.url) {
        this.baseURL = connectionMethod.url;
        console.log('[apiClient] ✓ Conexão estabelecida via:', connectionMethod.type);
        console.log('[apiClient] URL:', connectionMethod.url);
      } else {
        console.error('[apiClient] ✗ Nenhum método de conexão disponível');
        this.baseURL = 'http://localhost:8000';
      }
    } catch (error) {
      console.error('[apiClient] Erro ao inicializar conexão:', error);
      this.baseURL = 'http://localhost:8000';
    }

    this.connectionInitialized = true;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    // Garantir que a conexão foi inicializada (apenas uma vez)
    if (!this.connectionInitialized) {
      await this.initializeConnection();
    }

    const url = `${this.baseURL}${API_CONFIG.API_PREFIX}${endpoint}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
      console.log('[apiClient] Token configurado, enviando Authorization header');
    } else {
      console.log('[apiClient] Token NÃO configurado!');
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
      });

      // Handle 204 No Content (no body to parse)
      if (response.status === 204) {
        return undefined as T;
      }

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.error?.message || 'Request failed');
      }

      return data;
    } catch (error) {
      // Invalidar cache em caso de falha de conexão para forçar nova detecção
      if (error instanceof Error && (error.message.includes('network') || error.message.includes('fetch') || error.message.includes('ECONNREFUSED'))) {
        console.log('[apiClient] Falha de conexão detectada, invalidando cache...');
        connectionDetector.invalidateCache();
      }
      
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('An unknown error occurred');
    }
  }

  async login(credentials: LoginRequest): Promise<TokenResponse> {
    return this.request<TokenResponse>(API_CONFIG.ENDPOINTS.AUTH.LOGIN, {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
  }

  async register(userData: RegisterRequest): Promise<User> {
    return this.request<User>(API_CONFIG.ENDPOINTS.AUTH.REGISTER, {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  }

  async refreshToken(refreshToken: string): Promise<TokenResponse> {
    return this.request<TokenResponse>(API_CONFIG.ENDPOINTS.AUTH.REFRESH, {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  }

  async healthCheck(): Promise<{ status: string }> {
    return this.request<{ status: string }>(API_CONFIG.ENDPOINTS.HEALTH);
  }

  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'GET',
    });
  }

  async post<T>(endpoint: string, body: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async put<T>(endpoint: string, body: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'DELETE',
    });
  }
}

export const apiClient = new ApiClient();
