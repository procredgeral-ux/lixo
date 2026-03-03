import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Animated, TouchableOpacity, Alert } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { API_CONFIG } from '../constants/api';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';
import { useAuth } from '../contexts/AuthContext';

interface MaintenanceStatus {
  is_under_maintenance: boolean;
  last_checked_at: string | null;
}

export default function MaintenanceScreen() {
  const insets = useSafeAreaInsets();
  const navigation = useNavigation();
  const { user } = useAuth();
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fadeAnim = useState(new Animated.Value(0))[0];
  const [previousRoute, setPreviousRoute] = useState<string | null>(null);
  const [maintenanceEnded, setMaintenanceEnded] = useState(false);
  const [notified, setNotified] = useState(false);

  useEffect(() => {
    // Salvar a rota anterior ao entrar na tela de manutenção
    const state = navigation.getState();
    if (state && state.routes.length > 1) {
      setPreviousRoute(state.routes[state.routes.length - 2].name as string);
    } else {
      navigation.navigate('Login' as never);
    }
  }, [navigation]);

  const handleGoBack = () => {
    if (previousRoute) {
      navigation.navigate(previousRoute as never);
    } else {
      navigation.navigate('Login' as never);
    }
  };

  const notifyMaintenanceEnded = async () => {
    if (!user?.telegram_chat_id || notified) return;

    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}/maintenance/notify-maintenance-ended`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ chat_id: user.telegram_chat_id }),
      });

      const result = await response.json();
      if (result.success) {
        setNotified(true);
      }
    } catch (error) {
      console.error('Erro ao enviar notificação:', error);
    }
  };

  const restartApp = () => {
    // Reiniciar o app
    Alert.alert(
      'Reiniciar App',
      'O sistema precisa reiniciar para voltar ao normal. Deseja reiniciar agora?',
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Reiniciar',
          onPress: () => {
            // Em React Native, podemos usar Updates.reloadAsync() do expo-updates
            // ou simplesmente navegar para a tela inicial e recarregar
            navigation.reset({
              index: 0,
              routes: [{ name: 'Login' as never }],
            });
          },
        },
      ]
    );
  };

  const checkMaintenance = async () => {
    // Se simulação está ativa, não tentar conectar ao servidor
    if (API_CONFIG.SIMULATE_MAINTENANCE) {
      setStatus({ is_under_maintenance: true, last_checked_at: new Date().toISOString() });
      setError(null);
      setLoading(false);
      return;
    }

    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}/maintenance/status`);
      if (!response.ok) {
        throw new Error('Erro ao conectar ao servidor');
      }
      const data = await response.json();

      // Verificar se a manutenção terminou
      if (status && status.is_under_maintenance && !data.is_under_maintenance && !maintenanceEnded) {
        setMaintenanceEnded(true);

        // Enviar notificação no Telegram
        await notifyMaintenanceEnded();

        // Redirecionar para tela de login (usuário precisa fazer login novamente)
        navigation.navigate('Login' as never);
        return;

        // Reiniciar o app
        setTimeout(() => {
          restartApp();
        }, 2000); // Esperar 2 segundos antes de reiniciar
      }

      setStatus(data);
      setError(null);
      setLoading(false);
    } catch (error) {
      console.error('Erro ao verificar manutenção:', error);
      // Se houver erro, usar último status conhecido (não assumir manutenção)
      if (status && status.is_under_maintenance) {
        // Já está em manutenção, manter status
        setStatus({ is_under_maintenance: true, last_checked_at: new Date().toISOString() });
      } else {
        // Não há status conhecido ou não está em manutenção, não assumir manutenção
        setStatus({ is_under_maintenance: false, last_checked_at: new Date().toISOString() });
      }
      setError(null);
      setLoading(false);
    }
  };

  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 500,
      useNativeDriver: true,
    }).start();
  }, []);

  useEffect(() => {
    checkMaintenance();
    const interval = setInterval(checkMaintenance, 5000); // Verificar a cada 5 segundos
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <View style={[styles.container, { paddingTop: insets.top }]}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>Verificando status...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <Animated.View style={[styles.container, { paddingTop: insets.top, opacity: fadeAnim }]}>
        <View style={styles.errorIconContainer}>
          <Text style={styles.errorIcon}>⚠️</Text>
        </View>
        <Text style={styles.errorText}>{error}</Text>
        <View style={styles.retryContainer}>
          <ActivityIndicator size="small" color={colors.primary} />
          <Text style={styles.retryText}>Tentando reconectar...</Text>
        </View>
      </Animated.View>
    );
  }

  return (
    <Animated.View style={[styles.container, { paddingTop: insets.top, opacity: fadeAnim }]}>
      <TouchableOpacity 
        style={[styles.backButton, { top: insets.top + 10 }]} 
        onPress={handleGoBack}
        activeOpacity={0.7}
      >
        <Ionicons name="arrow-back" size={24} color={colors.text} />
      </TouchableOpacity>
      
      <View style={styles.iconContainer}>
        <Text style={styles.icon}>🔧</Text>
      </View>
      <Text style={styles.title}>Corretora em Manutenção</Text>
      <Text style={styles.message}>
        A PocketOption está passando por manutenção programada.
      </Text>
      <Text style={styles.message}>
        O sistema foi desativado temporariamente e as estratégias foram pausadas.
      </Text>
      <View style={styles.infoContainer}>
        <Text style={styles.infoText}>
          Última verificação: {status?.last_checked_at ? new Date(status.last_checked_at).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : 'N/A'}
        </Text>
      </View>
      <ActivityIndicator size="small" color={colors.primary} style={styles.spinner} />
      <Text style={styles.statusText}>Verificando retorno da corretora...</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  backButton: {
    position: 'absolute',
    left: 20,
    padding: 8,
    zIndex: 10,
  },
  iconContainer: {
    marginBottom: 30,
  },
  icon: {
    fontSize: 100,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 12,
    textAlign: 'center',
  },
  message: {
    fontSize: 16,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 32,
    lineHeight: 24,
  },
  subMessage: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 20,
    lineHeight: 20,
  },
  infoContainer: {
    marginTop: 30,
    padding: 20,
    backgroundColor: colors.surfaceAlt,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoText: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
  },
  errorText: {
    color: colors.danger,
    fontSize: 14,
    marginTop: 12,
    textAlign: 'center',
  },
  spinner: {
    marginTop: 30,
  },
  statusText: {
    fontSize: 14,
    color: colors.textMuted,
    marginLeft: 8,
    fontWeight: '600',
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
    marginTop: 12,
  },
  errorIconContainer: {
    marginBottom: 30,
  },
  errorIcon: {
    fontSize: 80,
  },
  retryContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  retryText: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '600',
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceAlt,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    marginBottom: 20,
  },
});
