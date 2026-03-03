import React, { useState, useMemo, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Dimensions,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { apiClient, IndicatorCombinationRanking } from '../services/api';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

const { width } = Dimensions.get('window');

interface StrategyPerformance {
  id: string;
  name: string;
  totalTrades: number;
  winRate: number;
  profitFactor: number;
  totalProfit: number;
  maxDrawdown: number;
  sharpeRatio: number;
  avgWin: number;
  avgLoss: number;
  largestWin: number;
  largestLoss: number;
  consecutiveWins: number;
  consecutiveLosses: number;
  monthlyReturns: number[];
}

interface StrategySummary {
  id: string;
  name: string;
}

interface StrategyPerformanceSnapshotResponse {
  strategy_id: string;
  strategy_name: string;
  performance: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    total_profit: number;
    total_loss: number;
    net_profit: number;
    profit_factor: number;
    max_drawdown: number;
    sharpe_ratio: number;
    avg_win: number;
    avg_loss: number;
    largest_win: number;
    largest_loss: number;
    consecutive_wins: number;
    consecutive_losses: number;
    monthly_returns: number[];
  };
  snapshot_date?: string | null;
}

const normalizePerformance = (
  item: StrategyPerformanceSnapshotResponse
): StrategyPerformance => ({
  id: item.strategy_id,
  name: item.strategy_name,
  totalTrades: item.performance.total_trades,
  winRate: item.performance.win_rate,
  profitFactor: item.performance.profit_factor,
  totalProfit: item.performance.net_profit,
  maxDrawdown: item.performance.max_drawdown,
  sharpeRatio: item.performance.sharpe_ratio,
  avgWin: item.performance.avg_win,
  avgLoss: item.performance.avg_loss,
  largestWin: item.performance.largest_win,
  largestLoss: item.performance.largest_loss,
  consecutiveWins: item.performance.consecutive_wins,
  consecutiveLosses: item.performance.consecutive_losses,
  monthlyReturns: item.performance.monthly_returns || [],
});

interface MetricCardProps {
  title: string;
  value: string;
  change?: string;
  trend?: 'up' | 'down' | 'neutral';
  icon: string;
  color: string;
}

const MetricCard: React.FC<MetricCardProps> = ({ title, value, change, trend, icon, color }) => (
  <View style={styles.metricCard}>
    <View style={styles.metricHeader}>
      <Ionicons name={icon as any} size={20} color={color} />
      <Text style={styles.metricTitle}>{title}</Text>
    </View>
    <Text style={styles.metricValue}>{value}</Text>
    {change && (
      <View style={styles.metricChange}>
        <Ionicons
          name={trend === 'up' ? 'arrow-up' : trend === 'down' ? 'arrow-down' : 'remove'}
          size={12}
          color={trend === 'up' ? '#34C759' : trend === 'down' ? '#F87171' : '#94A3B8'}
        />
        <Text style={[
          styles.metricChangeText,
          { color: trend === 'up' ? '#34C759' : trend === 'down' ? '#F87171' : '#94A3B8' }
        ]}>
          {change}
        </Text>
      </View>
    )}
  </View>
);

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function StrategyPerformanceScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('');
  const [selectedPeriod, setSelectedPeriod] = useState<string>('30d');
  const [selectedTimeframe, setSelectedTimeframe] = useState<number | null>(null); // null = todos
  const [performanceData, setPerformanceData] = useState<StrategyPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [indicatorRankings, setIndicatorRankings] = useState<IndicatorCombinationRanking[]>([]);
  const [loadingRankings, setLoadingRankings] = useState(false);
  const [availableTimeframes, setAvailableTimeframes] = useState<number[]>([]);

  const periods = [
    { id: '7d', label: '7 dias' },
    { id: '30d', label: '30 dias' },
    { id: '90d', label: '90 dias' },
    { id: '1y', label: '1 ano' },
  ];

  // Mapeamento de timeframes para labels
  const timeframeLabels: Record<number, string> = {
    60: 'M1',
    300: 'M5',
    900: 'M15',
    1800: 'M30',
    3600: 'H1',
    7200: 'H2',
    14400: 'H4',
    86400: 'D1',
  };

  const fetchStrategies = useCallback(async () => {
    try {
      setError(null);
      setLoading(true);
      const response = await apiClient.get<Array<{ id: string; name: string }>>('/strategies');
      const normalized = response.map((strategy) => ({
        id: strategy.id,
        name: strategy.name,
      }));
      setStrategies(normalized);
      setSelectedStrategy((prev) => {
        if (normalized.length === 0) return '';
        return normalized.some((strategy) => strategy.id === prev)
          ? prev
          : normalized[0].id;
      });
      if (normalized.length === 0) {
        setLoading(false);
      }
    } catch (err) {
      console.error('Erro ao carregar estratégias:', err);
      setError('Não foi possível carregar estratégias');
      setStrategies([]);
      setSelectedStrategy('');
      setPerformanceData([]);
      setLoading(false);
    }
  }, []);

  const fetchPerformance = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!selectedStrategy) {
        setPerformanceData([]);
        if (!options.silent) {
          setLoading(false);
        }
        return;
      }

      if (!options.silent) {
        setLoading(true);
        setError(null);
      }

      try {
        const timeframeParam = selectedTimeframe ? `&timeframe=${selectedTimeframe}` : '';
        const response = await apiClient.get<StrategyPerformanceSnapshotResponse[]>(
          `/strategies/performance?period=${selectedPeriod}&strategy_id=${selectedStrategy}${timeframeParam}`
        );
        const normalized = response.map(normalizePerformance);
        setPerformanceData(normalized);
      } catch (err) {
        console.error('Erro ao carregar desempenho:', err);
        if (!options.silent) {
          setError('Não foi possível carregar o desempenho');
          setPerformanceData([]);
        }
      } finally {
        if (!options.silent) {
          setLoading(false);
        }
      }
    },
    [selectedPeriod, selectedStrategy, selectedTimeframe]
  );

  const handleRetry = useCallback(() => {
    if (strategies.length === 0) {
      fetchStrategies();
    } else {
      fetchPerformance();
    }
  }, [fetchPerformance, fetchStrategies, strategies.length]);

  // Função para definir timeframes disponíveis (mostrar todos os comuns por padrão)
  const loadAvailableTimeframes = useCallback(() => {
    // Mostrar todos os timeframes comuns - o backend filtra automaticamente
    setAvailableTimeframes([60, 300, 900, 1800, 3600, 7200, 14400, 86400]);
  }, []);

  useEffect(() => {
    fetchStrategies();
  }, [fetchStrategies]);

  useEffect(() => {
    fetchPerformance();
  }, [fetchPerformance]);

  useEffect(() => {
    loadAvailableTimeframes();
  }, [loadAvailableTimeframes]);

  const loadIndicatorRankings = async () => {
    setLoadingRankings(true);
    try {
      const timeframeParam = selectedTimeframe ? `&timeframe=${selectedTimeframe}` : '';
      const response = await apiClient.get<{rankings: IndicatorCombinationRanking[]}>(`/trades/indicator-rankings?limit=20${timeframeParam}`);
      setIndicatorRankings(response.rankings || []);
    } catch (err) {
      console.error('Erro ao carregar rankings de indicadores:', err);
    } finally {
      setLoadingRankings(false);
    }
  };

  useEffect(() => {
    loadIndicatorRankings();
  }, [selectedTimeframe]);

  // Polling automático para atualizar dados a cada 30 segundos
  useEffect(() => {
    if (!selectedStrategy) return undefined;
    const interval = setInterval(() => {
      fetchPerformance({ silent: true });
    }, 30000);

    return () => clearInterval(interval);
  }, [fetchPerformance, selectedStrategy]);

  const currentStrategy = useMemo(
    () => performanceData.find((strategy) => strategy.id === selectedStrategy) || null,
    [performanceData, selectedStrategy]
  );

  const formatCurrency = (value: number | undefined | null): string => {
    if (value === undefined || value === null) return 'R$ 0,00';
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
    }).format(value);
  };

  const formatPercentage = (value: number | undefined | null): string => {
    if (value === undefined || value === null) return '0%';
    return `${value.toFixed(1)}%`;
  };

  const mainMetrics = currentStrategy
    ? [
        {
          title: 'Total de Operações',
          value: currentStrategy.totalTrades?.toString() || '0',
          icon: 'bar-chart-outline',
          color: '#7DD3FC',
        },
        {
          title: 'Taxa de Acerto',
          value: formatPercentage(currentStrategy.winRate),
          icon: 'checkmark-circle-outline',
          color: '#34C759',
        },
        {
          title: 'Fator de Lucro',
          value: currentStrategy.profitFactor?.toFixed(2) || 'N/A',
          icon: 'analytics-outline',
          color: '#7DD3FC',
        },
        {
          title: 'Retorno Total',
          value: formatCurrency(currentStrategy.totalProfit),
          icon: 'trending-up-outline',
          color: '#34C759',
        },
      ]
    : [];

  const riskMetrics = currentStrategy
    ? [
        {
          title: 'Drawdown Máximo',
          value: formatPercentage(currentStrategy.maxDrawdown),
          icon: 'trending-down-outline',
          color: '#F87171',
        },
        {
          title: 'Sharpe Ratio',
          value: currentStrategy.sharpeRatio?.toFixed(2) || 'N/A',
          icon: 'pulse-outline',
          color: '#7DD3FC',
        },
        {
          title: 'Ganho Médio',
          value: formatCurrency(currentStrategy.avgWin),
          icon: 'arrow-up-circle-outline',
          color: '#34C759',
        },
        {
          title: 'Perda Média',
          value: formatCurrency(Math.abs(currentStrategy.avgLoss)),
          icon: 'arrow-down-circle-outline',
          color: '#F87171',
        },
      ]
    : [];

  const streakMetrics = currentStrategy
    ? [
        {
          title: 'Maior Sequência de Ganhos',
          value: `${currentStrategy.consecutiveWins} trades`,
          icon: 'trophy-outline',
          color: '#FBBF24',
        },
        {
          title: 'Maior Sequência de Perdas',
          value: `${currentStrategy.consecutiveLosses} trades`,
          icon: 'warning-outline',
          color: '#F87171',
        },
        {
          title: 'Maior Ganho',
          value: formatCurrency(currentStrategy.largestWin),
          icon: 'arrow-up-outline',
          color: '#34C759',
        },
        {
          title: 'Maior Perda',
          value: formatCurrency(Math.abs(currentStrategy.largestLoss)),
          icon: 'arrow-down-outline',
          color: '#F87171',
        },
      ]
    : [];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#7DD3FC" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Desempenho da Estratégia</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading ? (
        <View style={styles.centerState}>
          <ActivityIndicator size="large" color="#7DD3FC" />
          <Text style={styles.stateText}>Carregando desempenho...</Text>
        </View>
      ) : error ? (
        <View style={styles.centerState}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={handleRetry}>
            <Text style={styles.retryButtonText}>Tentar novamente</Text>
          </TouchableOpacity>
        </View>
      ) : !currentStrategy ? (
        <View style={styles.centerState}>
          <Text style={styles.stateText}>Nenhuma estratégia encontrada.</Text>
        </View>
      ) : (
        <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
          <View style={styles.filtersContainer}>
            <View style={styles.filterRow}>
              <Text style={styles.filterLabel}>Estratégia:</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll}>
                <View style={styles.filterButtons}>
                  {strategies.map((strategy) => (
                    <TouchableOpacity
                      key={strategy.id}
                      style={[
                        styles.filterButton,
                        selectedStrategy === strategy.id && styles.filterButtonActive,
                      ]}
                      onPress={() => setSelectedStrategy(strategy.id)}
                    >
                      <Text style={[
                        styles.filterButtonText,
                        selectedStrategy === strategy.id && styles.filterButtonTextActive,
                      ]}>
                        {strategy.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            </View>

            <View style={styles.filterRow}>
              <Text style={styles.filterLabel}>Período:</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll}>
                <View style={styles.filterButtons}>
                  {periods.map((period) => (
                    <TouchableOpacity
                      key={period.id}
                      style={[
                        styles.filterButton,
                        selectedPeriod === period.id && styles.filterButtonActive,
                      ]}
                      onPress={() => setSelectedPeriod(period.id)}
                    >
                      <Text style={[
                        styles.filterButtonText,
                        selectedPeriod === period.id && styles.filterButtonTextActive,
                      ]}>
                        {period.label}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            </View>

            <View style={styles.filterRow}>
              <Text style={styles.filterLabel}>Timeframe:</Text>
              {availableTimeframes.length === 0 ? (
                <Text style={styles.noTimeframesText}>Nenhum timeframe disponível</Text>
              ) : (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll}>
                  <View style={styles.filterButtons}>
                    <TouchableOpacity
                      style={[
                        styles.filterButton,
                        selectedTimeframe === null && styles.filterButtonActive,
                      ]}
                      onPress={() => setSelectedTimeframe(null)}
                    >
                      <Text style={[
                        styles.filterButtonText,
                        selectedTimeframe === null && styles.filterButtonTextActive,
                      ]}>
                        Todos
                      </Text>
                    </TouchableOpacity>
                    {availableTimeframes.map((timeframe) => (
                      <TouchableOpacity
                        key={timeframe}
                        style={[
                          styles.filterButton,
                          selectedTimeframe === timeframe && styles.filterButtonActive,
                        ]}
                        onPress={() => setSelectedTimeframe(timeframe)}
                      >
                        <Text style={[
                          styles.filterButtonText,
                          selectedTimeframe === timeframe && styles.filterButtonTextActive,
                        ]}>
                          {timeframeLabels[timeframe] || `${timeframe}s`}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                </ScrollView>
              )}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Métricas Principais</Text>
            <View style={styles.metricsGrid}>
              {mainMetrics.map((metric, index) => (
                <MetricCard key={index} {...metric} />
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Métricas de Risco</Text>
            <View style={styles.metricsGrid}>
              {riskMetrics.map((metric, index) => (
                <MetricCard key={index} {...metric} />
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Recordes</Text>
            <View style={styles.metricsGrid}>
              {streakMetrics.map((metric, index) => (
                <MetricCard key={index} {...metric} />
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Retorno Mensal (%)</Text>
            <View style={styles.monthlyReturns}>
              {currentStrategy.monthlyReturns.map((return_, index) => (
                <View key={index} style={styles.monthItem}>
                  <Text style={styles.monthLabel}>
                    {['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'][index]}
                  </Text>
                  <Text style={[
                    styles.monthValue,
                    { color: return_ >= 0 ? '#34C759' : '#F87171' }
                  ]}>
                    {return_ >= 0 ? '+' : ''}{(return_ || 0).toFixed(1)}%
                  </Text>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Ranking de Melhores Combinações de Indicadores</Text>
            {loadingRankings ? (
              <View style={styles.loadingContainer}>
                <ActivityIndicator size="small" color={colors.primary} />
                <Text style={styles.loadingText}>Carregando rankings...</Text>
              </View>
            ) : indicatorRankings.length > 0 ? (
              <View style={styles.rankingsList}>
                {indicatorRankings.map((ranking, index) => (
                  <View key={`${ranking.combination}-${index}`} style={styles.rankingItem}>
                    <View style={styles.rankingHeader}>
                      <View style={styles.rankingPosition}>
                        <Text style={styles.rankingPositionText}>#{index + 1}</Text>
                      </View>
                      <View style={styles.rankingInfo}>
                        <Text style={styles.rankingCombination}>{ranking.combination}</Text>
                        <Text style={styles.rankingStats}>
                          {ranking.total_trades} trades • {ranking.winning_trades} wins • {ranking.losing_trades} losses
                        </Text>
                      </View>
                      <View style={styles.rankingMetrics}>
                        <View style={styles.rankingMetric}>
                          <Text style={styles.rankingMetricValue}>{ranking.win_rate.toFixed(0)}%</Text>
                          <Text style={styles.rankingMetricLabel}>Win Rate</Text>
                        </View>
                        <View style={styles.rankingMetric}>
                          <Text style={[
                            styles.rankingMetricValue,
                            { color: ranking.total_profit >= 0 ? '#34C759' : '#FF3B30' }
                          ]}>
                            {ranking.total_profit >= 0 ? '+' : ''}{ranking.total_profit.toFixed(2)}
                          </Text>
                          <Text style={styles.rankingMetricLabel}>Lucro Total</Text>
                        </View>
                      </View>
                    </View>
                  </View>
                ))}
              </View>
            ) : (
              <View style={styles.emptyState}>
                <Ionicons name="analytics-outline" size={48} color={colors.textMuted} />
                <Text style={styles.emptyText}>Nenhum dado de ranking disponível</Text>
                <Text style={styles.emptySubtext}>Execute trades com indicadores para ver o ranking</Text>
              </View>
            )}
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 20,
    paddingTop: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    justifyContent: 'space-between',
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
    color: colors.text,
    fontSize: 18,
    fontWeight: '700',
    flex: 1,
    textAlign: 'center',
  },
  headerSpacer: {
    width: 40,
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
  },
  centerState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  stateText: {
    marginTop: 12,
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
  },
  errorText: {
    fontSize: 14,
    color: colors.danger,
    textAlign: 'center',
    marginBottom: 12,
  },
  retryButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  retryButtonText: {
    fontSize: 12,
    color: colors.text,
    fontWeight: '600',
  },
  filtersContainer: {
    paddingTop: 20,
    marginBottom: 24,
  },
  filterRow: {
    marginBottom: 12,
  },
  filterLabel: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: 8,
    fontWeight: '500',
  },
  filterScroll: {
    flex: 1,
  },
  filterButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  filterButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  filterButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  filterButtonText: {
    fontSize: 12,
    color: colors.textMuted,
    fontWeight: '500',
  },
  filterButtonTextActive: {
    color: colors.primaryText,
  },
  noTimeframesText: {
    fontSize: 12,
    color: colors.textMuted,
    fontStyle: 'italic',
    paddingVertical: 8,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 16,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  metricCard: {
    width: (width - 52) / 2,
    backgroundColor: colors.surfaceAlt,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  metricHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  metricTitle: {
    fontSize: 12,
    color: colors.textMuted,
    fontWeight: '500',
  },
  metricValue: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 4,
  },
  metricChange: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  metricChangeText: {
    fontSize: 11,
    fontWeight: '500',
  },
  tradesList: {
    gap: 8,
  },
  tradeItem: {
    backgroundColor: '#1C1F2A',
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.08)',
  },
  tradeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tradeDate: {
    fontSize: 14,
    color: colors.textMuted,
  },
  tradeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  tradeBadgeText: {
    fontSize: 11,
    fontWeight: '600',
  },
  tradeProfit: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  monthlyReturns: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 0,
  },
  monthItem: {
    width: (width - 40) / 4,
    backgroundColor: colors.surfaceAlt,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    alignItems: 'center',
    height: 80,
    justifyContent: 'center',
  },
  monthLabel: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: 6,
  },
  monthValue: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  loadingContainer: {
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  loadingText: {
    marginTop: 12,
    fontSize: 14,
    color: colors.textMuted,
  },
  emptyState: {
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
  },
  emptyText: {
    marginTop: 12,
    fontSize: 14,
    color: colors.textMuted,
  },
  emptySubtext: {
    marginTop: 4,
    fontSize: 12,
    color: colors.textMuted,
  },
  rankingsList: {
    gap: 12,
  },
  rankingItem: {
    backgroundColor: colors.surfaceAlt,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  rankingHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  rankingPosition: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  rankingPositionText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: 'bold',
  },
  rankingInfo: {
    flex: 1,
  },
  rankingCombination: {
    fontSize: 14,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 4,
  },
  rankingStats: {
    fontSize: 12,
    color: colors.textMuted,
  },
  rankingMetrics: {
    flexDirection: 'row',
    gap: 16,
  },
  rankingMetric: {
    alignItems: 'flex-end',
  },
  rankingMetricValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text,
  },
  rankingMetricLabel: {
    fontSize: 10,
    color: colors.textMuted,
  },
});

