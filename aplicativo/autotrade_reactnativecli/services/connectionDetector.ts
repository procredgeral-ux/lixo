import { API_CONFIG } from '../constants/api';

export interface ConnectionMethod {
  type: 'local' | 'production';
  url: string;
  reachable: boolean;
}

class ConnectionDetector {
  private localUrls: string[] = API_CONFIG.LOCAL_URLS;
  private productionUrl: string = API_CONFIG.BASE_URL;
  
  private cachedMethod: ConnectionMethod | null = null;
  private cacheExpiry: number = 0;
  private cacheDuration: number = 30000; // 30 segundos
  
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
    
    // 1. Tentar conexão local primeiro
    const localMethod = await this.testLocalConnection();
    if (localMethod.reachable) {
      console.log('[ConnectionDetector] ✓ Conexão local disponível');
      this.cachedMethod = localMethod;
      this.cacheExpiry = now;
      return localMethod;
    }
    
    // 2. Tentar conexão production (Railway)
    const productionMethod = await this.testProductionConnection();
    if (productionMethod.reachable) {
      console.log('[ConnectionDetector] ✓ Conexão production disponível');
      this.cachedMethod = productionMethod;
      this.cacheExpiry = now;
      return productionMethod;
    }
    
    // 3. Nenhum método disponível
    console.error('[ConnectionDetector] ✗ Nenhum método de conexão disponível');
    return {
      type: 'production',
      url: this.productionUrl,
      reachable: false,
    };
  }
  
  /**
   * Testa conexão local
   */
  private async testLocalConnection(): Promise<ConnectionMethod> {
    for (const url of this.localUrls) {
      try {
        console.log(`[ConnectionDetector] Testando conexão local: ${url}`);
        
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

  /**
   * Testa conexão production (Railway)
   */
  private async testProductionConnection(): Promise<ConnectionMethod> {
    try {
      console.log(`[ConnectionDetector] Testando conexão production: ${this.productionUrl}`);
      
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Timeout')), 5000)
      );
      
      const response = await Promise.race([
        fetch(`${this.productionUrl}/health`, {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
        }),
        timeoutPromise
      ]);
      
      if (response instanceof Response && response.ok) {
        console.log(`[ConnectionDetector] ✓ Conexão production funcionando: ${this.productionUrl}`);
        return {
          type: 'production',
          url: this.productionUrl,
          reachable: true,
        };
      }
    } catch (error) {
      console.log(`[ConnectionDetector] ✗ Conexão production falhou: ${this.productionUrl}`);
    }
    
    return {
      type: 'production',
      url: this.productionUrl,
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
}

export const connectionDetector = new ConnectionDetector();
