import React, { useMemo, useEffect, useState, useCallback, memo, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Modal, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { CustomAlert } from '../components/CustomAlert';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface StrategyListItem {
  id: string;
  name: string;
  description?: string | null;
  type: string;
  indicators: number;
  isActive: boolean;
  timeframes?: number[];
  notification?: string | null;
}

interface AutoTradeConfigItem {
  strategy_id: string;
  timeframe: number;
}

interface AccountInfo {
  id: string;
  ssid_demo?: string | null;
  ssid_real?: string | null;
  autotrade_demo?: boolean;
  autotrade_real?: boolean;
}

interface StrategyCardProps {
  strategy: StrategyListItem;
  onDeletePress: (strategy: StrategyListItem) => void;
  onTogglePower: (strategy: StrategyListItem) => void;
  onAutoPress: (strategyId: string) => void;
  onManagePress: (strategyId: string) => void;
}

// Componente otimizado para o card da estratégia
const StrategyCard = memo(({ strategy, onDeletePress, onTogglePower, onAutoPress, onManagePress }: StrategyCardProps) => {
  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <View style={styles.titleRow}>
          <Text style={styles.cardTitle}>{strategy.name}</Text>
          <View
            style={[
              styles.statusBadge,
              strategy.isActive ? styles.activeBadge : styles.pausedBadge,
            ]}
          >
            <Ionicons
              name={strategy.isActive ? 'flash' : 'pause'}
              size={14}
              color={strategy.isActive ? '#34C759' : '#FF9F0A'}
            />
            <Text
              style={[
                styles.badgeText,
                strategy.isActive ? styles.activeText : styles.pausedText,
              ]}
            >
              {strategy.isActive ? 'LIGADO' : 'DESLIGADO'}
            </Text>
          </View>
        </View>
        <TouchableOpacity
          style={styles.deleteButton}
          onPress={() => onDeletePress(strategy)}
          activeOpacity={0.7}
        >
          <Ionicons name="close" size={20} color="#F87171" />
        </TouchableOpacity>
      </View>
      <View style={styles.cardBody}>
        <Text style={styles.cardDescription}>{strategy.description}</Text>
        {strategy.notification && (
          <View style={styles.notificationBox}>
            <Ionicons name="warning" size={14} color="#FF9F0A" />
            <Text style={styles.notificationText}>{strategy.notification}</Text>
          </View>
        )}
        <View style={styles.indicatorRow}>
          <Ionicons name="analytics" size={14} color="#7DD3FC" />
          <Text style={styles.indicatorCount}>{strategy.indicators} indicadores</Text>
        </View>
      </View>
      <View style={styles.cardFooter}>
        <View style={styles.buttonRow}>
          <TouchableOpacity
            style={styles.autoBadge}
            onPress={() => onAutoPress(strategy.id)}
          >
            <Text style={styles.autoBadgeText}>AUTO</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.manageBadge}
            onPress={() => onManagePress(strategy.id)}
          >
            <Text style={styles.manageBadgeText}>Gerenciar</Text>
          </TouchableOpacity>
        </View>
        <TouchableOpacity
          style={styles.iconButton}
          activeOpacity={0.7}
          onPress={() => onTogglePower(strategy)}
        >
          <Ionicons
            name={strategy.isActive ? 'power' : 'power-outline'}
            size={16}
            color={strategy.isActive ? '#34C759' : '#94A3B8'}
          />
        </TouchableOpacity>
      </View>
    </View>
  );
}, (prevProps, nextProps) => {
  // Só re-renderizar se o status mudou (evita re-renderização desnecessária)
  return prevProps.strategy.isActive === nextProps.strategy.isActive;
});

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function EstrategiasScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const { user } = useAuth();
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<number | 'all'>('all');
  const [deleteModalVisible, setDeleteModalVisible] = useState(false);
  const [strategyToDelete, setStrategyToDelete] = useState<StrategyListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedMode, setSelectedMode] = useState<'demo' | 'real'>('demo');
  const [modeModalVisible, setModeModalVisible] = useState(false);
  const [pendingMode, setPendingMode] = useState<'demo' | 'real' | null>(null);
  const [switchingMode, setSwitchingMode] = useState(false);
  const [autotradeConfigs, setAutotradeConfigs] = useState<AutoTradeConfigItem[]>([]);
  const [alertVisible, setAlertVisible] = useState(false);
  const [alertConfig, setAlertConfig] = useState<{ title: string; message: string; type?: 'success' | 'error' | 'warning' | 'info'; buttons?: Array<{ text: string; onPress?: () => void; style?: 'default' | 'cancel' | 'destructive' }> } | null>(null);
  const [switchStrategyModalVisible, setSwitchStrategyModalVisible] = useState(false);
  const [pendingStrategy, setPendingStrategy] = useState<StrategyListItem | null>(null);
  const [switchingStrategy, setSwitchingStrategy] = useState(false);
  const [accountInfo, setAccountInfo] = useState<AccountInfo | null>(null);
  const accountInfoRef = useRef<AccountInfo | null>(null);

  // Atualizar ref sempre que accountInfo mudar
  useEffect(() => {
    accountInfoRef.current = accountInfo;
  }, [accountInfo]);

  const fetchAccountMode = useCallback(async () => {
    try {
      const response = await apiClient.get<any>('/accounts');
      const accounts = Array.isArray(response)
        ? response
        : Array.isArray(response?.accounts)
        ? response.accounts
        : [];
      const account = accounts[0];

      setAccountInfo(account || null);

      // Verificar se usuário tem conta e SSID cadastrado
      if (account) {
        const hasSsidDemo = account.ssid_demo && account.ssid_demo.trim().length > 0;
        const hasSsidReal = account.ssid_real && account.ssid_real.trim().length > 0;

        if (!hasSsidDemo && !hasSsidReal) {
          // Mostrar alert apenas uma vez
          const hasShownAlert = await AsyncStorage.getItem('ssid_alert_shown');
          if (!hasShownAlert) {
            setAlertConfig({
              title: 'SSID não cadastrado',
              message: 'Para ativar estratégias, você precisa cadastrar o SSID da sua conta. Deseja cadastrar agora?',
              type: 'warning',
              buttons: [
                {
                  text: 'Cadastrar SSID',
                  onPress: async () => {
                    await AsyncStorage.setItem('ssid_alert_shown', 'true');
                    navigation.navigate('SsidRegistration' as never);
                  },
                },
                {
                  text: 'Mais tarde',
                  style: 'cancel',
                  onPress: async () => await AsyncStorage.setItem('ssid_alert_shown', 'true'),
                },
              ],
            });
            setAlertVisible(true);
          }
        }
      }
      
      if (account?.autotrade_real) {
        setSelectedMode('real');
      } else if (account?.autotrade_demo) {
        setSelectedMode('demo');
      }
    } catch (err) {
      console.error('Erro ao carregar modo da conta:', err);
      setAccountInfo(null);
    }
  }, [navigation]);

  const fetchAutotradeConfigs = useCallback(async () => {
    try {
      const response = await apiClient.get<any>('/autotrade-config');
      const configs = Array.isArray(response)
        ? response
        : Array.isArray(response?.configs)
        ? response.configs
        : [];

      const normalized: AutoTradeConfigItem[] = configs.map((item: any) => ({
        strategy_id: item.strategy_id,
        timeframe: item.timeframe || 5,
      }));

      setAutotradeConfigs(normalized);
    } catch (err) {
      console.error('Erro ao carregar configurações de autotrade:', err);
    }
  }, []);

  const fetchStrategies = useCallback(async (isInitial: boolean = false) => {
    try {
      // Só mostra loading na primeira carga
      if (isInitial) {
        setLoading(true);
        setIsInitialLoad(true);
      }
      setError(null);
      const response = await apiClient.get<any>('/strategies');
      const items = Array.isArray(response)
        ? response
        : Array.isArray(response?.strategies)
        ? response.strategies
        : [];

      const normalized: StrategyListItem[] = items.map((item: any) => {
        const indicatorsArray = Array.isArray(item.indicators) ? item.indicators : [];
        // Converter is_active para booleano (0/1 para false/true)
        const isActive = item.is_active === true || item.is_active === 1;
        return {
          id: item.id,
          name: item.name,
          description: item.description || 'Sem descrição',
          type: item.type || 'standard',
          indicators: indicatorsArray.length,
          isActive: isActive,
        };
      });

      // Sempre atualizar quando é carga inicial ou quando a tela ganha foco
      if (isInitial) {
        setStrategies(normalized);
      } else {
        // Para polling, só atualizar se houver mudança no estado is_active
        const prevMap = new Map(strategies.map(s => [s.id, s]));
        const hasChanged = normalized.some(newStrat => {
          const prevStrat = prevMap.get(newStrat.id);
          return !prevStrat || prevStrat.isActive !== newStrat.isActive || 
                 prevStrat.name !== newStrat.name || prevStrat.indicators !== newStrat.indicators ||
                 prevStrat.description !== newStrat.description;
        });
        
        if (hasChanged) {
          setStrategies(normalized);
        }
      }
    } catch (err) {
      setError('Não foi possível carregar suas estratégias');
      console.error('Erro ao carregar estratégias', err);
    } finally {
      setLoading(false);
      setIsInitialLoad(false);
    }
  }, []);

  // Carregar estratégias e configs quando a tela ganha foco
  useFocusEffect(
    useCallback(() => {
      fetchStrategies(true);
      fetchAutotradeConfigs();
      fetchAccountMode();
    }, [fetchStrategies, fetchAutotradeConfigs, fetchAccountMode])
  );

  // Polling para atualizar estratégias a cada 2 segundos para resposta imediata
  useEffect(() => {
    const interval = setInterval(() => {
      fetchStrategies(false); // Não mostra loading nas atualizações
      fetchAutotradeConfigs();
    }, 2000); // 2 segundos para atualização quase imediata

    return () => clearInterval(interval);
  }, []);

  // Obter timeframes únicos das configurações de autotrade
  const availableTimeframes = useMemo(() => {
    const timeframesSet = new Set<number>();
    autotradeConfigs.forEach((config) => {
      timeframesSet.add(config.timeframe);
    });
    return Array.from(timeframesSet).sort((a, b) => a - b);
  }, [autotradeConfigs]);

  // Filtrar estratégias por timeframe
  const filteredStrategies = useMemo(() => {
    if (filter === 'all') return strategies;

    // Filtrar estratégias que têm configuração de autotrade com o timeframe selecionado
    const strategyIdsWithTimeframe = autotradeConfigs
      .filter((config) => config.timeframe === filter)
      .map((config) => config.strategy_id);

    return strategies.filter((strategy) => strategyIdsWithTimeframe.includes(strategy.id));
  }, [strategies, filter, autotradeConfigs]);

  const formatTimeframe = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    return `${seconds / 60}m`;
  };

  const handleDeletePress = useCallback((strategy: StrategyListItem) => {
    if (strategy.isActive) {
      setAlertConfig({
        title: 'Estratégia ativa',
        message: 'Desative a estratégia antes de excluí-la.',
        type: 'warning',
      });
      setAlertVisible(true);
      return;
    }

    setStrategyToDelete(strategy);
    setDeleteModalVisible(true);
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!strategyToDelete) return;

    const currentStrategy = strategies.find((strategy) => strategy.id === strategyToDelete.id);
    if (currentStrategy?.isActive) {
      setDeleteModalVisible(false);
      setStrategyToDelete(null);
      setAlertConfig({
        title: 'Estratégia ativa',
        message: 'Desative a estratégia antes de excluí-la.',
        type: 'warning',
      });
      setAlertVisible(true);
      return;
    }

    try {
      setDeleting(true);
      await apiClient.delete(`/strategies/${strategyToDelete.id}`);
      setStrategies(prevStrategies => prevStrategies.filter(s => s.id !== strategyToDelete.id));
      setDeleteModalVisible(false);
      setStrategyToDelete(null);
      setAlertConfig({
        title: 'Sucesso',
        message: 'Estratégia excluída com sucesso!',
        type: 'success',
      });
      setAlertVisible(true);
    } catch (err) {
      console.error('Erro ao excluir estratégia:', err);
      setAlertConfig({
        title: 'Erro',
        message: 'Não foi possível excluir a estratégia',
        type: 'error',
      });
      setAlertVisible(true);
    } finally {
      setDeleting(false);
    }
  }, [strategyToDelete, strategies]);

  const cancelDelete = useCallback(() => {
    setDeleteModalVisible(false);
    setStrategyToDelete(null);
  }, []);

  const handleModePress = useCallback((mode: 'demo' | 'real') => {
    if (mode === selectedMode) return;
    
    // Verificar se usuário é VIP ou VIP+ para ativar modo real
    // Superusuários podem ativar modo real sem restrições
    if (mode === 'real') {
      const userRole = user?.role || 'free';
      const isSuperuser = user?.is_superuser || false;
      
      console.log('[EstrategiasScreen] Validação modo real:');
      console.log('  - userRole:', userRole);
      console.log('  - isSuperuser:', isSuperuser);
      console.log('  - vip_start_date:', user?.vip_start_date);
      console.log('  - vip_end_date:', user?.vip_end_date);
      
      // Superusuários podem ativar modo real sem restrições
      if (!isSuperuser) {
        // Verificar se usuário tem plano VIP ativo
        const isVipActive = userRole === 'vip' || userRole === 'vip_plus';
        
        console.log('  - isVipActive:', isVipActive);
        
        if (!isVipActive) {
          // Personalizar mensagem baseado no status do VIP
          let title = 'Acesso Premium Necessário';
          let message = 'Para operar em conta real, você precisa ser usuário VIP ou VIP+. Entre em contato com o gerente de contas para adquirir seu acesso.';
          
          setAlertConfig({
            title: title,
            message: message,
            type: 'warning',
            buttons: [
              {
                text: 'Falar com o Gerente',
                onPress: () => {
                  // Abrir Telegram com o gerente @leandrosouzaw
                  const telegramUrl = `https://t.me/leandrosouzaw`;
                  Linking.openURL(telegramUrl).catch(() => {
                    // Fallback: tentar abrir no app Telegram
                    const telegramAppUrl = `tg://resolve?domain=t.me&username=leandrosouzaw`;
                    Linking.openURL(telegramAppUrl);
                  });
                },
                style: 'default'
              },
              {
                text: 'Cancelar',
                onPress: () => setAlertVisible(false),
                style: 'cancel'
              }
            ]
          });
          setAlertVisible(true);
          return;
        }
      }
    }
    
    setPendingMode(mode);
    setModeModalVisible(true);
  }, [selectedMode, user]);

  const confirmModeSwitch = useCallback(async () => {
    if (!pendingMode) return;

    try {
      setSwitchingMode(true);
      await apiClient.put('/accounts/me', {
        autotrade_demo: pendingMode === 'demo' ? true : false,
        autotrade_real: pendingMode === 'real' ? true : false,
      });
      setSelectedMode(pendingMode);
      setModeModalVisible(false);
      setPendingMode(null);
      setAlertConfig({
        title: 'Sucesso',
        message: `Modo ${pendingMode === 'demo' ? 'Demo' : 'Real'} ativado com sucesso!`,
        type: 'success',
      });
      setAlertVisible(true);
    } catch (err) {
      console.error('Erro ao mudar modo:', err);
      setAlertConfig({
        title: 'Erro',
        message: 'Não foi possível mudar o modo de operação',
        type: 'error',
      });
      setAlertVisible(true);
    } finally {
      setSwitchingMode(false);
    }
  }, [pendingMode]);

  const cancelModeSwitch = useCallback(() => {
    setModeModalVisible(false);
    setPendingMode(null);
  }, []);

  const ensureSsidForMode = useCallback((mode: 'demo' | 'real') => {
    const currentAccountInfo = accountInfoRef.current;
    const ssid = mode === 'demo' ? currentAccountInfo?.ssid_demo : currentAccountInfo?.ssid_real;
    const hasSsid = ssid && ssid.trim().length > 0;

    if (hasSsid) return true;

    const modeLabel = mode === 'demo' ? 'Demo' : 'Real';
    setAlertConfig({
      title: `SSID ${modeLabel} não cadastrado`,
      message: `Cadastre o SSID ${modeLabel} na sua conta para ligar a estratégia.`,
      type: 'warning',
      buttons: [
        {
          text: 'Cadastrar SSID',
          onPress: () => navigation.navigate('SsidRegistration' as never),
        },
        {
          text: 'Cancelar',
          style: 'cancel',
        },
      ],
    });
    setAlertVisible(true);
    return false;
  }, [navigation]);

  const handleTogglePower = useCallback(async (strategy: StrategyListItem) => {
    const currentAccountInfo = accountInfoRef.current;
    const activeStrategy = strategies.find(s => s.isActive && s.id !== strategy.id);

    if (!strategy.isActive) {
      // Verificar se existe SSID para o modo selecionado
      const ssid = selectedMode === 'demo' ? currentAccountInfo?.ssid_demo : currentAccountInfo?.ssid_real;
      const hasSsid = ssid && ssid.trim().length > 0;

      if (!hasSsid) {
        const modeLabel = selectedMode === 'demo' ? 'Demo' : 'Real';
        setAlertConfig({
          title: `SSID ${modeLabel} não cadastrado`,
          message: `Cadastre o SSID ${modeLabel} na sua conta para ligar a estratégia.`,
          type: 'warning',
          buttons: [
            {
              text: 'Cadastrar SSID',
              onPress: () => navigation.navigate('SsidRegistration' as never),
            },
            {
              text: 'Cancelar',
              style: 'cancel',
            },
          ],
        });
        setAlertVisible(true);
        return;
      }

      if (activeStrategy) {
        setPendingStrategy(strategy);
        setSwitchStrategyModalVisible(true);
        return;
      }
    }
    
    try {
      await apiClient.put(`/strategies/${strategy.id}`, {
        is_active: !strategy.isActive
      });
      // Atualizar estado local apenas após sucesso da requisição
      setStrategies(prevStrategies => prevStrategies.map(s =>
        s.id === strategy.id
          ? { ...s, isActive: !s.isActive }
          : s
      ));
    } catch (err) {
      console.error('Erro ao alternar estado da estratégia:', err);
      setAlertConfig({
        title: 'Erro',
        message: 'Não foi possível alterar o estado da estratégia',
        type: 'error',
      });
      setAlertVisible(true);
    }
  }, [strategies, selectedMode, navigation]);

  const confirmSwitchStrategy = useCallback(async () => {
    if (!pendingStrategy) return;
    
    const activeStrategy = strategies.find(s => s.isActive);
    if (!activeStrategy) return;

    if (!ensureSsidForMode(selectedMode)) {
      setSwitchStrategyModalVisible(false);
      setPendingStrategy(null);
      return;
    }
    
    try {
      setSwitchingStrategy(true);
      
      await Promise.all([
        apiClient.put(`/strategies/${activeStrategy.id}`, { is_active: false }),
        apiClient.put(`/strategies/${pendingStrategy.id}`, { is_active: true })
      ]);
      
      setStrategies(prevStrategies => prevStrategies.map(s =>
        s.id === activeStrategy.id
          ? { ...s, isActive: false }
          : s.id === pendingStrategy.id
          ? { ...s, isActive: true }
          : s
      ));
      
      setSwitchStrategyModalVisible(false);
      setPendingStrategy(null);
      setAlertConfig({
        title: 'Sucesso',
        message: `Estratégia "${pendingStrategy.name}" ativada e "${activeStrategy.name}" desativada!`,
        type: 'success',
      });
      setAlertVisible(true);
    } catch (err) {
      console.error('Erro ao trocar estratégia:', err);
      setAlertConfig({
        title: 'Erro',
        message: 'Não foi possível trocar a estratégia',
        type: 'error',
      });
      setAlertVisible(true);
    } finally {
      setSwitchingStrategy(false);
    }
  }, [pendingStrategy, strategies, selectedMode]);

  const cancelSwitchStrategy = useCallback(() => {
    setSwitchStrategyModalVisible(false);
    setPendingStrategy(null);
  }, []);

  const handleAutoPress = useCallback((strategyId: string) => {
    // @ts-ignore - Navigation params are dynamic
    navigation.navigate('AutoTradeConfig', { strategyId });
  }, [navigation]);

  const handleManagePress = useCallback((strategyId: string) => {
    // @ts-ignore - Navigation params are dynamic
    navigation.navigate('EditStrategy', { strategyId });
  }, [navigation]);

  return (
    <View style={styles.container}>
      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#7DD3FC" />
          <Text style={styles.loadingText}>Carregando estratégias...</Text>
        </View>
      ) : error ? (
        <View style={styles.loadingContainer}>
          <Ionicons name="warning" size={28} color="#F87171" />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scrollContainer}>
        <View style={styles.heroCard}>
          <View style={styles.heroText}>
            <Text style={styles.heroEyebrow}>Painel de Estratégias</Text>
            <Text style={styles.heroTitle}>Controle total sobre suas execuções</Text>
            <Text style={styles.heroDescription}>
              Acompanhe desempenho, ative novas ideias e ajuste indicadores em um só lugar.
            </Text>
          </View>
          <TouchableOpacity
            style={styles.heroButton}
            onPress={() => navigation.navigate('CreateStrategy' as never)}
            activeOpacity={0.9}
          >
            <Ionicons name="add" size={18} color="#0F172A" />
            <Text style={styles.heroButtonText}>Criar estratégia</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.filterRow}>
          <TouchableOpacity
            style={[styles.filterPill, filter === 'all' && styles.filterPillActive]}
            onPress={() => setFilter('all')}
          >
            <Text style={[styles.filterText, filter === 'all' && styles.filterTextActive]}>Todas</Text>
          </TouchableOpacity>
          {availableTimeframes.map((timeframe) => (
            <TouchableOpacity
              key={timeframe}
              style={[styles.filterPill, filter === timeframe && styles.filterPillActive]}
              onPress={() => setFilter(timeframe)}
            >
              <Text style={[styles.filterText, filter === timeframe && styles.filterTextActive]}>
                {formatTimeframe(timeframe)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.section}>
          <View style={styles.modeSelectorSection}>
            <Text style={styles.modeSelectorLabel}>Conta de Execução</Text>
            <Text style={styles.modeSelectorDescription}>Selecione a conta para executar trades e analisar resultados</Text>
            <View style={styles.modeSelectorCard}>
              <TouchableOpacity
                style={[styles.modeSelectorButton, selectedMode === 'demo' && styles.modeSelectorButtonSelected]}
                onPress={() => handleModePress('demo')}
              >
                <Ionicons 
                  name={selectedMode === 'demo' ? 'checkmark-circle' : 'ellipse-outline'} 
                  size={18} 
                  color={selectedMode === 'demo' ? '#0F172A' : '#657089'} 
                  style={styles.modeSelectorIcon}
                />
                <Text style={[styles.modeSelectorText, selectedMode === 'demo' && styles.modeSelectorTextSelected]}>
                  DEMO
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modeSelectorButton, selectedMode === 'real' && styles.modeSelectorButtonSelected]}
                onPress={() => handleModePress('real')}
              >
                <Ionicons 
                  name={selectedMode === 'real' ? 'checkmark-circle' : 'ellipse-outline'} 
                  size={18} 
                  color={selectedMode === 'real' ? '#0F172A' : '#657089'} 
                  style={styles.modeSelectorIcon}
                />
                <Text style={[styles.modeSelectorText, selectedMode === 'real' && styles.modeSelectorTextSelected]}>
                  REAL
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Minhas estratégias</Text>
            <TouchableOpacity style={styles.sectionAction} onPress={() => navigation.navigate('StrategyPerformance' as never)}>
              <Text style={styles.sectionActionText}>Ver desempenho</Text>
              <Ionicons name="arrow-forward" size={16} color="#7DD3FC" />
            </TouchableOpacity>
          </View>

          {filteredStrategies.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              onDeletePress={handleDeletePress}
              onTogglePower={handleTogglePower}
              onAutoPress={handleAutoPress}
              onManagePress={handleManagePress}
            />
          ))}
        </View>
        {filteredStrategies.length === 0 && (
          <View style={styles.emptyState}>
            <Ionicons name="documents" size={48} color="#2F3B52" />
            <Text style={styles.emptyTitle}>Nenhuma estratégia cadastrada</Text>
            <Text style={styles.emptySubtitle}>Crie sua primeira estratégia para vê-la aqui.</Text>
          </View>
        )}
      </ScrollView>
      )}

      {/* Modal de Confirmação de Exclusão */}
      <Modal
        visible={deleteModalVisible}
        transparent={true}
        animationType="fade"
        onRequestClose={cancelDelete}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            <Text style={styles.modalTitle}>Excluir Estratégia</Text>
            <Text style={styles.modalMessage}>
              Tem certeza que deseja excluir a estratégia "{strategyToDelete?.name}"? Esta ação não pode ser desfeita.
            </Text>
            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonCancel]}
                onPress={cancelDelete}
                disabled={deleting}
              >
                <Text style={styles.modalButtonTextCancel}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonConfirm]}
                onPress={confirmDelete}
                disabled={deleting}
              >
                {deleting ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.modalButtonTextConfirm}>Excluir</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Modal de Confirmação de Mudança de Modo */}
      <Modal
        visible={modeModalVisible}
        transparent={true}
        animationType="fade"
        onRequestClose={cancelModeSwitch}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            <Text style={styles.modalTitle}>Mudar Modo de Operação</Text>
            <Text style={styles.modalMessage}>
              Tem certeza que deseja mudar para o modo {pendingMode === 'demo' ? 'Demo' : 'Real'}? A conexão atual será desconectada e uma nova conexão será estabelecida.
            </Text>
            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonCancel]}
                onPress={cancelModeSwitch}
                disabled={switchingMode}
              >
                <Text style={styles.modalButtonTextCancel}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonConfirm]}
                onPress={confirmModeSwitch}
                disabled={switchingMode}
              >
                {switchingMode ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.modalButtonTextConfirm}>Confirmar</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Modal de Confirmação de Troca de Estratégia */}
      <Modal
        visible={switchStrategyModalVisible}
        transparent={true}
        animationType="fade"
        onRequestClose={cancelSwitchStrategy}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            <Text style={styles.modalTitle}>Trocar Estratégia</Text>
            <Text style={styles.modalMessage}>
              Já existe uma estratégia rodando: <Text style={styles.modalHighlight}>{strategies.find(s => s.isActive)?.name}</Text>.{'\n\n'}
              Deseja desativá-la e ativar <Text style={styles.modalHighlight}>{pendingStrategy?.name}</Text>?
            </Text>
            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonCancel]}
                onPress={cancelSwitchStrategy}
                disabled={switchingStrategy}
              >
                <Text style={styles.modalButtonTextCancel}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalButton, styles.modalButtonConfirm]}
                onPress={confirmSwitchStrategy}
                disabled={switchingStrategy}
              >
                {switchingStrategy ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.modalButtonTextConfirm}>OK</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* CustomAlert */}
      <CustomAlert
        visible={alertVisible}
        title={alertConfig?.title || ''}
        message={alertConfig?.message || ''}
        type={alertConfig?.type}
        buttons={alertConfig?.buttons}
        onClose={() => setAlertVisible(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollContainer: {
    padding: 20,
    gap: 16,
  },
  heroCard: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
  },
  heroText: {
    gap: 6,
  },
  heroEyebrow: {
    color: colors.primary,
    textTransform: 'uppercase',
    fontSize: 12,
    letterSpacing: 1,
  },
  heroTitle: {
    color: colors.text,
    fontSize: 22,
    fontWeight: '700',
  },
  heroDescription: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  heroButton: {
    marginTop: 16,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 999,
    width: '60%',
    justifyContent: 'center',
    gap: 6,
  },
  heroButtonText: {
    color: colors.primaryText,
    fontWeight: '700',
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  filterPill: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.surfaceAlt,
  },
  filterPillActive: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  filterText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  filterTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  statsRow: {
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.surfaceAlt,
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 4,
  },
  statValue: {
    color: colors.text,
    fontSize: 26,
    fontWeight: '700',
  },
  section: {
    marginTop: 8,
    gap: 12,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    gap: 12,
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  errorText: {
    color: colors.danger,
    fontSize: 14,
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '700',
  },
  sectionAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  sectionActionText: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: '500',
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 14,
  },
  emptyState: {
    padding: 32,
    alignItems: 'center',
    gap: 8,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  emptySubtitle: {
    color: colors.textMuted,
    fontSize: 13,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  cardBody: {
    marginBottom: 12,
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  cardTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 999,
  },
  activeBadge: {
    backgroundColor: 'rgba(52, 199, 89, 0.15)',
  },
  pausedBadge: {
    backgroundColor: 'rgba(255, 159, 10, 0.15)',
  },
  badgeText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '500',
  },
  activeText: {
    color: '#34C759',
  },
  pausedText: {
    color: '#FF9F0A',
  },
  cardDescription: {
    color: colors.textMuted,
    fontSize: 14,
    marginBottom: 12,
  },
  indicatorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  indicatorCount: {
    color: colors.primary,
    fontSize: 13,
  },
  actionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  footerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  footerText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  cardActions: {
    flexDirection: 'row',
    gap: 8,
    alignItems: 'center',
  },
  autoBadge: {
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
    backgroundColor: colors.primarySoft,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  autoBadgeText: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 8,
  },
  manageBadge: {
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
    backgroundColor: 'rgba(52, 199, 89, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(52, 199, 89, 0.3)',
  },
  manageBadgeText: {
    color: colors.success,
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
  pillButton: {
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  ghostButton: {
    backgroundColor: 'rgba(148, 163, 184, 0.15)',
  },
  ghostButtonText: {
    color: '#B0C4DE',
    fontWeight: '600',
  },
  primaryButton: {
    backgroundColor: '#2563EB',
  },
  primaryButtonTextSmall: {
    color: '#FFFFFF',
    fontWeight: '600',
  },
  iconButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconButtonActive: {
    backgroundColor: colors.primary,
  },
  iconButtonPaused: {
    backgroundColor: colors.surfaceAlt,
  },
  powerButtonWrapper: {
    borderRadius: 999,
    borderWidth: 2,
    borderColor: 'rgba(255, 255, 255, 0.3)',
    padding: 2,
  },
  powerButtonActive: {
    borderColor: colors.success,
    shadowColor: colors.success,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 8,
    elevation: 4,
  },
  deleteButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  notificationBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 159, 10, 0.1)',
    padding: 8,
    borderRadius: 8,
    marginTop: 8,
    borderWidth: 1,
    borderColor: 'rgba(255, 159, 10, 0.3)',
  },
  notificationText: {
    color: colors.warning,
    fontSize: 12,
    marginLeft: 6,
    fontWeight: '600',
  },
  deleteModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  deleteModalContent: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 24,
    width: '100%',
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  deleteModalIcon: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: 'rgba(248, 113, 113, 0.15)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  deleteModalTitle: {
    color: colors.text,
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 12,
    textAlign: 'center',
  },
  deleteModalMessage: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 24,
    textAlign: 'center',
  },
  deleteModalActions: {
    flexDirection: 'row',
    gap: 12,
  },
  deleteModalButton: {
    flex: 1,
    padding: 14,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelButton: {
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  confirmButton: {
    backgroundColor: colors.danger,
  },
  deleteModalButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  modeSelectorSection: {
    marginBottom: 20,
  },
  modeSelectorLabel: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 4,
  },
  modeSelectorDescription: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 12,
  },
  modeSelectorCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    flexDirection: 'row',
    overflow: 'hidden',
    height: 52,
    borderWidth: 2,
    borderColor: colors.borderStrong,
  },
  modeSelectorButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  modeSelectorButtonSelected: {
    backgroundColor: colors.primary,
  },
  modeSelectorIcon: {
    marginRight: 4,
  },
  modeSelectorText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#657089',
    letterSpacing: 0.8,
  },
  modeSelectorTextSelected: {
    color: colors.primaryText,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContainer: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 16,
    padding: 24,
    width: '100%',
    maxWidth: 320,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 12,
    textAlign: 'center',
  },
  modalMessage: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: 20,
    textAlign: 'center',
    lineHeight: 20,
  },
  modalButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  modalButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 8,
    alignItems: 'center',
  },
  modalButtonCancel: {
    backgroundColor: '#475569',
  },
  modalButtonConfirm: {
    backgroundColor: colors.danger,
  },
  modalButtonTextCancel: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  modalButtonTextConfirm: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  modalHighlight: {
    color: colors.primary,
    fontWeight: '600',
  },
});
