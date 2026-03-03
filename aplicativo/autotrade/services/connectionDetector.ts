import { API_CONFIG } from '../constants/api';

export interface ConnectionMethod {
  type: 'local' | 'ngrok';
  url: string;
  reachable: boolean;
}

class ConnectionDetector {
  private localUrls: string[] = API_CONFIG.LOCAL_URLS;
  
  private cachedMethod: ConnectionMethod | null = null;
  private cacheExpiry: number = 0;
  private cacheDuration: number = 30000; // 30 segundos (reduzido para detectar mudanças mais rápido)
  
  // Variável para desabilitar detecção local (para testes)
  private localDetectionDisabled: boolean = false; // Habilitado por padrão - preferência por rede local
  
  // Verificação periódica
  private periodicCheckInterval: NodeJS.Timeout | null = null;
  private periodicCheckDuration: number = 30000; // 30 segundos

  /**
   * Invalida o cache de conexão (chamado quando há falha)
   */
  invalidateCache(): void {
    this.cachedMethod = null;
    this.cacheExpiry = 0;
    console.log('[ConnectionDetector] Cache invalidado');
  }

  /**
   * Verifica se o endpoint em cache ainda está saudável
   */
  private async verifyCachedEndpoint(url: string): Promise<boolean> {
    try {
      const timeoutPromise = new Promise<never>((_, reject) => 
        setTimeout(() => reject(new Error('Timeout')), 2000)
      );
      
      const response = await Promise.race([
        fetch(`${url}/health`, { method: 'GET' }),
        timeoutPromise
      ]);
      
      return response instanceof Response && response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Detecta automaticamente o melhor método de conexão
   */
  async detectConnectionMethod(): Promise<ConnectionMethod> {
    const now = Date.now();
    
    // Usar cache se válido E saudável
    if (this.cachedMethod && (now - this.cacheExpiry) < this.cacheDuration) {
      console.log('[ConnectionDetector] Verificando saúde do cache:', this.cachedMethod);
      
      // Verificar se o endpoint em cache ainda está saudável
      if (this.cachedMethod.reachable && await this.verifyCachedEndpoint(this.cachedMethod.url)) {
        console.log('[ConnectionDetector] ✓ Cache válido e saudável, usando:', this.cachedMethod);
        return this.cachedMethod;
      } else {
        console.log('[ConnectionDetector] ⚠️ Cache inválido ou endpoint não saudável, revalidando...');
        this.invalidateCache();
      }
    }
    
    console.log('[ConnectionDetector] Detectando método de conexão...');
    
    // 1. Tentar conexão local primeiro (se não desabilitado)
    if (!this.localDetectionDisabled) {
      const localMethod = await this.testLocalConnection();
      if (localMethod.reachable) {
        console.log('[ConnectionDetector] ✓ Conexão local disponível');
        this.cachedMethod = localMethod;
        this.cacheExpiry = now;
        return localMethod;
      }
    } else {
      console.log('[ConnectionDetector] ⚠️ Detecção local desabilitada, pulando para ngrok');
    }
    
    // 2. Tentar conexão via ngrok (Google Sheets)
    const ngrokMethod = await this.testNgrokConnection();
    if (ngrokMethod.reachable) {
      console.log('[ConnectionDetector] ✓ Conexão ngrok disponível');
      this.cachedMethod = ngrokMethod;
      this.cacheExpiry = now;
      return ngrokMethod;
    }
    
    // 3. Nenhum método disponível
    console.error('[ConnectionDetector] ✗ Nenhum método de conexão disponível');
    return {
      type: 'local',
      url: this.localUrls[0],
      reachable: false,
    };
  }
  
  /**
   * Desabilita detecção local (para testes de ngrok)
   */
  disableLocalDetection(): void {
    this.localDetectionDisabled = true;
    this.clearCache();
    console.log('[ConnectionDetector] ⚠️ Detecção local desabilitada');
  }
  
  /**
   * Habilita detecção local
   */
  enableLocalDetection(): void {
    this.localDetectionDisabled = false;
    this.clearCache();
    console.log('[ConnectionDetector] ✓ Detecção local habilitada');
  }
  
  /**
   * Testa conexão local
   */
  private async testLocalConnection(): Promise<ConnectionMethod> {
    for (const url of this.localUrls) {
      try {
        console.log(`[ConnectionDetector] Testando conexão local: ${url}`);
        
        // Usar Promise.race com setTimeout para timeout
        const timeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error('Timeout')), 3000)
        );
        
        const response = await Promise.race([
          fetch(`${url}/health`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
            },
          }),
          timeoutPromise
        ]);
        
        if (response instanceof Response && response.ok) {
          console.log(`[ConnectionDetector] ✓ Conexão local funcionando: ${url}`);
          return {
            type: 'local',
            url,
            reachable: true,
          };
        }
      } catch (error) {
        console.log(`[ConnectionDetector] ✗ Conexão local falhou: ${url}`);
        continue;
      }
    }
    
    console.log('[ConnectionDetector] ✗ Nenhuma conexão local disponível');
    return {
      type: 'local',
      url: this.localUrls[0],
      reachable: false,
    };
  }
  
  private async readNgrokUrlFromPublicSheet(): Promise<string | null> {
    if (!API_CONFIG.NGROK_SHEET_PUBLIC_URL) {
      return null;
    }

    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timeout')), 5000)
      );

      const response = await Promise.race([
        fetch(API_CONFIG.NGROK_SHEET_PUBLIC_URL, {
          method: 'GET',
          headers: {
            'Cache-Control': 'no-store',
          },
        }),
        timeoutPromise,
      ]);

      if (!(response instanceof Response) || !response.ok) {
        return null;
      }

      const text = await response.text();
      const firstCell = text.split('\n')[0]?.split('\t')[0]?.trim();

      if (!firstCell || !firstCell.startsWith('http')) {
        return null;
      }

      return firstCell.replace(/\/$/, '');
    } catch (error) {
      console.error('[ConnectionDetector] ✗ Erro ao ler Google Sheets público:', error);
      return null;
    }
  }

  private async readNgrokUrlFromDiscoveryEndpoints(): Promise<string | null> {
    const discoveryUrls = API_CONFIG.NGROK_DISCOVERY_URLS || [];
    if (discoveryUrls.length === 0) {
      return null;
    }

    for (const baseUrl of discoveryUrls) {
      try {
        const normalizedBaseUrl = baseUrl.replace(/\/$/, '');
        const timeoutPromise = new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Timeout')), 5000)
        );

        const response = await Promise.race([
          fetch(`${normalizedBaseUrl}${API_CONFIG.API_PREFIX}/connection/ngrok-url`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
            },
          }),
          timeoutPromise,
        ]);

        if (!(response instanceof Response) || !response.ok) {
          continue;
        }

        const data = await response.json();
        if (data?.url) {
          return String(data.url).replace(/\/$/, '');
        }
      } catch (error) {
        console.log('[ConnectionDetector] ✗ Falha ao consultar discovery URL:', baseUrl, error);
      }
    }

    return null;
  }

  /**
   * Testa conexão via ngrok (Google Sheets)
   */
  private async testNgrokConnection(): Promise<ConnectionMethod> {
    try {
      console.log('[ConnectionDetector] Tentando ler URL do ngrok do Google Sheets...');

      const ngrokUrl =
        (await this.readNgrokUrlFromPublicSheet()) ??
        (await this.readNgrokUrlFromDiscoveryEndpoints());

      if (!ngrokUrl) {
        console.log('[ConnectionDetector] ✗ URL do ngrok não encontrado no Google Sheets');
        return {
          type: 'ngrok',
          url: '',
          reachable: false,
        };
      }

      console.log(`[ConnectionDetector] URL do ngrok obtido: ${ngrokUrl}`);

      const timeoutTestPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timeout')), 5000)
      );

      const testResponse = await Promise.race([
        fetch(`${ngrokUrl}/health`, {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
        }),
        timeoutTestPromise,
      ]);

      if (testResponse instanceof Response && testResponse.ok) {
        console.log(`[ConnectionDetector] ✓ Conexão ngrok funcionando: ${ngrokUrl}`);
        return {
          type: 'ngrok',
          url: ngrokUrl,
          reachable: true,
        };
      }

      console.log('[ConnectionDetector] ✗ URL do ngrok não responde');
    } catch (error) {
      console.error('[ConnectionDetector] ✗ Erro ao testar conexão ngrok:', error);
    }

    return {
      type: 'ngrok',
      url: '',
      reachable: false,
    };
  }
  
  /**
   * Limpa cache
   */
  clearCache(): void {
    this.cachedMethod = null;
    this.cacheExpiry = 0;
    console.log('[ConnectionDetector] Cache limpo');
  }
  
  /**
   * Força nova detecção
   */
  async forceDetection(): Promise<ConnectionMethod> {
    this.clearCache();
    return await this.detectConnectionMethod();
  }
  
  /**
   * Inicia verificação periódica do ngrok
   */
  startPeriodicCheck(): void {
    if (this.periodicCheckInterval) {
      return; // Já está rodando
    }
    
    console.log('[ConnectionDetector] Iniciando verificação periódica do ngrok...');
    
    this.periodicCheckInterval = setInterval(async () => {
      try {
        console.log('[ConnectionDetector] Verificando ngrok...');
        
        // Tentar detectar conexão novamente
        const connectionMethod = await this.detectConnectionMethod();
        
        if (connectionMethod.reachable && connectionMethod.type === 'ngrok') {
          console.log('[ConnectionDetector] ✓ Ngrok disponível, conexão retomada!');
          this.stopPeriodicCheck();
        }
      } catch (error) {
        console.error('[ConnectionDetector] Erro na verificação periódica:', error);
      }
    }, this.periodicCheckDuration);
  }
  
  /**
   * Para verificação periódica
   */
  stopPeriodicCheck(): void {
    if (this.periodicCheckInterval) {
      clearInterval(this.periodicCheckInterval);
      this.periodicCheckInterval = null;
      console.log('[ConnectionDetector] Verificação periódica parada');
    }
  }
}

export const connectionDetector = new ConnectionDetector();
