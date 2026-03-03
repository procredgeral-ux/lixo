import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { statsService, UserStats } from '../services/stats';
import { API_CONFIG } from '../constants/api';
import { useAuth } from '../contexts/AuthContext';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface StatCard {
  title: string;
  value: string;
  subtitle: string;
  color: string;
  icon: string;
}

export default function DashboardContent() {
  const { user } = useAuth();
  const [selectedMode, setSelectedMode] = useState<'demo' | 'real'>('demo');
  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isUnderMaintenance, setIsUnderMaintenance] = useState(false);
  
  // Refs para controle de requisições
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);

  // Verificar se o usuário está autenticado
  useEffect(() => {
    if (!user) {
      console.log('[DashboardContent] Usuário não autenticado, não carregando dados');
      setIsLoading(false);
      setError('Usuário não autenticado');
      return;
    }
  }, [user]);

  useEffect(() => {
    const checkMaintenance = async () => {
      try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.API_PREFIX}/maintenance/status`);
        const data = await response.json();
        if (isMountedRef.current) {
          setIsUnderMaintenance(data.is_under_maintenance);
        }
      } catch (error) {
        if (isMountedRef.current) {
          setIsUnderMaintenance(true);
        }
      }
    };

    checkMaintenance();
    const interval = setInterval(checkMaintenance, 300000);
    return () => {
      clearInterval(interval);
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (isUnderMaintenance || !isMountedRef.current) {
      return;
    }
    loadStats(true);
  }, [isUnderMaintenance]);

  useEffect(() => {
    if (isUnderMaintenance || !isMountedRef.current) {
      return;
    }
    
    // Cancelar requisição anterior se existir
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    
    loadStats(false);
  }, [selectedMode]);

  useEffect(() => {
    if (isUnderMaintenance || !isMountedRef.current) {
      return;
    }
    
    const interval = setInterval(() => {
      loadStats(false);
    }, 5000); // Atualiza a cada 5 segundos

    return () => {
      clearInterval(interval);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [isUnderMaintenance]);

  const loadStats = async (isInitial: boolean = false) => {
    // Cancelar requisição anterior
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Criar novo AbortController
    abortControllerRef.current = new AbortController();
    
    try {
      if (isInitial) {
        setIsLoading(true);
      }
      setError(null);
      
      // Carregar dados do backend
      const data = await statsService.getUserStats();
      
      if (isMountedRef.current) {
        setStats(data);
      }
    } catch (err: any) {
      if (err.name !== 'AbortError' && isMountedRef.current) {
        setError('Falha ao carregar estatísticas');
        console.error('Error loading stats:', err);
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  };

  const formatValue = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    // Mostrar no máximo 2 casas decimais
    const formatted = value.toLocaleString('pt-BR', {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    });
    return formatted;
  };

  const formatPercentage = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    return `${value.toFixed(0)}%`;
  };

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.content}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#7DD3FC" />
            <Text style={styles.loadingText}>Carregando...</Text>
          </View>
        </View>
      </View>
    );
  }

  if (error || !stats) {
    return (
      <View style={styles.container}>
        <View style={styles.content}>
          <View style={styles.errorContainer}>
            <Text style={styles.errorText}>{error || 'Nenhum dado disponível'}</Text>
            <TouchableOpacity style={styles.retryButton} onPress={() => loadStats(false)}>
              <Text style={styles.retryButtonText}>Tentar novamente</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    );
  }

  const demoStats: StatCard[] = [
    { title: 'Saldo', value: `US$ ${formatValue(stats.balance_demo)}`, subtitle: 'Disponível', color: '#007AFF', icon: 'wallet-outline' },
    { title: 'Win Rate', value: formatPercentage(stats.win_rate_demo), subtitle: `${stats.total_trades_demo} trades`, color: '#34C759', icon: 'trending-up-outline' },
    { title: 'Loss Rate', value: formatPercentage(stats.loss_rate_demo), subtitle: `${stats.total_trades_demo} trades`, color: '#FF3B30', icon: 'trending-down-outline' },
    { title: 'Trades', value: formatValue(stats.total_trades_demo), subtitle: 'Total', color: '#FF9500', icon: 'list-outline' },
  ];

  const realStats: StatCard[] = [
    { title: 'Saldo', value: `US$ ${formatValue(stats.balance_real)}`, subtitle: 'Disponível', color: '#007AFF', icon: 'wallet-outline' },
    { title: 'Win Rate', value: formatPercentage(stats.win_rate_real), subtitle: `${stats.total_trades_real} trades`, color: '#34C759', icon: 'trending-up-outline' },
    { title: 'Loss Rate', value: formatPercentage(stats.loss_rate_real), subtitle: `${stats.total_trades_real} trades`, color: '#FF3B30', icon: 'trending-down-outline' },
    { title: 'Trades', value: formatValue(stats.total_trades_real), subtitle: 'Total', color: '#FF9500', icon: 'list-outline' },
  ];

  // Cards adicionais com dados reais do backend
  const additionalStats: StatCard[] = [
    { title: 'Lucro Hoje', value: `+US$ ${formatValue(stats.lucro_hoje)}`, subtitle: `${stats.trades_hoje || 0} trades`, color: stats.lucro_hoje >= 0 ? '#34C759' : '#FF3B30', icon: 'cash-outline' },
    { title: 'Lucro Semana', value: `+US$ ${formatValue(stats.lucro_semana)}`, subtitle: 'Últimos 7 dias', color: stats.lucro_semana >= 0 ? '#34C759' : '#FF3B30', icon: 'trending-up-outline' },
    { title: 'Melhor Estratégia', value: stats.melhor_estrategia || 'N/A', subtitle: stats.taxa_sucesso !== undefined ? `${stats.taxa_sucesso.toFixed(0)}% win rate` : 'N/A', color: '#7DD3FC', icon: 'analytics-outline' },
    { title: 'Tempo Ativo', value: stats.tempo_ativo || '0h 0m', subtitle: 'Hoje', color: '#FF9500', icon: 'time-outline' },
    { title: 'Trades Hoje', value: (stats.trades_hoje || 0).toString(), subtitle: 'Total hoje', color: '#007AFF', icon: 'list-outline' },
    { title: 'Maior Ganho', value: `+US$ ${formatValue(stats.maior_ganho)}`, subtitle: 'Melhor trade', color: '#34C759', icon: 'arrow-up-circle' },
    { title: 'Maior Perda', value: `-US$ ${formatValue(Math.abs(stats.maior_perda || 0))}`, subtitle: 'Pior trade', color: '#FF3B30', icon: 'arrow-down-circle' },
    { title: 'Taxa de Sucesso', value: stats.taxa_sucesso !== undefined ? `${stats.taxa_sucesso.toFixed(0)}%` : 'N/A', subtitle: 'Últimos 30 dias', color: '#7DD3FC', icon: 'checkmark-circle' },
  ];

  const currentStats = selectedMode === 'demo' ? demoStats : realStats;

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Dashboard</Text>
          <Text style={styles.headerSubtitle}>
            Acompanhe suas estatísticas e desempenho
          </Text>
        </View>

        <View style={styles.selectorCard}>
          <TouchableOpacity
            style={[styles.selectorButton, selectedMode === 'demo' && styles.selectorButtonSelected]}
            onPress={() => setSelectedMode('demo')}
          >
            <Text style={[styles.selectorText, selectedMode === 'demo' && styles.selectorTextSelected]}>
              DEMO
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.selectorButton, selectedMode === 'real' && styles.selectorButtonSelected]}
            onPress={() => setSelectedMode('real')}
          >
            <Text style={[styles.selectorText, selectedMode === 'real' && styles.selectorTextSelected]}>
              REAL
            </Text>
          </TouchableOpacity>
        </View>

        <View style={styles.statsGrid}>
          {currentStats.map((stat) => (
            <View key={stat.title} style={styles.statCard}>
              <View style={styles.statHeader}>
                <Ionicons name={stat.icon as any} size={24} color={stat.color} />
              </View>
              <Text style={styles.statTitle}>{stat.title}</Text>
              <Text style={[styles.statValue, { color: stat.color }]}>{stat.value}</Text>
              <Text style={styles.statSubtitle}>{stat.subtitle}</Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Atividade Recente</Text>
          <View style={styles.statsGrid}>
            {additionalStats.map((stat) => (
              <View key={stat.title} style={styles.statCard}>
                <View style={styles.statHeader}>
                  <Ionicons name={stat.icon as any} size={24} color={stat.color} />
                </View>
                <Text style={styles.statTitle}>{stat.title}</Text>
                <Text style={[styles.statValue, { color: stat.color }]}>{stat.value}</Text>
                <Text style={styles.statSubtitle}>{stat.subtitle}</Text>
              </View>
            ))}
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
    padding: 16,
    alignItems: 'center',
  },
  header: {
    width: '100%',
    maxWidth: contentMaxWidth,
    marginBottom: 20,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 4,
  },
  headerSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
  },
  selectorCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    flexDirection: 'row',
    marginBottom: 12,
    overflow: 'hidden',
    height: 48,
    width: '100%',
    maxWidth: contentMaxWidth,
    borderWidth: 1,
    borderColor: colors.border,
  },
  selectorButton: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectorButtonSelected: {
    backgroundColor: colors.primary,
  },
  selectorText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSoft,
    letterSpacing: 0.8,
  },
  selectorTextSelected: {
    color: colors.primaryText,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    justifyContent: 'center',
    width: '100%',
    maxWidth: contentMaxWidth,
  },
  statCard: {
    width: '48%',
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    minHeight: 110,
    borderWidth: 1,
    borderColor: colors.border,
  },
  statHeader: {
    marginBottom: 8,
  },
  statTitle: {
    fontSize: 12,
    color: colors.textMuted,
    fontWeight: '500',
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  statValue: {
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 6,
  },
  statSubtitle: {
    fontSize: 11,
    color: colors.textSoft,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 16,
    color: colors.textMuted,
    marginTop: 12,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    fontSize: 16,
    color: colors.danger,
    marginBottom: 16,
  },
  retryButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 28,
    paddingVertical: 14,
    borderRadius: 999,
  },
  retryButtonText: {
    color: colors.primaryText,
    fontSize: 14,
    fontWeight: '700',
  },
  planCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  planHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  },
  planTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  planStatus: {
    fontSize: 12,
    color: colors.textMuted,
  },
  section: {
    width: '100%',
    maxWidth: contentMaxWidth,
    marginTop: 20,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textMuted,
    marginBottom: 12,
    letterSpacing: 0.5,
  },
});
