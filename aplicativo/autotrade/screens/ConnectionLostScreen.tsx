import React, { useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useConnection, ConnectionErrorType } from '../contexts/ConnectionContext';
import { colors } from '../theme';

export default function ConnectionLostScreen() {
  const navigation = useNavigation();
  const { connectionStatus, checkConnection, lastChecked, errorType } = useConnection();

  useEffect(() => {
    // Tentar reconectar a cada 5 segundos
    const interval = setInterval(() => {
      checkConnection();
    }, 5000);

    return () => clearInterval(interval);
  }, [checkConnection]);

  // Navegar de volta quando a conexão for restaurada
  useEffect(() => {
    if (connectionStatus === 'connected') {
      // Navegar de volta para a tela anterior
      navigation.goBack();
    }
  }, [connectionStatus, navigation]);

  const isChecking = connectionStatus === 'checking';
  const isDisconnected = connectionStatus === 'disconnected';

  const getErrorMessage = () => {
    if (errorType === 'network') {
      return 'Verifique sua conexão com a internet e tente novamente.';
    } else if (errorType === 'server') {
      return 'O servidor está temporariamente indisponível. Tente novamente em alguns minutos.';
    }
    return 'Não foi possível conectar ao servidor. Tente novamente.';
  };

  const getIcon = () => {
    if (errorType === 'network') {
      return '📶';
    } else if (errorType === 'server') {
      return '🖥️';
    }
    return '🔌';
  };

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        {isChecking ? (
          <>
            <ActivityIndicator size="large" color="#007AFF" />
            <Text style={styles.title}>Verificando conexão...</Text>
          </>
        ) : (
          <>
            <Text style={styles.icon}>{getIcon()}</Text>
            <Text style={styles.title}>
              {errorType === 'network' ? 'Sem internet' : 'Servidor indisponível'}
            </Text>
            <Text style={styles.message}>{getErrorMessage()}</Text>
            {lastChecked && (
              <Text style={styles.lastChecked}>
                Última verificação: {lastChecked.toLocaleTimeString()}
              </Text>
            )}
            <ActivityIndicator size="small" color="#007AFF" style={styles.spinner} />
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  content: {
    alignItems: 'center',
    padding: 20,
  },
  icon: {
    fontSize: 64,
    marginBottom: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 10,
  },
  message: {
    fontSize: 16,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 20,
  },
  lastChecked: {
    fontSize: 12,
    color: colors.textSoft,
    marginBottom: 20,
  },
  spinner: {
    marginTop: 10,
  },
});
