import React, { useState, useEffect, useCallback, memo, useMemo, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, TouchableOpacity, Modal } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/api';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

type SignalDirection = 'buy' | 'sell' | 'hold' | 'BUY' | 'SELL' | 'HOLD';

interface Indicator {
  type: string;
  name?: string;
  value?: number;
  confidence?: number;
  signal?: SignalDirection;
  parameters?: Record<string, any>;
  result?: Record<string, any>;
}

interface Signal {
  id: string;
  strategy_id: string;
  strategy_name?: string;
  asset_id: number;
  asset_name?: string;
  timeframe: number;
  signal_type: SignalDirection;
  confidence: number;
  price: number;
  indicators?: Indicator[];
  is_executed: boolean;
  trade_id?: string;
  created_at: string;
  executed_at?: string;
}

interface SignalsListResponse {
  signals: Signal[];
}

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

// Componente de card de sinal memoizado para evitar re-renderizações
const SignalCard = memo(({ signal, onPress, key }: { signal: Signal; onPress: () => void; key: string }) => {
  const isBuyDirection = (value?: SignalDirection): boolean => {
    if (!value) return false;
    return value.toString().toUpperCase() === 'BUY';
  };

  const isSellDirection = (value?: SignalDirection): boolean => {
    if (!value) return false;
    return value.toString().toUpperCase() === 'SELL';
  };

  const normalizeDirection = (value?: SignalDirection): string => {
    if (!value) return '';
    return value.toString().toUpperCase();
  };

  const formatPrice = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    return value.toFixed(5);
  };

  const formatDate = (dateString: string): string => {
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

  const formatTimeframe = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    return `${seconds / 60}m`;
  };

  const formatIndicatorSummary = (indicators?: Indicator[]): string => {
    if (!indicators || indicators.length === 0) return '';
    const names = indicators
      .map((indicator) => indicator.name || indicator.type)
      .filter(Boolean) as string[];
    if (names.length === 0) return '';

    const preview = names.slice(0, 3);
    const remaining = names.length - preview.length;
    return `${preview.join(', ')}${remaining > 0 ? ` +${remaining}` : ''}`;
  };

  return (
    <TouchableOpacity
      style={styles.signalCard}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <View style={styles.signalHeader}>
        <View style={styles.signalAssetRow}>
          <Text style={styles.signalAsset}>{signal.asset_name || `Ativo #${signal.asset_id}`}</Text>
          <View
            style={[
              styles.statusBadge,
              signal.is_executed ? styles.executedBadge : styles.pendingBadge
            ]}
          >
            <Text style={[styles.statusText, signal.is_executed ? styles.executedText : styles.pendingText]}>
              {signal.is_executed ? 'Executado' : 'Pendente'}
            </Text>
          </View>
        </View>
        <Text style={styles.signalDate}>{formatDate(signal.created_at)}</Text>
      </View>

      <View style={styles.signalBody}>
        <View style={styles.signalRow}>
          <View style={styles.signalInfo}>
            <Text style={styles.signalLabel}>Direção</Text>
            <Text style={[
              styles.signalValue,
              isBuyDirection(signal.signal_type)
                ? styles.buyText
                : isSellDirection(signal.signal_type)
                ? styles.sellText
                : {}
            ]}>
              {normalizeDirection(signal.signal_type) || '-'}
            </Text>
          </View>
          <View style={styles.signalInfo}>
            <Text style={styles.signalLabel}>Confiança</Text>
            <Text style={styles.signalValue}>{((signal.confidence || 0) * 100).toFixed(0)}%</Text>
          </View>
          <View style={styles.signalInfo}>
            <Text style={styles.signalLabel}>Timeframe</Text>
            <Text style={styles.signalValue}>{formatTimeframe(signal.timeframe)}</Text>
          </View>
        </View>

        <View style={styles.signalRow}>
          <View style={styles.signalInfo}>
            <Text style={styles.signalLabel}>Preço</Text>
            <Text style={styles.signalValue}>{formatPrice(signal.price)}</Text>
          </View>
          <View style={styles.signalInfo}>
            <Text style={styles.signalLabel}>Estratégia</Text>
            <Text style={styles.signalValue}>{signal.strategy_name || signal.strategy_id}</Text>
          </View>
        </View>

        {signal.indicators && signal.indicators.length > 0 && (
          <View style={styles.indicatorsSection}>
            <Text style={styles.indicatorsTitle}>Indicadores:</Text>
            <Text style={styles.indicatorText}>
              {formatIndicatorSummary(signal.indicators)}
            </Text>
          </View>
        )}
      </View>
    </TouchableOpacity>
  );
});

SignalCard.displayName = 'SignalCard';

export default function SinaisScreen() {
  useMaintenanceCheck();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [currentSignal, setCurrentSignal] = useState<Signal | null>(null);
  const [pastSignals, setPastSignals] = useState<Signal[]>([]);
  const [totalPastSignals, setTotalPastSignals] = useState(0);
  const [expandedIndicators, setExpandedIndicators] = useState<Set<number>>(new Set());

  // Usar refs para evitar loops infinitos
  const currentSignalRef = useRef(currentSignal);
  const pastSignalsRef = useRef(pastSignals);

  // Atualizar refs quando os estados mudam
  useEffect(() => {
    currentSignalRef.current = currentSignal;
  }, [currentSignal]);

  useEffect(() => {
    pastSignalsRef.current = pastSignals;
  }, [pastSignals]);

  // Memoizar pastSignals para evitar re-renderizações
  const memoizedPastSignals = useMemo(() => pastSignals, [pastSignals]);
  const memoizedCurrentSignal = useMemo(() => currentSignal, [currentSignal]);

  const fetchSignals = useCallback(async (isInitial: boolean = false, pageNum: number = 1) => {
    try {
      if (isInitial) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);
      
      const response = await apiClient.get<SignalsListResponse>('/signals');
      const allSignals = response.signals || [];

      // Ordenar por created_at em ordem decrescente
      const sortedSignals = allSignals.sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA;
      });

      // Deduplicar sinais pelo ID
      const uniqueSignalsMap = new Map<string, Signal>();
      sortedSignals.forEach(signal => {
        if (signal.id) {
          uniqueSignalsMap.set(signal.id, signal);
        }
      });
      const uniqueSignals = Array.from(uniqueSignalsMap.values());

      // Verificar se há novo sinal
      const newCurrent = uniqueSignals[0];
      const oldCurrentId = currentSignalRef.current?.id;
      const hasNewSignal = newCurrent && newCurrent.id !== oldCurrentId;

      // Atualizar total de sinais passados
      const past = uniqueSignals.slice(1);
      setTotalPastSignals(past.length);

      // Paginação: carregar apenas 10 sinais por página
      const pageSize = 10;
      const startIndex = (pageNum - 1) * pageSize;
      const paginatedPast = past.slice(startIndex, startIndex + pageSize);

      setCurrentSignal(newCurrent);

      // Sempre atualizar pastSignals (removido verificação que impedia atualizações)
      if (hasNewSignal && oldCurrentId) {
        // Mover o atual antigo para o topo do passado e atualizar com novos sinais
        setPastSignals(prev => {
          const existingIds = new Set(prev.map(s => s.id));
          // Adicionar o atual antigo no topo e novos sinais do servidor
          const newPast = currentSignalRef.current ? [currentSignalRef.current, ...paginatedPast.filter(s => !existingIds.has(s.id))] : paginatedPast.filter(s => !existingIds.has(s.id));
          return newPast;
        });
      } else {
        setPastSignals(paginatedPast);
      }

      setHasMore(startIndex + pageSize < past.length);
    } catch (err) {
      setError('Não foi possível carregar os sinais');
      console.error('Erro ao carregar sinais:', err);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals(true, 1);
  }, [fetchSignals]);

  // Polling para atualizar sinais em tempo real (a cada 5 segundos)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchSignals(false, 1);
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchSignals]);

  const handleLoadMore = () => {
    if (!loadingMore && hasMore) {
      const nextPage = page + 1;
      setPage(nextPage);
      fetchSignals(false, nextPage);
    }
  };

  const handleSignalPress = (signal: Signal) => {
    setSelectedSignal(signal);
    setModalVisible(true);
  };

  const formatIndicatorSummary = (indicators?: Indicator[]): string => {
    if (!indicators || indicators.length === 0) return '';
    const names = indicators
      .map((indicator) => indicator.name || indicator.type)
      .filter(Boolean) as string[];
    if (names.length === 0) return '';

    const preview = names.slice(0, 3);
    const remaining = names.length - preview.length;
    return `${preview.join(', ')}${remaining > 0 ? ` +${remaining}` : ''}`;
  };

  const closeModal = () => {
    setModalVisible(false);
    setSelectedSignal(null);
  };

  const formatPrice = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return 'N/A';
    return value.toFixed(5);
  };

  const formatDate = (dateString: string): string => {
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

  const formatTimeframe = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    return `${seconds / 60}m`;
  };

  const normalizeDirection = (value?: SignalDirection): string => {
    if (!value) return '';
    return value.toString().toUpperCase();
  };

  const isBuyDirection = (value?: SignalDirection): boolean => normalizeDirection(value) === 'BUY';

  const isSellDirection = (value?: SignalDirection): boolean => normalizeDirection(value) === 'SELL';

  // Contar sinais BUY e SELL dos indicadores
  const countIndicatorSignals = (indicators?: Indicator[]) => {
    if (!indicators || indicators.length === 0) {
      return { buy: 0, sell: 0, total: 0 };
    }
    
    let buyCount = 0;
    let sellCount = 0;
    
    indicators.forEach(indicator => {
      const signal = normalizeDirection(indicator.signal);
      if (signal === 'BUY') {
        buyCount++;
      } else if (signal === 'SELL') {
        sellCount++;
      }
    });
    
    return {
      buy: buyCount,
      sell: sellCount,
      total: indicators.length
    };
  };

  const formatMetricLabel = (label: string): string => {
    return label
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  const formatMetricValue = (value: any): string => {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'boolean') return value ? 'Sim' : 'Não';
    if (typeof value === 'number') {
      const fixed = Math.abs(value) >= 1 ? value.toFixed(4) : value.toFixed(6);
      return fixed.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
    }
    if (typeof value === 'string') return value;
    return JSON.stringify(value);
  };

  const renderKeyValueTable = (title: string, data?: Record<string, any>) => {
    if (!data || Object.keys(data).length === 0) return null;

    return (
      <View style={styles.tableSection}>
        <Text style={styles.tableTitle}>{title}</Text>
        <View style={styles.tableContainer}>
          <View style={styles.tableHeaderRow}>
            <Text style={styles.tableHeaderCell}>Métrica</Text>
            <Text style={styles.tableHeaderCell}>Valor</Text>
          </View>
          {Object.entries(data).map(([key, value], index) => (
            <View
              key={`${key}-${index}`}
              style={[styles.tableRow, index % 2 === 1 && styles.tableRowAlt]}
            >
              <Text style={styles.tableCellLabel}>{formatMetricLabel(key)}</Text>
              <Text style={styles.tableCellValue}>{formatMetricValue(value)}</Text>
            </View>
          ))}
        </View>
      </View>
    );
  };

  const renderIndicatorDetails = (indicator: Indicator, index: number, signalId?: string) => {
    const isExpanded = expandedIndicators.has(index);
    const indicatorSignal = normalizeDirection(indicator.signal);

    const toggleExpand = () => {
      setExpandedIndicators(prev => {
        const newSet = new Set(prev);
        if (newSet.has(index)) {
          newSet.delete(index);
        } else {
          newSet.add(index);
        }
        return newSet;
      });
    };

    return (
      <View key={`${signalId || 'signal'}-indicator-${index}`} style={styles.indicatorDetailCard}>
        <TouchableOpacity
          style={styles.indicatorDetailHeader}
          onPress={toggleExpand}
          activeOpacity={0.7}
        >
          <View style={styles.indicatorDetailHeaderLeft}>
            <Text style={styles.indicatorDetailName}>{indicator.name || indicator.type || 'Indicador'}</Text>
            <Text style={styles.indicatorDetailType}>{indicator.type}</Text>
          </View>
          <Ionicons
            name={isExpanded ? 'chevron-up' : 'chevron-down'}
            size={20}
            color={colors.primary}
          />
        </TouchableOpacity>

        {isExpanded && (
          <>
            {indicator.value !== undefined && (
              <View style={styles.indicatorDetailRow}>
                <Text style={styles.indicatorDetailLabel}>Valor:</Text>
                <Text style={styles.indicatorDetailValue}>{typeof indicator.value === 'number' ? (indicator.value || 0).toFixed(4) : indicator.value}</Text>
              </View>
            )}

            {indicator.confidence !== undefined && (
              <View style={styles.indicatorDetailRow}>
                <Text style={styles.indicatorDetailLabel}>Confiança:</Text>
                <Text style={styles.indicatorDetailValue}>{((indicator.confidence || 0) * 100).toFixed(1)}%</Text>
              </View>
            )}

            {indicatorSignal && (
              <View style={styles.indicatorDetailRow}>
                <Text style={styles.indicatorDetailLabel}>Sinal:</Text>
                <Text style={[
                  styles.indicatorDetailValue,
                  isBuyDirection(indicator.signal) ? styles.buyText : isSellDirection(indicator.signal) ? styles.sellText : {}
                ]}>
                  {indicatorSignal}
                </Text>
              </View>
            )}

            {renderKeyValueTable('Parâmetros', indicator.parameters)}
            {renderKeyValueTable('Resultados', indicator.result)}
          </>
        )}
      </View>
    );
  };

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
        {/* Header com título e descrição */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Sinais de Trading</Text>
          <Text style={styles.headerSubtitle}>
            Visualize os sinais executados pelas estratégias
          </Text>
        </View>

        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#7DD3FC" />
            <Text style={styles.loadingText}>Carregando sinais...</Text>
          </View>
        ) : error ? (
          <View style={styles.loadingContainer}>
            <Ionicons name="warning" size={28} color="#F87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : !currentSignal && pastSignals.length === 0 ? (
          <View style={styles.emptyState}>
            <Ionicons name="list-outline" size={48} color="#2F3B52" />
            <Text style={styles.emptyTitle}>Nenhum sinal encontrado</Text>
            <Text style={styles.emptySubtitle}>Nenhum sinal foi gerado ainda</Text>
          </View>
        ) : (
          <>
            {/* Seção Atual */}
            {currentSignal && (
              <View style={styles.section}>
                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Atual</Text>
                  <View style={styles.sectionBadge}>
                    <Text style={styles.sectionBadgeText}>1</Text>
                  </View>
                </View>
                <TouchableOpacity
                  key={`current-signal-${currentSignal.id || 'current-signal'}`}
                  style={styles.signalCard}
                  onPress={() => handleSignalPress(currentSignal)}
                  activeOpacity={0.7}
                >
                  <View style={styles.signalHeader}>
                    <View style={styles.signalAssetRow}>
                      <Text style={styles.signalAsset}>{currentSignal.asset_name || `Ativo #${currentSignal.asset_id}`}</Text>
                      <View
                        style={[
                          styles.statusBadge,
                          currentSignal.is_executed ? styles.executedBadge : styles.pendingBadge
                        ]}
                      >
                        <Text style={[styles.statusText, currentSignal.is_executed ? styles.executedText : styles.pendingText]}>
                          {currentSignal.is_executed ? 'Executado' : 'Pendente'}
                        </Text>
                      </View>
                    </View>
                    <Text style={styles.signalDate}>{formatDate(currentSignal.created_at)}</Text>
                  </View>

                  <View style={styles.signalBody}>
                    <View style={styles.signalRow}>
                      <View style={styles.signalInfo}>
                        <Text style={styles.signalLabel}>Direção</Text>
                        <Text style={[
                          styles.signalValue,
                          isBuyDirection(currentSignal.signal_type)
                            ? styles.buyText
                            : isSellDirection(currentSignal.signal_type)
                            ? styles.sellText
                            : {}
                        ]}>
                          {normalizeDirection(currentSignal.signal_type) || '-'}
                        </Text>
                      </View>
                      <View style={styles.signalInfo}>
                        <Text style={styles.signalLabel}>Confiança</Text>
                        <Text style={styles.signalValue}>{((currentSignal.confidence || 0) * 100).toFixed(0)}%</Text>
                      </View>
                      <View style={styles.signalInfo}>
                        <Text style={styles.signalLabel}>Timeframe</Text>
                        <Text style={styles.signalValue}>{formatTimeframe(currentSignal.timeframe)}</Text>
                      </View>
                    </View>

                    <View style={styles.signalRow}>
                      <View style={styles.signalInfo}>
                        <Text style={styles.signalLabel}>Preço</Text>
                        <Text style={styles.signalValue}>{formatPrice(currentSignal.price)}</Text>
                      </View>
                      <View style={styles.signalInfo}>
                        <Text style={styles.signalLabel}>Estratégia</Text>
                        <Text style={styles.signalValue}>{currentSignal.strategy_name || currentSignal.strategy_id}</Text>
                      </View>
                    </View>

                    {currentSignal.indicators && currentSignal.indicators.length > 0 && (
                      <View style={styles.indicatorsSection}>
                        <Text style={styles.indicatorsTitle}>Indicadores:</Text>
                        <Text style={styles.indicatorText}>
                          {formatIndicatorSummary(currentSignal.indicators)}
                        </Text>
                      </View>
                    )}
                  </View>
                </TouchableOpacity>
              </View>
            )}

            {/* Seção Passado */}
            {memoizedPastSignals.length > 0 && (
              <View style={styles.section}>
                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Passado</Text>
                  <View style={styles.sectionBadge}>
                    <Text style={styles.sectionBadgeText}>{totalPastSignals}</Text>
                  </View>
                </View>
                {memoizedPastSignals.map((signal, index) => (
                  <TouchableOpacity
                    key={`past-${signal.id || `signal-${index}`}-${index}`}
                    style={styles.signalCard}
                    onPress={() => handleSignalPress(signal)}
                    activeOpacity={0.7}
                  >
                    <View style={styles.signalHeader}>
                      <View style={styles.signalAssetRow}>
                        <Text style={styles.signalAsset}>{signal.asset_name || `Ativo #${signal.asset_id}`}</Text>
                        <View
                          style={[
                            styles.statusBadge,
                            signal.is_executed ? styles.executedBadge : styles.pendingBadge
                          ]}
                        >
                          <Text style={[styles.statusText, signal.is_executed ? styles.executedText : styles.pendingText]}>
                            {signal.is_executed ? 'Executado' : 'Pendente'}
                          </Text>
                        </View>
                      </View>
                      <Text style={styles.signalDate}>{formatDate(signal.created_at)}</Text>
                    </View>

                    <View style={styles.signalBody}>
                      <View style={styles.signalRow}>
                        <View style={styles.signalInfo}>
                          <Text style={styles.signalLabel}>Direção</Text>
                          <Text style={[
                            styles.signalValue,
                            isBuyDirection(signal.signal_type)
                              ? styles.buyText
                              : isSellDirection(signal.signal_type)
                              ? styles.sellText
                              : {}
                          ]}>
                            {normalizeDirection(signal.signal_type) || '-'}
                          </Text>
                        </View>
                        <View style={styles.signalInfo}>
                          <Text style={styles.signalLabel}>Confiança</Text>
                          <Text style={styles.signalValue}>{((signal.confidence || 0) * 100).toFixed(0)}%</Text>
                        </View>
                        <View style={styles.signalInfo}>
                          <Text style={styles.signalLabel}>Timeframe</Text>
                          <Text style={styles.signalValue}>{formatTimeframe(signal.timeframe)}</Text>
                        </View>
                      </View>

                      <View style={styles.signalRow}>
                        <View style={styles.signalInfo}>
                          <Text style={styles.signalLabel}>Preço</Text>
                          <Text style={styles.signalValue}>{formatPrice(signal.price)}</Text>
                        </View>
                        <View style={styles.signalInfo}>
                          <Text style={styles.signalLabel}>Estratégia</Text>
                          <Text style={styles.signalValue}>{signal.strategy_name || signal.strategy_id}</Text>
                        </View>
                      </View>

                      {signal.indicators && signal.indicators.length > 0 && (
                        <View style={styles.indicatorsSection}>
                          <Text style={styles.indicatorsTitle}>Indicadores:</Text>
                          <Text style={styles.indicatorText}>
                            {formatIndicatorSummary(signal.indicators)}
                          </Text>
                        </View>
                      )}
                    </View>
                  </TouchableOpacity>
                ))}
                
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
                    <Text style={styles.loadMoreButtonText}>Carregar mais sinais</Text>
                  </TouchableOpacity>
                )}
              </View>
            )}
          </>
        )}
      </ScrollView>

      {/* Modal de detalhes do sinal */}
      <Modal
        visible={modalVisible}
        animationType="slide"
        transparent={true}
        onRequestClose={closeModal}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Detalhes do Sinal</Text>
              <TouchableOpacity onPress={closeModal}>
                <Ionicons name="close" size={24} color="#94A3B8" />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalScroll}>
              {selectedSignal && (
                <>
                  <View style={styles.modalSection}>
                    <Text style={styles.modalSectionTitle}>Informações Gerais</Text>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Ativo:</Text>
                      <Text style={styles.modalValue}>{selectedSignal.asset_name || `#${selectedSignal.asset_id}`}</Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Estratégia:</Text>
                      <Text style={styles.modalValue}>{selectedSignal.strategy_name || selectedSignal.strategy_id}</Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Direção:</Text>
                      <Text style={[
                        styles.modalValue,
                        isBuyDirection(selectedSignal.signal_type)
                          ? styles.buyText
                          : isSellDirection(selectedSignal.signal_type)
                          ? styles.sellText
                          : {}
                      ]}>
                        {normalizeDirection(selectedSignal.signal_type) || '-'}
                      </Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Confiança:</Text>
                      <Text style={styles.modalValue}>{((selectedSignal.confidence || 0) * 100).toFixed(1)}%</Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Preço:</Text>
                      <Text style={styles.modalValue}>{formatPrice(selectedSignal.price)}</Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Timeframe:</Text>
                      <Text style={styles.modalValue}>{formatTimeframe(selectedSignal.timeframe)}</Text>
                    </View>
                    <View style={styles.modalRow}>
                      <Text style={styles.modalLabel}>Status:</Text>
                      <Text style={[
                        styles.modalValue,
                        selectedSignal.is_executed ? styles.executedText : styles.pendingText
                      ]}>
                        {selectedSignal.is_executed ? 'Executado' : 'Pendente'}
                      </Text>
                    </View>
                  </View>

                  {selectedSignal.indicators && selectedSignal.indicators.length > 0 ? (
                    <View style={styles.modalSection}>
                      <Text style={styles.modalSectionTitle}>Detalhes dos Indicadores</Text>
                      
                      {/* Resumo de sinais BUY/SELL */}
                      {(() => {
                        const counts = countIndicatorSignals(selectedSignal.indicators);
                        return (
                          <View style={styles.indicatorSummaryContainer}>
                            <View style={styles.indicatorSummaryRow}>
                              <View style={[styles.indicatorSummaryBadge, styles.buyBadge]}>
                                <Text style={styles.indicatorSummaryCount}>{counts.buy}</Text>
                                <Text style={styles.indicatorSummaryLabel}>BUY</Text>
                              </View>
                              <View style={[styles.indicatorSummaryBadge, styles.sellBadge]}>
                                <Text style={styles.indicatorSummaryCount}>{counts.sell}</Text>
                                <Text style={styles.indicatorSummaryLabel}>SELL</Text>
                              </View>
                              <View style={[styles.indicatorSummaryBadge, styles.totalBadge]}>
                                <Text style={styles.indicatorSummaryCount}>{counts.total}</Text>
                                <Text style={styles.indicatorSummaryLabel}>Total</Text>
                              </View>
                            </View>
                          </View>
                        );
                      })()}
                      
                      {selectedSignal.indicators.map((indicator: Indicator, index: number) =>
                        renderIndicatorDetails(indicator, index, selectedSignal.id)
                      )}
                    </View>
                  ) : (
                    <View style={styles.modalSection}>
                      <Text style={styles.modalSectionTitle}>Detalhes dos Indicadores</Text>
                      <View style={styles.emptyIndicatorState}>
                        <Ionicons name="information-circle-outline" size={20} color="#64748B" />
                        <Text style={styles.emptyIndicatorText}>Nenhum detalhe disponível para este sinal.</Text>
                      </View>
                    </View>
                  )}
                </>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
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
  section: {
    marginBottom: 20,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  sectionBadge: {
    backgroundColor: 'rgba(125, 211, 252, 0.15)',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(125, 211, 252, 0.3)',
  },
  sectionBadgeText: {
    color: colors.primary,
    fontSize: 11,
    fontWeight: '600',
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
  errorText: {
    color: colors.danger,
    fontSize: 14,
    marginTop: 12,
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
  signalCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 16,
  },
  signalHeader: {
    marginBottom: 16,
  },
  signalAssetRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  signalAsset: {
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
  executedBadge: {
    backgroundColor: 'rgba(34, 197, 94, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(34, 197, 94, 0.3)',
  },
  pendingBadge: {
    backgroundColor: 'rgba(251, 191, 36, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.3)',
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    marginLeft: 6,
  },
  executedText: {
    color: '#FFFFFF',
  },
  pendingText: {
    color: '#FFFFFF',
  },
  signalDate: {
    color: colors.textSoft,
    fontSize: 12,
  },
  signalBody: {
    gap: 16,
  },
  signalRow: {
    flexDirection: 'row',
  },
  signalInfo: {
    flex: 1,
    marginRight: 16,
  },
  signalLabel: {
    color: colors.textSoft,
    fontSize: 11,
    marginBottom: 2,
  },
  signalValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '500',
  },
  buyText: {
    color: '#34C759',
  },
  sellText: {
    color: '#FF3B30',
  },
  indicatorsSection: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.04)',
  },
  indicatorsTitle: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: 4,
  },
  indicatorText: {
    color: colors.textSoft,
    fontSize: 11,
    marginBottom: 2,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '90%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.04)',
  },
  modalTitle: {
    color: colors.text,
    fontSize: 20,
    fontWeight: '700',
  },
  modalScroll: {
    padding: 20,
  },
  modalSection: {
    marginBottom: 24,
  },
  modalSectionTitle: {
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 12,
  },
  modalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  modalLabel: {
    color: colors.textSoft,
    fontSize: 13,
  },
  modalValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '500',
  },
  indicatorDetailCard: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  indicatorDetailHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  indicatorDetailHeaderLeft: {
    flexDirection: 'column',
  },
  indicatorDetailName: {
    color: colors.text,
    fontSize: 15,
    fontWeight: '600',
  },
  indicatorDetailType: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: '500',
  },
  indicatorDetailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  indicatorDetailLabel: {
    color: colors.textSoft,
    fontSize: 12,
  },
  indicatorDetailValue: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '500',
  },
  indicatorDetailSection: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.04)',
  },
  indicatorDetailSectionTitle: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 6,
  },
  tableSection: {
    marginTop: 12,
  },
  tableTitle: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 8,
  },
  tableContainer: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.06)',
    overflow: 'hidden',
  },
  tableHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(15, 23, 42, 0.8)',
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  tableHeaderCell: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '600',
    flex: 1,
  },
  tableRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  tableRowAlt: {
    backgroundColor: 'rgba(15, 23, 42, 0.35)',
  },
  tableCellLabel: {
    color: colors.textMuted,
    fontSize: 12,
    flex: 1,
  },
  tableCellValue: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '500',
    flex: 1,
    textAlign: 'right',
  },
  emptyIndicatorState: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
  },
  emptyIndicatorText: {
    color: colors.textMuted,
    fontSize: 12,
  },
  indicatorSummaryContainer: {
    marginBottom: 16,
  },
  indicatorSummaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    gap: 12,
  },
  indicatorSummaryBadge: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 12,
    borderWidth: 1,
  },
  buyBadge: {
    backgroundColor: 'rgba(52, 199, 89, 0.2)',
    borderColor: 'rgba(52, 199, 89, 0.5)',
  },
  sellBadge: {
    backgroundColor: 'rgba(255, 59, 48, 0.2)',
    borderColor: 'rgba(255, 59, 48, 0.5)',
  },
  totalBadge: {
    backgroundColor: 'rgba(125, 211, 252, 0.2)',
    borderColor: 'rgba(125, 211, 252, 0.5)',
  },
  indicatorSummaryCount: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
  },
  indicatorSummaryLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textMuted,
    marginTop: 2,
  },
});
