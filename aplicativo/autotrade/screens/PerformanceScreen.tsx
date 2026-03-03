import React, { useState, useEffect } from 'react';
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
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';
import { apiClient, IndicatorCombinationRanking } from '../services/api';
import { statsService } from '../services/stats';

const { width } = Dimensions.get('window');

interface PerformanceMetric {
  id: string;
  title: string;
  value: string;
  change: string;
  trend: 'up' | 'down' | 'neutral';
  icon: string;
}

interface Trade {
  id: string;
  date: string;
  asset: string;
  type: 'COMPRA' | 'VENDA';
  result: 'LUCRO' | 'PREJUÍZO';
  value: string;
  percentage: string;
}

export default function PerformanceScreen() {
  const [selectedPeriod, setSelectedPeriod] = useState<string>('30d');
  const [selectedTimeframe, setSelectedTimeframe] = useState<number | null>(null); // null = todos
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [performanceMetrics, setPerformanceMetrics] = useState<PerformanceMetric[]>([]);
  const [indicatorRankings, setIndicatorRankings] = useState<IndicatorCombinationRanking[]>([]);
  const [loadingRankings, setLoadingRankings] = useState(false);

  const periods = [
    { id: '7d', label: '7 dias' },
    { id: '30d', label: '30 dias' },
    { id: '90d', label: '90 dias' },
    { id: '1y', label: '1 ano' },
  ];

  const timeframes = [
    { id: null, label: 'Todos', seconds: 0 },
    { id: 60, label: 'M1', seconds: 60 },
    { id: 300, label: 'M5', seconds: 300 },
    { id: 900, label: 'M15', seconds: 900 },
    { id: 1800, label: 'M30', seconds: 1800 },
    { id: 3600, label: 'H1', seconds: 3600 },
  ];

  useEffect(() => {
    loadPerformanceData();
  }, [selectedPeriod, selectedTimeframe]);

  useEffect(() => {
    loadIndicatorRankings();
  }, [selectedTimeframe]);

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

  const loadPerformanceData = async () => {
    setLoading(true);
    setError(null);
    try {
      // Carregar estatísticas do usuário
      const userStats = await statsService.getUserStats();
      setStats(userStats);

      // Carregar trades recentes com filtro de timeframe
      const timeframeParam = selectedTimeframe ? `&timeframe=${selectedTimeframe}` : '';
      const tradesData = await apiClient.get<any[]>(`/trades?limit=10${timeframeParam}`);
      setTrades(tradesData.map((trade: any) => ({
        id: trade.id,
        date: new Date(trade.placed_at).toLocaleDateString('pt-BR'),
        asset: trade.asset_symbol || 'N/A',
        type: trade.direction === 'CALL' ? 'COMPRA' : 'VENDA',
        result: trade.profit > 0 ? 'LUCRO' : 'PREJUÍZO',
        value: trade.profit ? `US$ ${Math.abs(trade.profit).toFixed(2)}` : 'US$ 0.00',
        percentage: trade.profit ? `${trade.profit > 0 ? '+' : ''}${(trade.profit / trade.amount * 100).toFixed(1)}%` : '0.0%',
      })));

      // Calcular métricas de performance
      const totalTrades = userStats.total_trades_demo + userStats.total_trades_real;
      const winRate = totalTrades > 0 ? ((userStats.win_rate_demo + userStats.win_rate_real) / 2) : 0;
      const profitFactor = 0; // UserStats não tem total_profit/total_loss, usar valor padrão

      setPerformanceMetrics([
        {
          id: '1',
          title: 'Retorno Total',
          value: `${((userStats.lucro_hoje + userStats.lucro_semana) / 100).toFixed(1)}%`,
          change: '+2.3%',
          trend: 'up',
          icon: 'trending-up-outline',
        },
        {
          id: '2',
          title: 'Taxa de Acerto',
          value: `${winRate.toFixed(1)}%`,
          change: '+1.2%',
          trend: 'up',
          icon: 'checkmark-circle-outline',
        },
        {
          id: '3',
          title: 'Fator de Lucro',
          value: profitFactor.toFixed(2),
          change: '+0.05',
          trend: 'up',
          icon: 'analytics-outline',
        },
        {
          id: '4',
          title: 'Drawdown Máximo',
          value: '-8.3%',
          change: '-0.5%',
          trend: 'neutral',
          icon: 'trending-down-outline',
        },
      ]);
    } catch (err: any) {
      console.error('[PerformanceScreen] Erro ao carregar dados:', err);
      setError('Erro ao carregar dados de performance. Tente novamente.');
    } finally {
      setLoading(false);
    }
  };

  const renderMetric = (metric: PerformanceMetric) => (
    <View key={metric.id} style={styles.metricCard}>
      <View style={styles.metricHeader}>
        <Ionicons 
          name={metric.icon as any} 
          size={24} 
          color="#6366f1" 
        />
        <Text style={styles.metricTitle}>{metric.title}</Text>
      </View>
      <Text style={styles.metricValue}>{metric.value}</Text>
      <View style={styles.metricChange}>
        <Ionicons 
          name={metric.trend === 'up' ? 'arrow-up' : metric.trend === 'down' ? 'arrow-down' : 'remove'} 
          size={12} 
          color={metric.trend === 'up' ? '#10b981' : metric.trend === 'down' ? '#ef4444' : '#6b7280'} 
        />
        <Text style={[
          styles.metricChangeText,
          { color: metric.trend === 'up' ? '#10b981' : metric.trend === 'down' ? '#ef4444' : '#6b7280' }
        ]}>
          {metric.change}
        </Text>
      </View>
    </View>
  );

  const renderTrade = (trade: Trade) => (
    <View key={trade.id} style={styles.tradeItem}>
      <View style={styles.tradeHeader}>
        <Text style={styles.tradeDate}>{trade.date}</Text>
        <Text style={[
          styles.tradeResult,
          { color: trade.result === 'LUCRO' ? '#10b981' : '#ef4444' }
        ]}>
          {trade.result}
        </Text>
      </View>
      <View style={styles.tradeDetails}>
        <Text style={styles.tradeAsset}>{trade.asset}</Text>
        <Text style={styles.tradeType}>{trade.type}</Text>
        <Text style={[
          styles.tradeValue,
          { color: trade.result === 'LUCRO' ? '#10b981' : '#ef4444' }
        ]}>
          {trade.value}
        </Text>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Performance</Text>
        <View style={styles.periodSelector}>
          {periods.map((period) => (
            <TouchableOpacity
              key={period.id}
              style={[
                styles.periodButton,
                selectedPeriod === period.id && styles.periodButtonActive,
              ]}
              onPress={() => setSelectedPeriod(period.id)}
              disabled={loading}
            >
              <Text style={[
                styles.periodButtonText,
                selectedPeriod === period.id && styles.periodButtonTextActive,
              ]}>
                {period.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.timeframeSelector}>
          {timeframes.map((timeframe) => (
            <TouchableOpacity
              key={timeframe.label}
              style={[
                styles.timeframeButton,
                selectedTimeframe === timeframe.id && styles.timeframeButtonActive,
              ]}
              onPress={() => setSelectedTimeframe(timeframe.id)}
              disabled={loading}
            >
              <Text style={[
                styles.timeframeButtonText,
                selectedTimeframe === timeframe.id && styles.timeframeButtonTextActive,
              ]}>
                {timeframe.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>Carregando dados de performance...</Text>
        </View>
      ) : error ? (
        <View style={styles.errorContainer}>
          <Ionicons name="alert-circle-outline" size={48} color="#EF4444" />
          <Text style={styles.errorTitle}>Erro ao carregar dados</Text>
          <Text style={styles.errorMessage}>{error}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={loadPerformanceData}>
            <Text style={styles.retryButtonText}>Tentar novamente</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
          <View style={styles.metricsGrid}>
            {performanceMetrics.map(renderMetric)}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Operações Recentes</Text>
            {trades.length > 0 ? (
              <View style={styles.tradesList}>
                {trades.map(renderTrade)}
              </View>
            ) : (
              <View style={styles.emptyState}>
                <Ionicons name="document-outline" size={48} color={colors.textMuted} />
                <Text style={styles.emptyText}>Nenhuma operação registrada</Text>
              </View>
            )}
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
    padding: 20,
    paddingBottom: 10,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 16,
  },
  periodSelector: {
    flexDirection: 'row',
    gap: 8,
  },
  periodButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  periodButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  periodButtonText: {
    fontSize: 12,
    color: colors.textMuted,
    fontWeight: '500',
  },
  periodButtonTextActive: {
    color: colors.primaryText,
  },
  timeframeSelector: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 12,
  },
  timeframeButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  timeframeButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  timeframeButtonText: {
    fontSize: 11,
    color: colors.textMuted,
    fontWeight: '500',
  },
  timeframeButtonTextActive: {
    color: colors.primaryText,
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 24,
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
    fontSize: 14,
    color: colors.textMuted,
    fontWeight: '500',
  },
  metricValue: {
    fontSize: 24,
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
    fontSize: 12,
    fontWeight: '500',
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
  tradesList: {
    gap: 12,
  },
  tradeItem: {
    backgroundColor: colors.surfaceAlt,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
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
  tradeResult: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  tradeDetails: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tradeAsset: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text,
  },
  tradeType: {
    fontSize: 14,
    color: colors.textSoft,
  },
  tradeValue: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: colors.textMuted,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text,
    marginTop: 16,
  },
  errorMessage: {
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 8,
    textAlign: 'center',
  },
  retryButton: {
    marginTop: 20,
    paddingHorizontal: 24,
    paddingVertical: 12,
    backgroundColor: colors.primary,
    borderRadius: 8,
  },
  retryButtonText: {
    color: colors.primaryText,
    fontSize: 14,
    fontWeight: 'bold',
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
