import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { Alert } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient, LoginRequest, RegisterRequest, TokenResponse, User } from '../services/api';
import { API_CONFIG } from '../constants/api';
import { useConnection } from './ConnectionContext';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, rememberMe: boolean) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<void>;
  fetchUser: () => Promise<void>;
  checkMaintenanceLogout: () => Promise<boolean>;
  maintenanceLogout: boolean;
  setMaintenanceLogout: React.Dispatch<React.SetStateAction<boolean>>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user_data';
const REMEMBER_EMAIL_KEY = 'remember_email';
const REMEMBER_PASSWORD_KEY = 'remember_password';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [maintenanceLogout, setMaintenanceLogout] = useState(false);
  const userRef = React.useRef<User | null>(null);
  const { connectionStatus } = useConnection();

  useEffect(() => {
    loadStoredAuth();
  }, []);

  // Monitorar mudanças de conexão
  useEffect(() => {
    if (connectionStatus === 'maintenance' && userRef.current) {
      console.log('[AuthContext] Manutenção detectada, deslogando usuário...');
      logout();
      setMaintenanceLogout(true);
    }
  }, [connectionStatus]);

  // Atualizar ref quando user mudar
  useEffect(() => {
    userRef.current = user;
  }, [user]);

  const loadStoredAuth = async () => {
    try {
      const token = await AsyncStorage.getItem(TOKEN_KEY);
      const userData = await AsyncStorage.getItem(USER_KEY);

      if (token && userData) {
        console.log('[AuthContext] Token encontrado, configurando apiClient...');
        
        // Verificar se o token está expirado (decodificação manual do JWT)
        try {
          const parts = token.split('.');
          if (parts.length === 3) {
            const payload = parts[1];
            // Adicionar padding se necessário
            const padding = 4 - payload.length % 4;
            const paddedPayload = padding !== 4 ? payload + '='.repeat(padding) : payload;
            
            const decoded = atob(paddedPayload);
            const payloadData = JSON.parse(decoded);
            
            if (payloadData.exp && payloadData.exp < Date.now() / 1000) {
              console.log('[AuthContext] Token expirado, fazendo logout...');
              logout();
              return;
            }
          }
        } catch (e) {
          // Se não conseguir decodificar, assume que está válido
          console.log('[AuthContext] Não foi possível verificar expiração do token');
        }
        
        apiClient.setAccessToken(token);
        console.log('[AuthContext] Token configurado:', token.substring(0, 20) + '...');
        setUser(JSON.parse(userData));
      } else {
        console.log('[AuthContext] Nenhum token ou usuário encontrado');
      }
    } catch (error) {
      console.error('Error loading stored auth:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string, rememberMe: boolean) => {
    try {
      // Verificar status de conexão antes de permitir login
      if (connectionStatus === 'maintenance') {
        throw new Error('Sistema em manutenção. Tente novamente mais tarde.');
      }
      if (connectionStatus === 'disconnected') {
        throw new Error('Sem conexão com o servidor. Verifique sua internet.');
      }

      const response = await apiClient.login({ email, password });

      // Store tokens
      await AsyncStorage.setItem(TOKEN_KEY, response.access_token);
      await AsyncStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token);
      apiClient.setAccessToken(response.access_token);

      // Store remember me data
      if (rememberMe) {
        console.log('[AuthContext] Salvando credenciais para lembrar meus dados...');
        await AsyncStorage.setItem(REMEMBER_EMAIL_KEY, email);
        await AsyncStorage.setItem(REMEMBER_PASSWORD_KEY, password);
        console.log('[AuthContext] Credenciais salvas com sucesso');
      } else {
        console.log('[AuthContext] Removendo credenciais salvas...');
        await AsyncStorage.removeItem(REMEMBER_EMAIL_KEY);
        await AsyncStorage.removeItem(REMEMBER_PASSWORD_KEY);
        console.log('[AuthContext] Credenciais removidas com sucesso');
      }

      // Fetch full user data
      await fetchUser();
    } catch (error) {
      throw error;
    }
  };

  const register = async (name: string, email: string, password: string) => {
    try {
      const userData = await apiClient.register({ name, email, password });
      setUser(userData);
    } catch (error) {
      throw error;
    }
  };

  const logout = async () => {
    try {
      await AsyncStorage.removeItem(TOKEN_KEY);
      await AsyncStorage.removeItem(REFRESH_TOKEN_KEY);
      await AsyncStorage.removeItem(USER_KEY);
      apiClient.setAccessToken(null);
      setUser(null);
    } catch (error) {
      console.error('Error during logout:', error);
    }
  };

  const refreshToken = async () => {
    try {
      const refreshToken = await AsyncStorage.getItem(REFRESH_TOKEN_KEY);
      if (!refreshToken) {
        throw new Error('No refresh token available');
      }

      const response = await apiClient.refreshToken(refreshToken);

      await AsyncStorage.setItem(TOKEN_KEY, response.access_token);
      apiClient.setAccessToken(response.access_token);
    } catch (error) {
      await logout();
      throw error;
    }
  };

  const fetchUser = async () => {
    try {
      const userData = await apiClient.get<User>('/users/me');
      setUser(userData);
      await AsyncStorage.setItem(USER_KEY, JSON.stringify(userData));
    } catch (error) {
      console.error('Error fetching user data:', error);
    }
  };

  const checkMaintenanceLogout = async (): Promise<boolean> => {
    try {
      const userData = await apiClient.get<User>('/users/me');
      // Se o usuário tem maintenance_logout_at, significa que foi deslogado por manutenção
      if (userData.maintenance_logout_at) {
        await logout();
        return true;
      }
      return false;
    } catch (error) {
      console.error('Error checking maintenance logout:', error);
      return false;
    }
  };

  const getRememberedCredentials = async (): Promise<{ email: string; password: string } | null> => {
    try {
      console.log('[AuthContext] Carregando credenciais lembradas...');
      const email = await AsyncStorage.getItem(REMEMBER_EMAIL_KEY);
      const password = await AsyncStorage.getItem(REMEMBER_PASSWORD_KEY);

      if (email && password) {
        // Validar integridade dos dados
        if (typeof email === 'string' && email.includes('@') && typeof password === 'string' && password.length >= 8) {
          console.log('[AuthContext] Credenciais válidas encontradas:', email.substring(0, 3) + '***');
          return { email, password };
        } else {
          console.warn('[AuthContext] Credenciais inválidas encontradas, removendo...');
          await AsyncStorage.removeItem(REMEMBER_EMAIL_KEY);
          await AsyncStorage.removeItem(REMEMBER_PASSWORD_KEY);
        }
      } else {
        console.log('[AuthContext] Nenhuma credencial lembrada encontrada');
      }
      return null;
    } catch (error) {
      console.error('[AuthContext] Erro ao carregar credenciais lembradas:', error);
      return null;
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        maintenanceLogout,
        setMaintenanceLogout,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        refreshToken,
        fetchUser,
        checkMaintenanceLogout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const getRememberedCredentials = async (): Promise<{ email: string; password: string } | null> => {
  try {
    const email = await AsyncStorage.getItem(REMEMBER_EMAIL_KEY);
    const password = await AsyncStorage.getItem(REMEMBER_PASSWORD_KEY);

    if (email && password) {
      return { email, password };
    }
    return null;
  } catch (error) {
    return null;
  }
};
