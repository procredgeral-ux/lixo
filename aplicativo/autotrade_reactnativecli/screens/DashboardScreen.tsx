import React, { useState, useEffect } from 'react';
import { View, ScrollView, StyleSheet, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Ionicons from 'react-native-vector-icons/Ionicons';
import { colors } from '../theme';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { useConnection } from '../contexts/ConnectionContext';
import { useScreenAvailability } from '../contexts/ScreenAvailabilityContext';
import { Alert } from 'react-native';
import DashboardContent from '../components/DashboardContent';
import ConfiguracoesScreen from './ConfiguracoesScreen';
import EstrategiasScreen from './EstrategiasScreen';
import SinaisScreen from './SinaisScreen';
import HistoricoScreen from './HistoricoScreen';

// ... rest of the code remains the same ...
interface MenuItem {
  id: string;
  icon: string;
  label: string;
}

const menuItems: MenuItem[] = [
  { id: 'dashboard', icon: 'bar-chart-outline', label: 'Dashboard' },
  { id: 'estrategias', icon: 'trending-up-outline', label: 'Estratégias' },
  { id: 'sinais', icon: 'trending-down-outline', label: 'Sinais' },
  { id: 'historico', icon: 'list-outline', label: 'Histórico' },
  { id: 'configuracoes', icon: 'settings-outline', label: 'Configurações' },
];

export default function DashboardScreen() {
  const navigation = useNavigation();
  const { user, logout } = useAuth();
  const { connectionStatus } = useConnection();
  const { isScreenEnabled } = useScreenAvailability();
  const [isUnderMaintenance, setIsUnderMaintenance] = useState(false);
  
  // Verificar se o usuário está autenticado
  useEffect(() => {
    if (!user) {
      console.log('[DashboardScreen] Usuário não autenticado, deslogando e redirecionando para login');
      logout();
      navigation.navigate('Login' as never);
    }
  }, [user, logout, navigation]);

  // Redirecionar para Admin se usuário for superusuário
  useEffect(() => {
    if (user?.is_superuser) {
      console.log('[DashboardScreen] Redirecionando para Admin - usuário é superusuário');
      navigation.reset({
        index: 0,
        routes: [{ name: 'Admin' as never }],
      });
    }
  }, [user?.is_superuser, navigation]);

  // Navegar para ConnectionLostScreen quando a conexão for perdida
  useEffect(() => {
    if (connectionStatus === 'disconnected') {
      navigation.navigate('ConnectionLost' as never);
    }
  }, [connectionStatus, navigation]);

  // Monitorar mudanças de conexão
  useEffect(() => {
    if (connectionStatus === 'maintenance') {
      console.log('[DashboardScreen] Navegando para tela de manutenção');
      setIsUnderMaintenance(true);
      navigation.navigate('Maintenance' as never);
    } else if (connectionStatus === 'connected') {
      setIsUnderMaintenance(false);
    }
  }, [connectionStatus, navigation]);
  const [selectedItem, setSelectedItem] = useState<string>('dashboard');
  const [lastScreenCheck, setLastScreenCheck] = useState<number>(Date.now());
  const [isRedirecting, setIsRedirecting] = useState<boolean>(false);

  // Verificar se a tela atual foi desabilitada e redirecionar inteligentemente
  useEffect(() => {
    // Evitar verificações se já estiver redirecionando
    if (isRedirecting || isUnderMaintenance) return;

    const checkAndRedirect = () => {
      if (!selectedItem || isScreenEnabled(selectedItem)) return;
      
      console.log(`[DashboardScreen] Tela ${selectedItem} foi desabilitada, redirecionando para Estratégias`);
      setIsRedirecting(true);
      
      // Redirecionar para Estratégias (fallback inteligente)
      setSelectedItem('estrategias');
      
      // Mostrar alerta informativo
      Alert.alert(
        'Tela Desabilitada',
        `A tela que você estava acessando foi desabilitada pelo administrador. Você foi redirecionado para Estratégias.`,
        [{ text: 'Entendido', style: 'default' }]
      );
      
      // Resetar flag após 2 segundos
      setTimeout(() => setIsRedirecting(false), 2000);
    };

    // Verificação periódica leve (a cada 10 segundos para economizar recursos)
    const now = Date.now();
    if (now - lastScreenCheck > 10000) {
      setLastScreenCheck(now);
      checkAndRedirect();
    }
  }, [selectedItem, isScreenEnabled, isUnderMaintenance, lastScreenCheck, isRedirecting]);

  // Detecção imediata de mudanças no contexto (mais eficiente)
  useEffect(() => {
    // Apenas verificar quando houver mudança real no estado da tela
    if (!selectedItem || isRedirecting || isUnderMaintenance) return;
    
    const isCurrentDisabled = !isScreenEnabled(selectedItem);
    const now = Date.now();
    const canCheckImmediately = now - lastScreenCheck > 1000;
    
    if (isCurrentDisabled && canCheckImmediately) {
      console.log(`[DashboardScreen] Detecção imediata: tela ${selectedItem} desabilitada`);
      setIsRedirecting(true);
      setLastScreenCheck(now);
      
      setSelectedItem('estrategias');
      
      Alert.alert(
        'Tela Desabilitada',
        `A tela que você estava acessando foi desabilitada pelo administrador. Você foi redirecionado para Estratégias.`,
        [{ text: 'Entendido', style: 'default' }]
      );
      
      setTimeout(() => setIsRedirecting(false), 2000);
    }
  }, [isScreenEnabled, selectedItem, isUnderMaintenance, lastScreenCheck, isRedirecting]);

  const handleMenuPress = (item: MenuItem) => {
    // Verificar se a tela está habilitada
    if (!isScreenEnabled(item.id)) {
      Alert.alert(
        'Tela em Manutenção',
        `A tela "${item.label}" está em manutenção sem previsão de retorno.`,
        [{ text: 'OK', style: 'default' }]
      );
      return;
    }
    setSelectedItem(item.id);
  };

  const renderContent = () => {
    // Se estiver em manutenção, não renderizar conteúdo
    if (isUnderMaintenance) {
      return null;
    }
    
    switch (selectedItem) {
      case 'dashboard':
        return <DashboardContent />;
      case 'estrategias':
        return <EstrategiasScreen />;
      case 'sinais':
        return <SinaisScreen />;
      case 'historico':
        return <HistoricoScreen />;
      case 'configuracoes':
        return <ConfiguracoesScreen />;
      default:
        return <DashboardContent />;
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <View style={styles.mainContent}>
          <ScrollView
            style={styles.contentArea}
            contentContainerStyle={styles.contentContainer}
            showsVerticalScrollIndicator={false}
          >
            {renderContent()}
          </ScrollView>

          <View style={styles.bottomNav}>
            {menuItems.map((item) => {
              const isSelected = selectedItem === item.id;
              const isEnabled = isScreenEnabled(item.id);
              return (
                <TouchableOpacity
                  key={item.id}
                  style={[styles.navItem, isSelected && styles.navItemActive, !isEnabled && styles.navItemDisabled]}
                  onPress={() => handleMenuPress(item)}
                  activeOpacity={isEnabled ? 0.85 : 1}
                  disabled={!isEnabled}
                >
                  <Ionicons
                    name={item.icon as any}
                    size={22}
                    color={!isEnabled ? '#64748B' : isSelected ? colors.primary : colors.textMuted}
                  />
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  serverIconContainer: {
    position: 'absolute',
    top: 50,
    right: 10,
    zIndex: 100,
  },
  content: {
    flex: 1,
    backgroundColor: colors.background,
  },
  mainContent: {
    flex: 1,
  },
  contentArea: {
    flex: 1,
  },
  contentContainer: {
    flexGrow: 1,
  },
  bottomNav: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingBottom: 12,
    paddingTop: 8,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 8,
    position: 'relative',
  },
  navItemActive: {
    backgroundColor: 'transparent',
  },
  navItemDisabled: {
    opacity: 0.5,
  },
  indicator: {
    position: 'absolute',
    bottom: 0,
    left: '50%',
    marginLeft: -14,
    width: 28,
    height: 3,
    backgroundColor: colors.primary,
    borderRadius: 1,
  },
});
