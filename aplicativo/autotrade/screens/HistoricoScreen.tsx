import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/api';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface Trade {
  id: string;
  asset: string;
  direction: 'call' | 'put';
  amount: number;
  entry_price: number | null;
  exit_price: number | null;
  duration: number;
  status: string;
  profit: number | null;
  payout: number | null;
  placed_at: string;
  closed_at: string | null;
  strategy_name?: string;
  connection_type?: 'demo' | 'real';
}

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function HistoricoScreen() {
  useMaintenanceCheck();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [allTrades, setAllTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'win' | 'loss'>('all');
  const [selectedMode, setSelectedMode] = useState<'demo' | 'real'>('demo');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  // Usar refs para evitar loops infinitos
  const selectedModeRef = useRef(selectedMode);
  const filterRef = useRef(filter);

  // Atualizar refs quando os estados mudam
  useEffect(() => {
    selectedModeRef.current = selectedMode;
  }, [selectedMode]);

  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);

  // Memoizar trades para evitar re-renderizações
  const memoizedTrades = useMemo(() => trades, [trades]);

  const fetchTrades = useCallback(async (isInitial: boolean = false, pageNum: number = 1) => {
    try {
      if (isInitial) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);
      const response = await apiClient.get<any>('/trades'); // Corrigir trailing slash
      const items = Array.isArray(response)
        ? response
        : Array.isArray(response?.trades)
        ? response.trades
        : [];

      const normalized: Trade[] = items.map((item: any) => ({
        id: item.id,
        asset: item.symbol || item.asset_symbol || item.asset?.symbol || item.asset || 'N/A',
        direction: item.direction,
        amount: item.amount,
        entry_price: item.entry_price,
        exit_price: item.exit_price,
        duration: item.duration,
        status: item.status,
        profit: item.profit,
        payout: item.payout,
        placed_at: item.entry_time || item.created_at,
        closed_at: item.exit_time,
        strategy_name: item.strategy_name || item.strategy?.name || null,
        connection_type: (item.connection_type || 'demo').toLowerCase(),
      }));

      // Ordenar por placed_at em ordem decrescente (mais recentes primeiro)
      const sortedTrades = normalized.sort((a, b) => {
        const dateA = new Date(a.placed_at).getTime();
        const dateB = new Date(b.placed_at).getTime();
        return dateB - dateA;
      });

      setAllTrades(sortedTrades);

      // Filtrar por modo selecionado
      const modeFiltered = sortedTrades.filter((trade) => trade.connection_type === selectedMode);

      // Paginação: carregar apenas 10 trades por página
      const pageSize = 10;
      const startIndex = (pageNum - 1) * pageSize;
      const paginatedTrades = modeFiltered.slice(startIndex, startIndex + pageSize);

      if (pageNum === 1) {
        setTrades(paginatedTrades);
      } else {
        setTrades(prevTrades => {
          const existingIds = new Set(prevTrades.map(t => t.id));
          const newTrades = paginatedTrades.filter(t => !existingIds.has(t.id));
          return [...prevTrades, ...newTrades];
        });
      }

      setHasMore(startIndex + pageSize < modeFiltered.length);
    } catch (err) {
      setError('Não foi possível carregar o histórico');
      console.error('Erro ao carregar histórico:', err);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [selectedMode]);

  useEffect(() => {
    fetchTrades(true, 1);
  }, [fetchTrades]);

  // Polling para atualizar trades em tempo real (a cada 5 segundos)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchTrades(false, 1);
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchTrades]);

  const handleLoadMore = () => {
    if (!loadingMore && hasMore) {
      const nextPage = page + 1;
      setPage(nextPage);
      fetchTrades(false, nextPage);
    }
  };

  const modeTrades = trades.filter((trade) => trade.connection_type === selectedMode);

  const filteredTrades = modeTrades.filter((trade) => {
    if (filter === 'all') return true;
    if (filter === 'win') return trade.status.toUpperCase() === 'WIN';
    if (filter === 'loss') return trade.status.toUpperCase() === 'LOSS';
    return true;
  });

  const formatCurrency = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    // Remove zeros desnecessários (ex: 0.00 -> 0, 12.50 -> 12.5)
    let formatted = value.toFixed(2).replace(/\.00$/, '').replace(/(\.[1-9])0$/, '$1');
    return `US$ ${formatted}`;
  };

  const formatPrice = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    return value.toFixed(5);
  };

  const formatDate = (dateString?: string | null): string => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return 'N/A';
    return date.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatDuration = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    return `${seconds / 60}m`;
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'WIN':
        return '#34C759';
      case 'LOSS':
        return '#FF3B30';
      case 'CLOSED':
        return '#94A3B8';
      case 'ACTIVE':
        return '#FF9500';
      case 'PENDING':
        return '#FF9500';
      case 'CANCELLED':
        return '#8E8E93';
      default:
        return '#94A3B8';
    }
  };

  const getStatusIcon = (status: string): string => {
    switch (status) {
      case 'WIN':
        return 'checkmark-circle';
      case 'LOSS':
        return 'close-circle';
      case 'CLOSED':
        return 'time';
      case 'ACTIVE':
        return 'flash';
      case 'PENDING':
        return 'hourglass';
      case 'CANCELLED':
        return 'close';
      default:
        return 'help-circle';
    }
  };

  const totalTrades = modeTrades.length;
  const winTrades = modeTrades.filter((t) => t.status === 'WIN').length;
  const loseTrades = modeTrades.filter((t) => t.status === 'LOSS').length;
  const winRate = totalTrades > 0 ? ((winTrades / totalTrades) * 100).toFixed(0) : '0';
  const totalProfit = modeTrades.reduce((sum, t) => sum + (t.profit || 0), 0);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView 
        style={styles.content} 
        contentContainerStyle={styles.scrollContainer}
        onScroll={({ nativeEvent }) => {
          const { layoutMeasurement, contentOffset, contentSize } = nativeEvent;
          const paddingToBottom = 50;
          const isCloseToBottom = layoutMeasurement.height + contentOffset.y >= contentSize.height - paddingToBottom;
          if (isCloseToBottom && !loadingMore && hasMore) {
            handleLoadMore();
          }
        }}
        scrollEventThrottle={100}
      >
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Histórico de Operações</Text>
          <Text style={styles.headerSubtitle}>
            Visualize seus trades em contas
          </Text>
        </View>

        <View style={styles.modeSelectorCard}>
          <TouchableOpacity
            style={[styles.modeSelectorButton, selectedMode === 'demo' && styles.modeSelectorButtonSelected]}
            onPress={() => setSelectedMode('demo')}
          >
            <Text style={[styles.modeSelectorText, selectedMode === 'demo' && styles.modeSelectorTextSelected]}>
              DEMO
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.modeSelectorButton, selectedMode === 'real' && styles.modeSelectorButtonSelected]}
            onPress={() => setSelectedMode('real')}
          >
            <Text style={[styles.modeSelectorText, selectedMode === 'real' && styles.modeSelectorTextSelected]}>
              REAL
            </Text>
          </TouchableOpacity>
        </View>

        {/* Filters */}
        <View style={styles.filterRow}>
          <TouchableOpacity
            style={[styles.filterPill, filter === 'all' && styles.filterPillActive]}
            onPress={() => setFilter('all')}
          >
            <Text style={[styles.filterText, filter === 'all' && styles.filterTextActive]}>Todas</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.filterPill, filter === 'win' && styles.filterPillActive]}
            onPress={() => setFilter('win')}
          >
            <Text style={[styles.filterText, filter === 'win' && styles.filterTextActive]}>WIN</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.filterPill, filter === 'loss' && styles.filterPillActive]}
            onPress={() => setFilter('loss')}
          >
            <Text style={[styles.filterText, filter === 'loss' && styles.filterTextActive]}>LOSS</Text>
          </TouchableOpacity>
        </View>

        {/* Loading State */}
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#7DD3FC" />
            <Text style={styles.loadingText}>Carregando histórico...</Text>
          </View>
        ) : error ? (
          <View style={styles.loadingContainer}>
            <Ionicons name="warning" size={28} color="#F87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : filteredTrades.length === 0 ? (
          <View style={styles.emptyState}>
            <Ionicons name="list-outline" size={48} color="#2F3B52" />
            <Text style={styles.emptyTitle}>Nenhum trade encontrado</Text>
            <Text style={styles.emptySubtitle}>Nenhuma operação realizada ainda</Text>
          </View>
        ) : (
          filteredTrades.map((trade) => (
            <View key={trade.id} style={styles.tradeCard}>
              <View style={styles.tradeHeader}>
                <View style={styles.tradeAssetRow}>
                  <Text style={styles.tradeAsset}>{trade.asset}</Text>
                  <View
                    style={[
                      styles.statusBadge,
                      trade.status === 'win' ? styles.winBadge :
                      trade.status === 'loss' ? styles.loseBadge :
                      trade.status === 'closed' ? styles.closedBadge :
                      trade.status === 'active' ? styles.activeBadge :
                      styles.pendingBadge,
                    ]}
                  >
                    <Ionicons
                      name={trade.status === 'win' ? 'checkmark-circle' :
                            trade.status === 'loss' ? 'close-circle' :
                            trade.status === 'closed' ? 'time' :
                            trade.status === 'active' ? 'flash' :
                            'time-outline'}
                      size={16}
                      color={trade.status === 'win' ? '#4ADE80' :
                             trade.status === 'loss' ? '#F87171' :
                             trade.status === 'closed' ? '#94A3B8' :
                             trade.status === 'active' ? '#FBBF24' :
                             '#FBBF24'}
                    />
                    <Text
                      style={trade.status === 'win' ? styles.winText :
                             trade.status === 'loss' ? styles.loseText :
                             trade.status === 'closed' ? styles.closedText :
                             trade.status === 'active' ? styles.activeText :
                             styles.pendingText}
                    >
                      {trade.status}
                    </Text>
                  </View>
                </View>
                <Text style={styles.tradeDate}>{formatDate(trade.placed_at)}</Text>
              </View>

              <View style={styles.tradeBody}>
                <View style={styles.tradeRow}>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Direção</Text>
                    <Text style={[styles.tradeValue, trade.direction === 'call' && styles.callText, trade.direction === 'put' && styles.putText]}>
                      {trade.direction.toUpperCase()}
                    </Text>
                  </View>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Valor</Text>
                    <Text style={styles.tradeValue}>{formatCurrency(trade.amount)}</Text>
                  </View>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Duração</Text>
                    <Text style={styles.tradeValue}>{formatDuration(trade.duration)}</Text>
                  </View>
                </View>

                <View style={styles.tradeRow}>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Entrada</Text>
                    <Text style={styles.tradeValue}>{formatPrice(trade.entry_price)}</Text>
                  </View>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Saída</Text>
                    <Text style={styles.tradeValue}>{formatPrice(trade.exit_price)}</Text>
                  </View>
                  <View style={styles.tradeInfo}>
                    <Text style={styles.tradeLabel}>Lucro</Text>
                    <Text
                      style={[
                        styles.tradeValue,
                        { color: trade.profit && trade.profit >= 0 ? '#34C759' : '#FF3B30' },
                      ]}
                    >
                      {formatCurrency(trade.profit)}
                    </Text>
                  </View>
                </View>

                {trade.payout !== null && trade.payout !== undefined && (
                  <View style={styles.tradeRow}>
                    <View style={styles.tradeInfo}>
                      <Text style={styles.tradeLabel}>Payout</Text>
                      <Text style={styles.tradeValue}>{trade.payout ? trade.payout.toFixed(0) + '%' : 'N/A'}</Text>
                    </View>
                    {Boolean(trade.strategy_name) && (
                      <View style={styles.tradeInfo}>
                        <Text style={styles.tradeLabel}>Estratégia</Text>
                        <Text style={styles.tradeValue}>{trade.strategy_name}</Text>
                      </View>
                    )}
                  </View>
                )}

                {Boolean(trade.closed_at) && (
                  <View style={styles.tradeRow}>
                    <View style={styles.tradeInfo}>
                      <Text style={styles.tradeLabel}>Fechado em</Text>
                      <Text style={styles.tradeValue}>{formatDate(trade.closed_at)}</Text>
                    </View>
                  </View>
                )}
              </View>
            </View>
          ))
        )}
        
        {loadingMore && (
          <View style={styles.loadingMoreContainer}>
            <ActivityIndicator size="small" color="#7DD3FC" />
            <Text style={styles.loadingMoreText}>Carregando mais...</Text>
          </View>
        )}
        
        {hasMore && !loadingMore && (
          <TouchableOpacity 
            style={styles.loadMoreButton}
            onPress={handleLoadMore}
          >
            <Text style={styles.loadMoreButtonText}>Carregar mais trades</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    paddingTop: 0,
  },
  content: {
    flex: 1,
    paddingTop: 0,
  },
  scrollContainer: {
    padding: 20,
    paddingTop: 0,
  },
  header: {
    marginBottom: 16,
  },
  headerTitle: {
    color: colors.text,
    fontSize: 22,
    fontWeight: '700',
    marginBottom: 6,
  },
  headerSubtitle: {
    color: colors.textMuted,
    fontSize: 13,
  },
  modeSelectorCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    flexDirection: 'row',
    marginBottom: 16,
    overflow: 'hidden',
    height: 48,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modeSelectorButton: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modeSelectorButtonSelected: {
    backgroundColor: colors.primary,
  },
  modeSelectorText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#657089',
    letterSpacing: 0.8,
  },
  modeSelectorTextSelected: {
    color: colors.primaryText,
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 20,
  },
  filterPill: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.surfaceAlt,
    marginRight: 10,
    marginBottom: 10,
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
    marginTop: 12,
  },
  loadingMoreContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 16,
  },
  loadingMoreText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  loadMoreButton: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  loadMoreButtonText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '600',
  },
  errorText: {
    color: colors.danger,
    fontSize: 14,
    textAlign: 'center',
  },
  emptyState: {
    padding: 32,
    alignItems: 'center',
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
    marginTop: 8,
  },
  emptySubtitle: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 4,
  },
  tradeCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 16,
  },
  tradeHeader: {
    marginBottom: 16,
  },
  tradeAssetRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tradeAsset: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
  },
  winBadge: {
    backgroundColor: 'rgba(34, 197, 94, 0.4)',
    borderWidth: 1,
    borderColor: 'rgba(34, 197, 94, 0.6)',
  },
  loseBadge: {
    backgroundColor: 'rgba(239, 68, 68, 0.4)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.6)',
  },
  closedBadge: {
    backgroundColor: 'rgba(148, 163, 184, 0.2)',
    borderWidth: 1,
    borderColor: 'rgba(148, 163, 184, 0.3)',
  },
  activeBadge: {
    backgroundColor: 'rgba(251, 191, 36, 0.2)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.3)',
  },
  pendingBadge: {
    backgroundColor: 'rgba(251, 191, 36, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.3)',
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    marginLeft: 8,
  },
  winText: {
    color: '#22C55E',
    fontSize: 12,
    fontWeight: '600',
  },
  loseText: {
    color: '#EF4444',
    fontSize: 12,
    fontWeight: '600',
  },
  closedText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '600',
  },
  activeText: {
    color: colors.warning,
    fontSize: 12,
    fontWeight: '600',
  },
  pendingText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '600',
  },
  tradeDate: {
    color: colors.textSoft,
    fontSize: 12,
  },
  tradeBody: {
    gap: 16,
  },
  tradeRow: {
    flexDirection: 'row',
  },
  tradeInfo: {
    flex: 1,
    marginRight: 16,
  },
  tradeLabel: {
    color: colors.textMuted,
    fontSize: 11,
    marginBottom: 2,
  },
  tradeValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '500',
  },
  callText: {
    color: '#34C759',
  },
  putText: {
    color: '#FF3B30',
  },
});
