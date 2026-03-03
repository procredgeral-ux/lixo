import React, { useState, useEffect } from 'react';
import { View, ScrollView, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../theme';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { useConnection } from '../contexts/ConnectionContext';
import DashboardContent from '../components/DashboardContent';
import ConfiguracoesScreen from './ConfiguracoesScreen';
import EstrategiasScreen from './EstrategiasScreen';
import SinaisScreen from './SinaisScreen';
import HistoricoScreen from './HistoricoScreen';

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

  const handleMenuPress = (item: MenuItem) => {
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
              return (
                <TouchableOpacity
                  key={item.id}
                  style={styles.navItem}
                  onPress={() => handleMenuPress(item)}
                  activeOpacity={0.85}
                >
                  <Ionicons
                    name={item.icon as any}
                    size={22}
                    color={isSelected ? colors.primary : colors.textMuted}
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
    backgroundColor: colors.primarySoft,
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
