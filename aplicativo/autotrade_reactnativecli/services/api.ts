import { API_CONFIG, getEffectiveBaseUrl } from '../constants/api';
import { connectionDetector } from './connectionDetector';
import AsyncStorage from '@react-native-async-storage/async-storage';

const SERVER_URL_KEY = '@autotrade:serverUrl';

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

export interface ConnectionHealth {
  status: string;
  database: string;
  redis?: any;
  pocketoption?: any;
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
  
  // 🛡️ Rate limiting protection
  private requestQueue: Map<string, Promise<any>> = new Map();
  private lastRequestTime: Map<string, number> = new Map();
  private readonly MIN_REQUEST_INTERVAL = 500; // ms entre requests do mesmo endpoint
  private readonly MAX_CONCURRENT_REQUESTS = 3;
  private activeRequests: number = 0;
  private requestBackoff: Map<string, number> = new Map(); // Exponential backoff per endpoint

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

  getBaseUrl(): string {
    return this.baseURL;
  }

  /**
   * Inicializa conexão - verifica URL salvo primeiro, depois BASE_URL, depois detecção automática
   */
  async initializeConnection(): Promise<void> {
    if (this.connectionInitialized) {
      return;
    }

    console.log('[apiClient] Inicializando conexão...');

    // 1. Verificar se há URL personalizado salvo no AsyncStorage
    try {
      const savedUrl = await AsyncStorage.getItem(SERVER_URL_KEY);
      if (savedUrl && savedUrl.trim() !== '') {
        this.baseURL = savedUrl.trim().replace(/\/$/, '');
        console.log('[apiClient] ✓ Usando URL personalizado salvo:', this.baseURL);
        this.connectionInitialized = true;
        return;
      }
    } catch (error) {
      console.error('[apiClient] Erro ao ler URL salvo:', error);
    }

    // 2. Se BASE_URL está configurado (produção), usar diretamente
    if (API_CONFIG.BASE_URL && API_CONFIG.BASE_URL.trim() !== '') {
      this.baseURL = API_CONFIG.BASE_URL;
      console.log('[apiClient] ✓ Usando BASE_URL fixo:', this.baseURL);
      this.connectionInitialized = true;
      return;
    }

    // 3. Fallback: detectar conexão automática (desenvolvimento)
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
    // 🛡️ RATE LIMITING: Debounce requests to same endpoint
    const now = Date.now();
    const lastTime = this.lastRequestTime.get(endpoint) || 0;
    const backoff = this.requestBackoff.get(endpoint) || 0;
    const timeSinceLastRequest = now - lastTime;
    
    // Se há um request pendente para o mesmo endpoint, retornar a Promise existente (deduplication)
    const pendingRequest = this.requestQueue.get(endpoint);
    if (pendingRequest && timeSinceLastRequest < this.MIN_REQUEST_INTERVAL) {
      console.log(`[apiClient] ⏳ Rate limiting: Reutilizando request pendente para ${endpoint}`);
      return pendingRequest as Promise<T>;
    }
    
    // Aguardar se necessário para respeitar MIN_REQUEST_INTERVAL + backoff
    const waitTime = Math.max(0, this.MIN_REQUEST_INTERVAL + backoff - timeSinceLastRequest);
    if (waitTime > 0) {
      console.log(`[apiClient] ⏳ Rate limiting: Aguardando ${waitTime}ms antes de ${endpoint}`);
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }
    
    // Limitar requests concorrentes
    while (this.activeRequests >= this.MAX_CONCURRENT_REQUESTS) {
      console.log(`[apiClient] ⏳ Rate limiting: Máximo de requests concorrentes atingido, aguardando...`);
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Garantir que a conexão foi inicializada (apenas uma vez)
    if (!this.connectionInitialized) {
      await this.initializeConnection();
    }

    const url = `${this.baseURL}${API_CONFIG.API_PREFIX}${endpoint}`;
    console.log('[apiClient] Request URL:', url);

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

    // Criar e armazenar a Promise para deduplication
    const requestPromise = this.executeRequest<T>(url, options, headers, endpoint);
    this.requestQueue.set(endpoint, requestPromise);
    this.lastRequestTime.set(endpoint, Date.now());
    this.activeRequests++;

    try {
      const result = await requestPromise;
      // Reset backoff on success
      this.requestBackoff.set(endpoint, 0);
      return result;
    } catch (error) {
      // Increase backoff on failure (exponential: 500ms, 1000ms, 2000ms, max 4000ms)
      const currentBackoff = this.requestBackoff.get(endpoint) || 0;
      const newBackoff = Math.min(currentBackoff + 500, 4000);
      this.requestBackoff.set(endpoint, newBackoff);
      console.log(`[apiClient] ⚠️ Backoff aumentado para ${endpoint}: ${newBackoff}ms`);
      throw error;
    } finally {
      this.activeRequests--;
      // Limpar da queue após um delay para permitir reuse
      setTimeout(() => {
        this.requestQueue.delete(endpoint);
      }, this.MIN_REQUEST_INTERVAL);
    }
  }
  
  private async executeRequest<T>(
    url: string,
    options: RequestInit,
    headers: Record<string, string>,
    endpoint: string
  ): Promise<T> {
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

  async getWithFallback<T>(endpoint: string, fallbackEndpoint: string): Promise<T> {
    try {
      return await this.request<T>(endpoint, { method: 'GET' });
    } catch (err) {
      console.log(`[apiClient] Falha em ${endpoint}, tentando ${fallbackEndpoint}`);
      return await this.request<T>(fallbackEndpoint, { method: 'GET' });
    }
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
