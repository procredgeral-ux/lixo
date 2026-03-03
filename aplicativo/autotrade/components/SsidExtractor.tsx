import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  ActivityIndicator,
  Linking,
  AppState,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { WebView } from 'react-native-webview';
import { colors } from '../theme';
import ConfirmModal from './ConfirmModal';
import { apiClient } from '../services/api';

interface SsidExtractorProps {
  environment: 'real' | 'demo';
  title: string;
}

export default function SsidExtractor({ environment, title }: SsidExtractorProps) {
  const navigation = useNavigation();
  const webViewRef = useRef<WebView>(null);
  const [extractedSsid, setExtractedSsid] = useState<string>('');
  const [showInfoModal, setShowInfoModal] = useState(false);
  const [showResetModal, setShowResetModal] = useState(false);
  const [ssidStatus, setSsidStatus] = useState<string>('Aguardando...');
  const [isLoading, setIsLoading] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);
  const [webviewError, setWebviewError] = useState<string | null>(null);
  const [isReloading, setIsReloading] = useState(false);
  const [existingSsid, setExistingSsid] = useState<string | null>(null);
  const [shouldSkipInjection, setShouldSkipInjection] = useState(false);
  const [isExternalBrowserOpen, setIsExternalBrowserOpen] = useState(false);
  const [showExternalBrowserModal, setShowExternalBrowserModal] = useState(false);

  const addLog = (message: string) => {
    setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${message}`].slice(-10));
  };

  const checkExistingSsid = async () => {
    try {
      const accounts = await apiClient.get<any[]>('/accounts');
      if (accounts && accounts.length > 0) {
        const account = accounts[0];
        const existingSsidValue = environment === 'demo' ? account.ssid_demo : account.ssid_real;
        
        if (existingSsidValue && existingSsidValue.length > 10) {
          setExistingSsid(existingSsidValue);
          setShouldSkipInjection(true);
          addLog(`⚠️ SSID ${environment} já preenchido: ${existingSsidValue.substring(0, 15)}...`);
          addLog('⚠️ Injeção de JavaScript desativada');
          setSsidStatus(`SSID ${environment} já existe`);
          setIsLoading(false);
        } else {
          addLog(`✓ SSID ${environment} não preenchido, iniciando extração...`);
        }
      }
    } catch (error: any) {
      console.error('[SsidExtractor] Erro ao verificar SSID existente:', error);
      addLog('✗ Erro ao verificar SSID existente');
    }
  };

  useEffect(() => {
    addLog('Tela montada, iniciando monitoramento...');
    checkExistingSsid();

    // Monitorar retorno do browser externo
    const subscription = AppState.addEventListener('change', (nextAppState) => {
      if (nextAppState === 'active' && isExternalBrowserOpen) {
        setIsExternalBrowserOpen(false);
        setShowExternalBrowserModal(true);
        addLog('✓ App retornou ao foreground, verifique se o login foi concluído');
      }
    });

    return () => {
      subscription.remove();
    };
  }, [isExternalBrowserOpen]);

  const handleReloadWebView = () => {
    setIsReloading(true);
    setWebviewError(null);
    addLog('Recarregando WebView...');
    webViewRef.current?.reload();
    setTimeout(() => setIsReloading(false), 2000);
  };

  const handleWebviewError = (syntheticEvent: any) => {
    const { nativeEvent } = syntheticEvent;
    console.error('[WebView Error]:', nativeEvent);
    setWebviewError(nativeEvent.description || 'Erro de conexão');
    addLog(`✗ Erro WebView: ${nativeEvent.description || 'Erro desconhecido'}`);
    setIsLoading(false);
  };

  const handleWebviewHttpError = (syntheticEvent: any) => {
    const { nativeEvent } = syntheticEvent;
    console.error('[WebView HTTP Error]:', nativeEvent);
    if (nativeEvent.statusCode >= 400) {
      addLog(`✗ Erro HTTP: ${nativeEvent.statusCode}`);
    }
  };

  // ============ GOOGLE OAUTH HANDLER - BROWSER EXTERNO ============
  const isGoogleOAuthUrl = (url: string): boolean => {
    const googleDomains = [
      'accounts.google.com',
      'accounts.youtube.com',
      'accounts.google.co',
      'google.com/signin',
      'google.com/o/oauth2',
      'oauth.google.com',
    ];
    return googleDomains.some(domain => url.includes(domain));
  };

  const handleOpenExternalBrowser = async (url: string) => {
    try {
      addLog('🔐 Detectado login Google, abrindo browser seguro...');
      setIsExternalBrowserOpen(true);
      
      const supported = await Linking.canOpenURL(url);
      if (supported) {
        await Linking.openURL(url);
      } else {
        addLog('✗ Não foi possível abrir o browser externo');
        Alert.alert(
          'Erro',
          'Não foi possível abrir o navegador para login Google. Tente fazer login com email/senha.'
        );
      }
    } catch (error) {
      console.error('[SsidExtractor] Erro ao abrir browser externo:', error);
      addLog('✗ Erro ao abrir browser externo');
      setIsExternalBrowserOpen(false);
    }
  };

  const handleNavigationStateChange = (navState: any) => {
    const { url, navigationType } = navState;
    
    // Detectar URLs de login Google OAuth
    if (isGoogleOAuthUrl(url)) {
      addLog(`🔐 URL Google detectada: ${url.substring(0, 50)}...`);
      
      // Abrir em browser externo
      handleOpenExternalBrowser(url);
      
      // Voltar para a página anterior no WebView
      webViewRef.current?.goBack();
      return false;
    }
    
    return true;
  };

  const handleExternalBrowserReturn = () => {
    setShowExternalBrowserModal(false);
    addLog('🔄 Recarregando WebView após login externo...');
    
    // Recarregar o WebView para capturar a sessão autenticada
    handleReloadWebView();
  };

  const injectedJavaScript = `
(function() {
  // Definir environment globalmente
  window.SSID_ENVIRONMENT = '${environment}';
  
  // URLs de destino permitidas
  const TARGET_URLS = {
    demo: 'https://pocketoption.com/pt/cabinet/demo-quick-high-low/',
    real: 'https://pocketoption.com/pt/cabinet/quick-high-low/USD/'
  };
  
  // Confirmar que o script foi injetado
  window.ReactNativeWebView.postMessage(JSON.stringify({
    type: 'INIT',
    message: 'Monitoramento iniciado'
  }));

  // ============ INTERCEPTAR WEBSOCKET ============
  const originalWebSocket = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    const ws = new originalWebSocket(url, protocols);
    const originalSend = ws.send.bind(ws);

    // Interceptar dados enviados
    ws.send = function(data) {
      // Verificar se é mensagem de autenticação sendo enviada
      if (typeof data === 'string' && data.startsWith('42') && data.includes('[')) {
        try {
          const jsonPart = data.substring(2);
          const parsedData = JSON.parse(jsonPart);
          
          if (Array.isArray(parsedData) && parsedData.length >= 2) {
            const eventName = parsedData[0];
            const eventData = parsedData[1];
            
            // Capturar mensagem auth sendo enviada - verificar isDemo para demo
            if (eventName === 'auth' && eventData && typeof eventData === 'object') {
              const isDemo = eventData.isDemo;
              const env = window.SSID_ENVIRONMENT;
              
              // Para demo: capturar apenas se isDemo === 1
              if (env === 'demo' && isDemo === 1) {
                window.ReactNativeWebView.postMessage(JSON.stringify({
                  type: 'SSID_FOUND',
                  ssid: data
                }));
              }
              // Para real: capturar se isDemo === 0 ou undefined
              else if (env === 'real' && (isDemo === 0 || isDemo === undefined)) {
                window.ReactNativeWebView.postMessage(JSON.stringify({
                  type: 'SSID_FOUND',
                  ssid: data
                }));
              }
            }
          }
        } catch(e) {
          // Ignorar erros de parsing
        }
      }
      
      return originalSend(data);
    };

    // Interceptar dados recebidos
    ws.addEventListener('message', function(event) {
      try {
        const rawData = event.data;
        console.log('[SSID Extractor] WS Message bruto:', rawData.substring(0, 150));
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'LOG',
          message: 'WS Raw: ' + rawData.substring(0, 60)
        }));

        // ============ FORMATO Socket.io: 42[...] - AUTH EVENT ============
        if (rawData.startsWith('42') && rawData.includes('[')) {
          const jsonPart = rawData.substring(2);
          try {
            const data = JSON.parse(jsonPart);
            console.log('[SSID Extractor] Evento Socket.io:', JSON.stringify(data).substring(0, 200));
            window.ReactNativeWebView.postMessage(JSON.stringify({
              type: 'LOG',
              message: 'Socket.io Event: ' + (Array.isArray(data) ? data[0] : 'unknown')
            }));

            if (Array.isArray(data) && data.length >= 2) {
              const eventName = data[0];
              const eventData = data[1];

              // Verificar se é mensagem de autenticação
              if (eventName === 'auth' || eventName === 'authenticate' || eventName === 'authorized') {
                console.log('[SSID Extractor] Auth event detectado!');
                window.ReactNativeWebView.postMessage(JSON.stringify({
                  type: 'LOG',
                  message: 'Auth event recebido'
                }));

                // Extrair session do objeto auth
                if (eventData && typeof eventData === 'object') {
                  const session = eventData.session;
                  const isDemo = eventData.isDemo;
                  const uid = eventData.uid;

                  if (session && typeof session === 'string') {
                    console.log('[SSID Extractor] Session encontrada:', session.substring(0, 30) + '...');
                    window.ReactNativeWebView.postMessage(JSON.stringify({
                      type: 'SSID_FOUND',
                      ssid: session,
                      isDemo: isDemo,
                      uid: uid
                    }));
                    return;
                  }
                }
              }
            }
          } catch (e2) {
            console.error('[SSID Extractor] Erro parsing auth event:', e2);
          }
        }
        // ============ FORMATO Socket.io: 0{...} - HANDSHAKE ============
        else if (rawData.startsWith('0') && rawData.includes('{')) {
          const jsonPart = rawData.substring(1);
          try {
            const data = JSON.parse(jsonPart);
            console.log('[SSID Extractor] Handshake Socket.io:', JSON.stringify(data).substring(0, 200));
            window.ReactNativeWebView.postMessage(JSON.stringify({
              type: 'LOG',
              message: 'Socket.io Handshake'
            }));
          } catch (e2) {
            console.error('[SSID Extractor] Erro parsing handshake:', e2);
          }
        }
        // ============ TENTAR PARSEAR COMO JSON PURO ============
        else {
          try {
            const data = JSON.parse(rawData);
            console.log('[SSID Extractor] JSON parseado:', JSON.stringify(data).substring(0, 200));
            extractSessionData(data);
          } catch (e) {
            // Não é JSON válido
          }
        }
      } catch (e) {
        console.error('[SSID Extractor] Erro ao processar WS:', e);
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'LOG',
          message: 'WS Error: ' + e.message
        }));
      }
    });

    ws.addEventListener('open', function() {
      console.log('[SSID Extractor] WebSocket aberto');
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'LOG',
        message: 'WebSocket aberto'
      }));
    });

    ws.addEventListener('close', function() {
      console.log('[SSID Extractor] WebSocket fechado');
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'LOG',
        message: 'WebSocket fechado'
      }));
    });

    ws.addEventListener('error', function(event) {
      console.error('[SSID Extractor] WebSocket erro:', event);
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'LOG',
        message: 'WebSocket erro'
      }));
    });

    return ws;
  };

  // ============ INTERCEPTAR FETCH PARA CAPTURAR SESSION EM HEADERS ============
  const originalFetch = window.fetch;
  window.fetch = function(...args) {
    const url = args[0];
    console.log('[SSID Extractor] Fetch:', url);
    
    return originalFetch.apply(this, args).then(response => {
      // Verificar headers da resposta
      const authHeader = response.headers.get('authorization');
      const sessionHeader = response.headers.get('x-session');
      const ssidHeader = response.headers.get('x-ssid');
      
      if (authHeader && authHeader.length > 10) {
        console.log('[SSID Extractor] Auth header encontrado:', authHeader.substring(0, 30));
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'SSID_FOUND',
          ssid: authHeader
        }));
      }
      
      if (sessionHeader && sessionHeader.length > 10) {
        console.log('[SSID Extractor] Session header encontrado:', sessionHeader.substring(0, 30));
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'SSID_FOUND',
          ssid: sessionHeader
        }));
      }
      
      if (ssidHeader && ssidHeader.length > 10) {
        console.log('[SSID Extractor] SSID header encontrado:', ssidHeader.substring(0, 30));
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'SSID_FOUND',
          ssid: ssidHeader
        }));
      }
      
      const clonedResponse = response.clone();
      clonedResponse.text().then(text => {
        console.log('[SSID Extractor] Fetch response:', text.substring(0, 500));
        try {
          window.ReactNativeWebView.postMessage(JSON.stringify({
            type: 'LOG',
            message: 'FETCH ' + url + ': ' + text.substring(0, 500)
          }));
          
          // Tentar extrair session do corpo da resposta
          try {
            const data = JSON.parse(text);
            extractSessionData(data);
          } catch(e) {}
        } catch(err) {}
      });
      return response;
    });
  };

  // ============ INTERCEPTAR XMLHttpRequest ============
  const originalXHR = window.XMLHttpRequest;
  window.XMLHttpRequest = function() {
    const xhr = new originalXHR();
    const originalOpen = xhr.open;
    const originalSend = xhr.send.bind(xhr);
    
    xhr.open = function(method, url) {
      console.log('[SSID Extractor] XHR:', method, url);
      xhr._url = url;
      return originalOpen.apply(xhr, arguments);
    };
    
    xhr.addEventListener('load', function() {
      if (xhr._url) {
        console.log('[SSID Extractor] XHR response:', xhr.responseText.substring(0, 500));
        try {
          window.ReactNativeWebView.postMessage(JSON.stringify({
            type: 'LOG',
            message: 'XHR ' + xhr._url + ': ' + xhr.responseText.substring(0, 500)
          }));
          
          // Verificar se o corpo da resposta contém o formato completo PHP serialized
          if (xhr.responseText.includes('session_id') && xhr.responseText.includes('ip_address')) {
            console.log('[SSID Extractor] PHP serialized detectado na resposta!');
            window.ReactNativeWebView.postMessage(JSON.stringify({
              type: 'SSID_FOUND',
              ssid: xhr.responseText
            }));
          }
          
          // Tentar extrair session do corpo da resposta
          try {
            const data = JSON.parse(xhr.responseText);
            extractSessionData(data);
          } catch(e) {}
        } catch(err) {}
      }
    });
    
    return xhr;
  };

  // ============ FUNÇÃO PARA EXTRAIR DADOS DE SESSÃO (FALLBACK) ============
  function extractSessionData(obj) {
    if (!obj || typeof obj !== 'object') return;

    const sessionKeys = [
      'ssid', 'session_id', 'sessionid', 'sid', 'session', 'auth_token', 'token',
      'access_token', 'token_value', 'auth_token_value', 'user_session',
      'user_id', 'userId', 'user_sid', 'connection_id', 'connectionId',
      'account_id', 'accountId', 'trading_id', 'tradingId'
    ];

    function searchKeys(obj, depth = 0) {
      if (depth > 5 || !obj || typeof obj !== 'object') return;

      for (const key of sessionKeys) {
        if (obj[key]) {
          const value = obj[key];
          if (typeof value === 'string' && value.length > 10 && value.length < 500) {
            console.log('[SSID Extractor] Encontrado em', key, ':', value.substring(0, 20) + '...');
            window.ReactNativeWebView.postMessage(JSON.stringify({
              type: 'LOG',
              message: 'Chave: ' + key + ' = ' + value.substring(0, 30) + '...'
            }));
            sendSSID(value);
            return;
          } else if (typeof value === 'object') {
            searchKeys(value, depth + 1);
          }
        }
      }

      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          const value = obj[key];
          if (typeof value === 'string' && value.length > 16 && value.length < 500) {
            if (/^[a-zA-Z0-9\-_\.\+\/=:;]+$/.test(value) && 
                (key.toLowerCase().includes('id') || 
                 key.toLowerCase().includes('token') || 
                 key.toLowerCase().includes('session'))) {
              console.log('[SSID Extractor] Possível sessão em', key, ':', value.substring(0, 20) + '...');
              window.ReactNativeWebView.postMessage(JSON.stringify({
                type: 'LOG',
                message: 'Possível: ' + key + ' = ' + value.substring(0, 30)
              }));
              sendSSID(value);
              return;
            }
          } else if (typeof value === 'object' && value !== null) {
            searchKeys(value, depth + 1);
          }
        }
      }
    }

    searchKeys(obj);
  }

  // ============ FUNÇÃO PARA DECODIFICAR SESSION DE COOKIE CI_SESSION ============
  function decodeCiSession(encoded) {
    try {
      // Decodificar URL encoding
      const decoded = decodeURIComponent(encoded);
      console.log('[SSID Extractor] ci_session decodificado:', decoded.substring(0, 100));
      
      // Extrair session_id do formato PHP serialized
      const match = decoded.match(/s:10:"session_id";s:32:"([a-zA-Z0-9]+)"/);
      if (match && match[1]) {
        console.log('[SSID Extractor] Session extraída do ci_session:', match[1]);
        return match[1];
      }
      
      return null;
    } catch (e) {
      console.error('[SSID Extractor] Erro ao decodificar ci_session:', e);
      return null;
    }
  }

  // ============ ENVIAR SSID ENCONTRADO ============
  function sendSSID(ssid) {
    if (!ssid || typeof ssid !== 'string' || ssid.length < 10) {
      return;
    }

    console.log('[SSID Extractor] Enviando SSID:', ssid.substring(0, 20) + '...');
    window.ReactNativeWebView.postMessage(JSON.stringify({
      type: 'SSID_FOUND',
      ssid: ssid
    }));
  }

  // Log initial data
  setTimeout(() => {
    console.log('[SSID Extractor] Verificando localStorage...');
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      const value = localStorage.getItem(key);
      console.log('[SSID Extractor] localStorage', key, value);
      try {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'LOG',
          message: 'STORAGE ' + key + ': ' + value
        }));
      } catch(err) {}
    }
    
    console.log('[SSID Extractor] Verificando cookies...');
    console.log('[SSID Extractor] Cookies:', document.cookie);
    try {
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'LOG',
        message: 'COOKIES: ' + document.cookie
      }));
    } catch(err) {}
    
    // Tentar encontrar session no localStorage
    const sessionKeys = ['ssid', 'session_id', 'sessionid', 'sid', 'session', 'auth_token', 'token'];
    for (const key of sessionKeys) {
      const value = localStorage.getItem(key);
      if (value && value.length > 10 && value.length < 500) {
        console.log('[SSID Extractor] Session encontrada em localStorage:', key, value);
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'SSID_FOUND',
          ssid: value
        }));
        return;
      }
    }
    
    // Tentar encontrar session em cookies
    const cookies = document.cookie.split(';');
    for (const cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      if (sessionKeys.includes(name) && value && value.length > 10 && value.length < 500) {
        console.log('[SSID Extractor] Session encontrada em cookies:', name, value);
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'SSID_FOUND',
          ssid: value
        }));
        return;
      }
    }
    
    // Tentar verificar se há algum objeto global com session
    if (window.PocketOption && window.PocketOption.session) {
      console.log('[SSID Extractor] Session encontrada em PocketOption.session:', window.PocketOption.session);
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'SSID_FOUND',
        ssid: window.PocketOption.session
      }));
    }
  }, 2000);
})();
`;

  const handleWebViewMessage = useCallback((event: any) => {
    try {
      const message = event.nativeEvent.data;
      console.log('[SsidExtractor] Mensagem recebida:', message);
      
      const data = JSON.parse(message);

      if (data.type === 'INIT') {
        addLog('✓ Monitoramento iniciado');
        setSsidStatus('Monitorando WebSocket...');
        setIsLoading(false);
      } else if (data.type === 'LOG') {
        addLog(data.message);
        setSsidStatus(data.message);
      } else if (data.type === 'SSID_FOUND' && data.ssid) {
        const ssid = data.ssid.trim();
        if (ssid.length > 10) {
          console.log('[SsidExtractor] SSID encontrado!:', ssid.substring(0, 20));
          addLog('✓ SSID encontrado!');
          setSsidStatus('SSID encontrado: ' + ssid.substring(0, 15) + '...');
          
          if (!extractedSsid) {
            setExtractedSsid(ssid);
          }
        }
      } else if (data.type === 'RESET_COMPLETE') {
        addLog('✓ Reset completo recebido do WebView');
      }
    } catch (e) {
      console.error('[SsidExtractor] Erro ao processar mensagem:', e);
      addLog('✗ Erro ao processar');
    }
  }, [extractedSsid]);

  const handleSaveSsid = async () => {
    try {
      const field = environment === 'demo' ? 'ssid_demo' : 'ssid_real';
      
      // Primeiro buscar as accounts do usuário
      const accounts = await apiClient.get<any[]>('/accounts');
      
      if (!accounts || accounts.length === 0) {
        addLog('✗ Nenhuma conta encontrada');
        return;
      }
      
      // Usar a primeira account encontrada
      const accountId = accounts[0].id;
      const payload = { [field]: extractedSsid };
      
      await apiClient.put(`/accounts/${accountId}`, payload);
      
      addLog(`✓ SSID salvo em ${field}`);
      
      // Redirecionar para a tela de cadastro de SSIDs
      navigation.navigate('SsidRegistration' as never);
    } catch (error: any) {
      addLog(`✗ Erro ao salvar: ${error.message}`);
    }
  };

  const handleResetBrowser = () => {
    setShowResetModal(true);
  };

  const handleConfirmReset = () => {
    addLog('⚠️ Iniciando reset do navegador...');
    
    // Navegar para URL de logout primeiro
    if (webViewRef.current) {
      const logoutUrl = getLogoutUrl();
      const targetUrl = getNavigationUrl();
      
      addLog(`⏳ Navegando para logout: ${logoutUrl}`);
      
      // Primeiro navegar para logout
      webViewRef.current?.injectJavaScript(`window.location.href = '${logoutUrl}';`);
      
      // Aguardar 3 segundos e navegar para URL alvo
      setTimeout(() => {
        setIsReloading(true);
        addLog(`⏳ Navegando para URL alvo: ${targetUrl}`);
        webViewRef.current?.injectJavaScript(`window.location.href = '${targetUrl}';`);
        setTimeout(() => setIsReloading(false), 3000);
      }, 3000);
    } else {
      addLog('✗ WebView não disponível para reset');
    }
    
    setShowResetModal(false);
  };

  const getNavigationUrl = () => {
    if (environment === 'demo') {
      return 'https://pocketoption.com/pt/cabinet/demo-quick-high-low/';
    }
    return 'https://pocketoption.com/pt/cabinet/quick-high-low/USD/';
  };

  const getLogoutUrl = () => {
    return 'https://pocketoption.com/pt/logout';
  };

  const resetSsid = async () => {
    try {
      const accounts = await apiClient.get<any[]>('/accounts');
      if (!accounts || accounts.length === 0) {
        addLog('✗ Nenhuma conta encontrada');
        return;
      }

      const accountId = accounts[0].id;
      const field = environment === 'demo' ? 'ssid_demo' : 'ssid_real';
      
      await apiClient.put(`/accounts/${accountId}`, { [field]: null });
      
      addLog(`✓ SSID ${field} resetado`);
      setExistingSsid(null);
      setShouldSkipInjection(false);
      setIsLoading(true);
      addLog('✓ Iniciando extração de novo SSID...');
      
      // Recarregar o WebView para começar a extração
      setTimeout(() => {
        checkExistingSsid();
      }, 1000);
    } catch (error: any) {
      addLog(`✗ Erro ao resetar SSID: ${error.message}`);
    }
  };

  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea} edges={['top']}>
        <View style={styles.header}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={() => navigation.goBack()}
          >
            <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>{title}</Text>
          <TouchableOpacity
            style={styles.infoButton}
            onPress={() => setShowInfoModal(true)}
          >
            <Ionicons name="information-circle-outline" size={24} color="#FFFFFF" />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.resetButton}
            onPress={handleResetBrowser}
          >
            <Ionicons name="trash-outline" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        </View>
      </SafeAreaView>

      <View style={styles.contentContainer}>
        {extractedSsid ? (
          <ScrollView style={styles.scrollView}>
            <View style={styles.successContainer}>
              <View style={styles.successIconContainer}>
                <Ionicons name="checkmark-circle" size={64} color="#4CAF50" />
              </View>
              <Text style={styles.successTitle}>SSID Encontrado!</Text>
              <Text style={styles.successSubtitle}>
                O SSID foi extraído com sucesso ({environment === 'demo' ? 'Conta Demo' : 'Conta Real'})
              </Text>

              <View style={[styles.environmentBadge, { backgroundColor: environment === 'demo' ? '#FF9800' : '#4CAF50' }]}>
                <Ionicons
                  name={environment === 'demo' ? 'beaker-outline' : 'server-outline'}
                  size={16}
                  color="#FFFFFF"
                />
                <Text style={styles.environmentBadgeText}>
                  {environment === 'demo' ? 'Conta Demo' : 'Conta Real'}
                </Text>
              </View>

              <View style={styles.ssidCard}>
                <Text style={styles.ssidLabel}>SSID Extraído:</Text>
                <Text style={styles.ssidValue} selectable={true}>
                  {extractedSsid}
                </Text>
              </View>

              <TouchableOpacity style={styles.copyButton} onPress={handleSaveSsid}>
                <Ionicons name="save-outline" size={20} color="#FFFFFF" />
                <Text style={styles.copyButtonText}>Salvar SSID</Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
        ) : (
          <View style={styles.webviewContainer}>
            {webviewError && (
              <View style={styles.errorOverlay}>
                <Ionicons name="warning" size={48} color="#FF5252" />
                <Text style={styles.errorTitle}>Erro de Conexão</Text>
                <Text style={styles.errorMessage}>{webviewError}</Text>
                <TouchableOpacity
                  style={styles.retryButton}
                  onPress={handleReloadWebView}
                  disabled={isReloading}
                >
                  {isReloading ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <>
                      <Ionicons name="refresh" size={20} color="#FFFFFF" />
                      <Text style={styles.retryButtonText}>Tentar Novamente</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            )}
            {isLoading && !webviewError && (
              <View style={styles.loadingOverlay}>
                <ActivityIndicator size="large" color={colors.primary} />
                <Text style={styles.loadingText}>Carregando...</Text>
              </View>
            )}
            <WebView
              ref={webViewRef}
              source={{ uri: environment === 'demo' ? 'https://pocketoption.com/pt/cabinet/demo-quick-high-low/' : 'https://pocketoption.com/pt/cabinet/quick-high-low/USD/' }}
              style={styles.webview}
              injectedJavaScriptBeforeContentLoaded={shouldSkipInjection ? '' : injectedJavaScript}
              injectedJavaScript={shouldSkipInjection ? '' : injectedJavaScript}
              onMessage={handleWebViewMessage}
              onNavigationStateChange={handleNavigationStateChange}
              javaScriptEnabled={true}
              domStorageEnabled={true}
              startInLoadingState={true}
              scalesPageToFit={true}
              mixedContentMode="compatibility"
              onLoad={() => {
                setIsLoading(false);
                setWebviewError(null);
                addLog('✓ WebView carregado com sucesso');
              }}
              onError={handleWebviewError}
              onHttpError={handleWebviewHttpError}
              allowsBackForwardNavigationGestures={true}
              cacheEnabled={true}
              incognito={false}
            />
          </View>
        )}
      </View>

      <View style={styles.footer}>
        <View style={styles.logContainerMain}>
          <ScrollView style={styles.logScroll} nestedScrollEnabled={true}>
            {logs.map((log, index) => (
              <Text key={index} style={styles.logLine}>
                {log}
              </Text>
            ))}
          </ScrollView>
        </View>

        <SafeAreaView style={styles.footerSafeArea} edges={['bottom']}>
          <View style={styles.footerContent}>
            <Ionicons name="shield-checkmark-outline" size={16} color={colors.textMuted} />
            <Text style={styles.footerText}>
              Conexão segura • Monitorando WebSocket
            </Text>
          </View>
        </SafeAreaView>
      </View>

      <ConfirmModal
        visible={showInfoModal}
        title="Como funciona?"
        message="Esta tela monitora automaticamente as comunicações com a Pocket Option. Após fazer login, o SSID será detectado através de mensagens WebSocket (42 - Auth Event). O SSID será extraído automaticamente quando encontrado e direcionará você para o Trading."
        confirmText="Entendi"
        type="info"
        onConfirm={() => setShowInfoModal(false)}
        onCancel={() => setShowInfoModal(false)}
      />
      <ConfirmModal
        visible={showResetModal}
        title="Resetar Navegador"
        message="Isso irá limpar todos os cookies e dados de sessão do navegador, permitindo que você faça login com uma conta diferente. Deseja continuar?"
        confirmText="Confirmar"
        cancelText="Cancelar"
        type="warning"
        onConfirm={handleConfirmReset}
        onCancel={() => setShowResetModal(false)}
      />
      <ConfirmModal
        visible={showExternalBrowserModal}
        title="Login Google Concluído?"
        message="Você foi redirecionado para o navegador externo para fazer login com Google. Após concluir o login no navegador, volte para este app e toque em 'Já fiz login' para continuar."
        confirmText="Já fiz login"
        cancelText="Cancelar"
        type="info"
        onConfirm={handleExternalBrowserReturn}
        onCancel={() => setShowExternalBrowserModal(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safeArea: {
    backgroundColor: colors.surface,
  },
  contentContainer: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    flex: 1,
    textAlign: 'center',
    marginLeft: 8,
  },
  infoButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
  },
  resetButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
  },
  webviewContainer: {
    flex: 1,
    position: 'relative',
  },
  webview: {
    flex: 1,
  },
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 999,
  },
  loadingText: {
    marginTop: 12,
    fontSize: 14,
    color: colors.text,
  },
  errorOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.9)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
    padding: 20,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFFFFF',
    marginTop: 16,
    marginBottom: 8,
  },
  errorMessage: {
    fontSize: 14,
    color: '#FF5252',
    textAlign: 'center',
    marginBottom: 24,
  },
  retryButton: {
    flexDirection: 'row',
    backgroundColor: '#FF5252',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 200,
  },
  retryButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 8,
  },
  successContainer: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
  },
  successIconContainer: {
    alignItems: 'center',
    marginBottom: 24,
  },
  successTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 8,
  },
  successSubtitle: {
    fontSize: 16,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 32,
  },
  environmentBadge: {
    flexDirection: 'row',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    alignSelf: 'center',
    marginBottom: 24,
    alignItems: 'center',
  },
  environmentBadgeText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 14,
    marginLeft: 8,
  },
  ssidCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  ssidLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textMuted,
    marginBottom: 8,
  },
  ssidValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primary,
    fontFamily: 'monospace',
  },
  copyButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  copyButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 8,
  },
  useButton: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  useButtonText: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 8,
  },
  footer: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    maxHeight: 150,
  },
  footerSafeArea: {
    backgroundColor: colors.surface,
  },
  footerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  footerText: {
    fontSize: 12,
    color: colors.textMuted,
    marginLeft: 8,
  },
  logContainerMain: {
    backgroundColor: '#1a1a1a',
    maxHeight: 120,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  logScroll: {
    flex: 1,
  },
  logLine: {
    fontSize: 10,
    color: '#00FF00',
    fontFamily: 'monospace',
    paddingVertical: 2,
  },
  existingSsidContainer: {
    padding: 24,
    alignItems: 'center',
  },
  existingSsidIconContainer: {
    marginBottom: 16,
  },
  existingSsidTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
    textAlign: 'center',
  },
  existingSsidSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 24,
  },
  resetButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  skipInjectionContainer: {
    padding: 24,
    alignItems: 'center',
  },
  skipInjectionIconContainer: {
    marginBottom: 16,
  },
  skipInjectionTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
    textAlign: 'center',
  },
  skipInjectionSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 24,
  },
  continueButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  continueButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 8,
  },
});
