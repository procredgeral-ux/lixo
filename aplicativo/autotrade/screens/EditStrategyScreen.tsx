import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { apiClient, IndicatorCombinationRanking } from '../services/api';
import RangeSlider from '../components/RangeSlider';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface Indicator {
  id: string;
  name: string;
  type: string;
  description: string;
  parameters: Record<string, any>;
  is_active: boolean;
}

interface IndicatorParam {
  key: string;
  label: string;
  defaultValue: string;
  value: any;
}

interface StrategyData {
  id: string;
  name: string;
  description: string;
  type: string;
  account_id: string;
  parameters: Record<string, any>;
  assets: string[];
  indicators: any[];
  is_active: boolean;
}

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function EditStrategyScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const route = useRoute();
  const params = route.params as { strategyId: string };

  const [strategyName, setStrategyName] = useState('');
  const [strategyDescription, setStrategyDescription] = useState('');
  const [selectedIndicators, setSelectedIndicators] = useState<string[]>([]);
  const [indicatorParams, setIndicatorParams] = useState<Record<string, Record<string, any>>>({});
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoModalVisible, setInfoModalVisible] = useState(false);
  const [currentInfo, setCurrentInfo] = useState<{title: string; description: string} | null>(null);
  const [saveModalVisible, setSaveModalVisible] = useState(false);
  const [saveModalType, setSaveModalType] = useState<'success' | 'error'>('success');
  const [saveModalMessage, setSaveModalMessage] = useState('');
  const [indicatorRankings, setIndicatorRankings] = useState<IndicatorCombinationRanking[]>([]);
  const [loadingRankings, setLoadingRankings] = useState(false);
  const [showRankingDropdown, setShowRankingDropdown] = useState(false);

  // Explicações dos parâmetros
  const paramExplanations: Record<string, string> = {
    'period': 'Período de cálculo do indicador (número de candles)',
    'overbought': 'Nível de sobrecompra (acima deste valor é considerado sobrecomprado)',
    'oversold': 'Nível de sobrevenda (abaixo deste valor é considerado sobrevendido)',
    'fast_period': 'Período rápido para cálculo (ex: EMA rápida)',
    'slow_period': 'Período lento para cálculo (ex: EMA lenta)',
    'signal_period': 'Período para linha de sinal',
    'k_period': 'Período %K (Stochastic)',
    'd_period': 'Período %D (Stochastic)',
    'smooth': 'Fator de suavização',
    'swing_period': 'Período de swing (número de candles)',
    'zone_strength': 'Força da zona (nível de confirmação)',
    'zone_tolerance': 'Tolerância da zona (distância mínima)',
    'min_zone_width': 'Largura mínima da zona',
    'atr_multiplier': 'Multiplicador ATR (para stop loss)',
  };

  const paramLimits: Record<string, { min: number; max: number }> = {
    'period': { min: 2, max: 200 },
    'overbought': { min: 50, max: 100 },
    'oversold': { min: 0, max: 50 },
    'fast_period': { min: 2, max: 100 },
    'slow_period': { min: 5, max: 200 },
    'signal_period': { min: 2, max: 50 },
    'k_period': { min: 2, max: 50 },
    'd_period': { min: 2, max: 30 },
    'smooth': { min: 1, max: 10 },
    'swing_period': { min: 2, max: 50 },
    'zone_strength': { min: 1, max: 10 },
    'zone_tolerance': { min: 0.001, max: 0.02 },
    'min_zone_width': { min: 0.001, max: 0.02 },
    'atr_multiplier': { min: 0.1, max: 2.0 },
  };

  const indicatorParamLimits: Record<string, Record<string, { min: number; max: number }>> = {
    williams_r: {
      overbought: { min: -100, max: 0 },
      oversold: { min: -100, max: 0 },
    },
    cci: {
      overbought: { min: -200, max: 200 },
      oversold: { min: -200, max: 200 },
    },
    roc: {
      overbought: { min: -100, max: 100 },
      oversold: { min: -100, max: 100 },
    },
  };

  const getParamLimits = (paramKey: string, indicatorType?: string) => {
    if (indicatorType && indicatorParamLimits[indicatorType]?.[paramKey]) {
      return indicatorParamLimits[indicatorType][paramKey];
    }
    return paramLimits[paramKey];
  };

  const intParams = new Set([
    'period',
    'fast_period',
    'slow_period',
    'signal_period',
    'k_period',
    'd_period',
    'smooth',
    'swing_period',
    'zone_strength',
  ]);

  const parseParametersPayload = (value: any): Record<string, any> => {
    if (!value) {
      return {};
    }

    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        if (typeof parsed === 'string') {
          return JSON.parse(parsed);
        }
        return parsed || {};
      } catch (error) {
        return {};
      }
    }

    return value;
  };

  const normalizeParamValue = (
    paramKey: string,
    rawValue: any,
    defaultValue: any,
    indicatorType?: string
  ): { valid: boolean; value?: number; message?: string } => {
    const resolvedValue = rawValue === '' || rawValue === null || rawValue === undefined
      ? defaultValue
      : rawValue;

    if (resolvedValue === '' || resolvedValue === null || resolvedValue === undefined) {
      return { valid: false, message: 'Valor vazio' };
    }

    const numValue = Number(String(resolvedValue).replace(',', '.'));
    if (Number.isNaN(numValue)) {
      return { valid: false, message: 'Valor inválido' };
    }

    const limits = getParamLimits(paramKey, indicatorType);
    if (limits && (numValue < limits.min || numValue > limits.max)) {
      return { valid: false, message: `O valor deve estar entre ${limits.min} e ${limits.max}` };
    }

    const normalizedValue = intParams.has(paramKey)
      ? Math.round(numValue)
      : parseFloat(numValue.toFixed(6));

    return { valid: true, value: normalizedValue };
  };

  const normalizeIndicatorParams = () => {
    const normalized: Record<string, Record<string, number>> = {};

    for (const indicatorId of selectedIndicators) {
      const indicator = indicators.find((item) => item.id === indicatorId);
      const rawParams = parseParametersPayload(indicatorParams[indicatorId]);
      const defaults = parseParametersPayload(indicator?.parameters);
      const paramKeys = new Set([...Object.keys(defaults), ...Object.keys(rawParams)]);
      const normalizedParams: Record<string, number> = {};

      for (const paramKey of paramKeys) {
        const parsed = normalizeParamValue(
          paramKey,
          rawParams[paramKey],
          defaults[paramKey],
          indicator?.type
        );
        if (!parsed.valid || parsed.value === undefined) {
          setSaveModalType('error');
          setSaveModalMessage(
            `Parâmetro inválido: ${indicator?.name ?? indicatorId} → ${paramKey}. ${parsed.message ?? ''}`.trim()
          );
          setSaveModalVisible(true);
          return null;
        }
        normalizedParams[paramKey] = parsed.value;
      }

      normalized[indicatorId] = normalizedParams;
    }

    return normalized;
  };

  const getKeyboardType = (paramKey: string): 'number-pad' | 'decimal-pad' => {
    return intParams.has(paramKey) ? 'number-pad' : 'decimal-pad';
  };

  const showParamInfo = (paramKey: string) => {
    setCurrentInfo({
      title: paramKey,
      description: paramExplanations[paramKey] || 'Parâmetro do indicador'
    });
    setInfoModalVisible(true);
  };

  const convertIndicatorParams = (indicator: Indicator): IndicatorParam[] => {
    const paramsMap: Record<string, { label: string }> = {
      'period': { label: 'Período' },
      'overbought': { label: 'Sobrecompra' },
      'oversold': { label: 'Sobrevenda' },
      'fast_period': { label: 'Período Rápido' },
      'slow_period': { label: 'Período Lento' },
      'signal_period': { label: 'Período Sinal' },
      'std_dev': { label: 'Desvio Padrão' },
      'k_period': { label: 'Período %K' },
      'd_period': { label: 'Período %D' },
      'smooth': { label: 'Suavização' },
      'swing_period': { label: 'Período Swing' },
      'zone_strength': { label: 'Força da Zona' },
      'zone_tolerance': { label: 'Tolerância da Zona' },
      'min_zone_width': { label: 'Largura Mínima' },
      'atr_multiplier': { label: 'Multiplicador ATR' },
      // Novos indicadores
      'initial_af': { label: 'AF Inicial' },
      'max_af': { label: 'AF Máximo' },
      'step_af': { label: 'AF Passo' },
      'tenkan_period': { label: 'Período Tenkan' },
      'kijun_period': { label: 'Período Kijun' },
      'senkou_span_b_period': { label: 'Período Senkou B' },
      'chikou_shift': { label: 'Deslocamento Chikou' },
      'ema_period': { label: 'Período EMA' },
      'atr_period': { label: 'Período ATR' },
      'multiplier': { label: 'Multiplicador' },
      'lookback': { label: 'Lookback' },
    };

    const params: IndicatorParam[] = [];

    const paramsSource = parseParametersPayload(indicator.parameters);
    if (paramsSource) {
      Object.entries(paramsSource).forEach(([key, value]) => {
        if (paramsMap[key]) {
          params.push({
            key,
            label: paramsMap[key].label,
            defaultValue: String(value),
            value,
          });
        }
      });
    }

    return params;
  };

  const convertIndicatorParamsWithSaved = (indicator: Indicator, savedParams?: Record<string, any>): IndicatorParam[] => {
    const paramsMap: Record<string, { label: string }> = {
      'period': { label: 'Período' },
      'overbought': { label: 'Sobrecompra' },
      'oversold': { label: 'Sobrevenda' },
      'fast_period': { label: 'Período Rápido' },
      'slow_period': { label: 'Período Lento' },
      'signal_period': { label: 'Período Sinal' },
      'k_period': { label: 'Período %K' },
      'd_period': { label: 'Período %D' },
      'smooth': { label: 'Suavização' },
      'swing_period': { label: 'Período Swing' },
      'zone_strength': { label: 'Força da Zona' },
      'zone_tolerance': { label: 'Tolerância da Zona' },
      'min_zone_width': { label: 'Largura Mínima' },
      'atr_multiplier': { label: 'Multiplicador ATR' },
      // Novos indicadores
      'initial_af': { label: 'AF Inicial' },
      'max_af': { label: 'AF Máximo' },
      'step_af': { label: 'AF Passo' },
      'tenkan_period': { label: 'Período Tenkan' },
      'kijun_period': { label: 'Período Kijun' },
      'senkou_span_b_period': { label: 'Período Senkou B' },
      'chikou_shift': { label: 'Deslocamento Chikou' },
      'ema_period': { label: 'Período EMA' },
      'atr_period': { label: 'Período ATR' },
      'multiplier': { label: 'Multiplicador' },
      'lookback': { label: 'Lookback' },
    };

    const params: IndicatorParam[] = [];

    const paramsSource = parseParametersPayload(indicator.parameters);
    const parsedSavedParams = parseParametersPayload(savedParams);
    if (paramsSource) {
      Object.entries(paramsSource).forEach(([key, defaultValue]) => {
        if (paramsMap[key]) {
          const savedValue = parsedSavedParams?.[key] ?? defaultValue;
          params.push({
            key,
            label: paramsMap[key].label,
            defaultValue: String(defaultValue),
            value: savedValue,
          });
        }
      });
    }

    return params;
  };

  const toggleIndicator = (indicatorId: string) => {
    if (selectedIndicators.includes(indicatorId)) {
      setSelectedIndicators(selectedIndicators.filter((id) => id !== indicatorId));
      const newParams = { ...indicatorParams };
      delete newParams[indicatorId];
      setIndicatorParams(newParams);
    } else {
      setSelectedIndicators([...selectedIndicators, indicatorId]);
      const indicator = indicators.find((i) => i.id === indicatorId);
      if (indicator) {
        const params = convertIndicatorParams(indicator);
        const defaultParams: Record<string, any> = {};
        params.forEach((param) => {
          defaultParams[param.key] = param.value;
        });
        setIndicatorParams({
          ...indicatorParams,
          [indicatorId]: defaultParams,
        });
      }
    }
  };

  const updateParam = (indicatorId: string, paramKey: string, value: string) => {
    setIndicatorParams({
      ...indicatorParams,
      [indicatorId]: {
        ...(indicatorParams[indicatorId] || {}),
        [paramKey]: value,
      },
    });
  };

  useEffect(() => {
    loadStrategy();
  }, [params.strategyId]);

  const loadStrategy = async () => {
    try {
      setLoading(true);
      
      // Carregar estratégia
      const response = await apiClient.get<StrategyData>(`/strategies/${params.strategyId}`);
      setStrategyName(response.name);
      setStrategyDescription(response.description || '');
      
      // Carregar indicadores da estratégia
      if (response.indicators && response.indicators.length > 0) {
        const indicatorIds = response.indicators.map((ind: any) => ind.id);
        setSelectedIndicators(indicatorIds);
        
        // Carregar parâmetros dos indicadores
        const params: Record<string, Record<string, any>> = {};
        response.indicators.forEach((ind: any) => {
          if (ind.parameters) {
            params[ind.id] = parseParametersPayload(ind.parameters);
          }
        });
        setIndicatorParams(params);
      }

      // Carregar indicadores disponíveis
      const indicatorsData = await apiClient.get<{indicators: Indicator[]}>('/indicators');
      if (indicatorsData.indicators) {
        setIndicators(indicatorsData.indicators);
      }

      // Carregar rankings de combinações de indicadores
      await loadIndicatorRankings();
    } catch (err) {
      setError('Erro ao carregar estratégia');
      console.error('Erro ao carregar estratégia:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadIndicatorRankings = async () => {
    setLoadingRankings(true);
    try {
      const response = await apiClient.get<{rankings: IndicatorCombinationRanking[]}>('/trades/indicator-rankings?limit=20');
      setIndicatorRankings(response.rankings || []);
    } catch (err) {
      console.error('Erro ao carregar rankings de indicadores:', err);
    } finally {
      setLoadingRankings(false);
    }
  };

  const applyIndicatorCombination = (combination: string) => {
    // Parse the combination string (e.g., "RSI + MACD" or "RSI, MACD, Bollinger")
    const indicatorNames = combination.split(/[+&,]/).map(name => name.trim().toLowerCase().replace(/[()]/g, ''));
    
    // Find matching indicators by name or type
    const matchingIds: string[] = [];
    const newParams: Record<string, Record<string, any>> = {};
    
    indicators.forEach(indicator => {
      const indicatorNameLower = indicator.name.toLowerCase().replace(/[()]/g, '');
      const indicatorTypeLower = indicator.type.toLowerCase();
      
      const isMatch = indicatorNames.some(name => {
        const nameMatch = indicatorNameLower.includes(name) || name.includes(indicatorNameLower);
        const typeMatch = indicatorTypeLower.includes(name) || name.includes(indicatorTypeLower);
        return nameMatch || typeMatch;
      });
      
      if (isMatch) {
        matchingIds.push(indicator.id);
        // Load default parameters for this indicator
        const params = convertIndicatorParams(indicator);
        const defaultParams: Record<string, any> = {};
        params.forEach((param) => {
          defaultParams[param.key] = param.value;
        });
        newParams[indicator.id] = defaultParams;
      }
    });
    
    // Apenas atualiza o estado local - sem salvar, sem alertas
    setSelectedIndicators(matchingIds);
    setIndicatorParams(prev => ({ ...prev, ...newParams }));
    setShowRankingDropdown(false);
  };

  const handleSave = async () => {
    if (!strategyName.trim()) {
      setSaveModalType('error');
      setSaveModalMessage('O nome da estratégia é obrigatório');
      setSaveModalVisible(true);
      return;
    }

    if (selectedIndicators.length === 0) {
      setSaveModalType('error');
      setSaveModalMessage('Selecione pelo menos um indicador');
      setSaveModalVisible(true);
      return;
    }

    try {
      setSaving(true);
      setError(null);

      const normalizedParams = normalizeIndicatorParams();
      if (!normalizedParams) {
        return;
      }

      // Preparar parâmetros da estratégia a partir dos indicadores selecionados
      const strategyParameters: Record<string, any> = {};
      selectedIndicators.forEach((indicatorId) => {
        const indicator = indicators.find((i) => i.id === indicatorId);
        if (indicator && normalizedParams[indicatorId]) {
          // Adicionar parâmetros do indicador ao dicionário de parâmetros da estratégia
          Object.entries(normalizedParams[indicatorId]).forEach(([key, value]) => {
            strategyParameters[key] = value;
          });
        }
      });

      const indicatorPayload = selectedIndicators
        .map((id) => {
          const indicator = indicators.find((i) => i.id === id);
          if (!indicator) return null;
          return {
            id: indicator.id,
            name: indicator.name,
            type: indicator.type,
            parameters: normalizedParams[id] || {},
          };
        })
        .filter((item): item is NonNullable<typeof item> => item !== null);

      // Preparar dados da estratégia
      const strategyData = {
        name: strategyName,
        description: strategyDescription,
        type: 'custom',
        parameters: strategyParameters,
        indicators: indicatorPayload,
      };

      await apiClient.put(`/strategies/${params.strategyId}`, strategyData);

      setSaveModalType('success');
      setSaveModalMessage('Estratégia atualizada com sucesso!');
      setSaveModalVisible(true);
    } catch (err) {
      setError('Erro ao atualizar estratégia');
      console.error('Erro ao atualizar estratégia:', err);
      setSaveModalType('error');
      setSaveModalMessage('Não foi possível atualizar a estratégia');
      setSaveModalVisible(true);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centerContainer}>
          <ActivityIndicator size="large" color="#7DD3FC" />
          <Text style={styles.loadingText}>Carregando estratégia...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#7DD3FC" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Editar Estratégia</Text>
      </View>

      <ScrollView 
        style={styles.scrollContainer}
        contentContainerStyle={styles.scrollContent}
        maintainVisibleContentPosition={{
          minIndexForVisible: 0,
          autoscrollToTopThreshold: 10,
        }}
      >
        <View style={styles.formSection}>
          <Text style={styles.sectionTitle}>Informações Básicas</Text>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Nome da Estratégia *</Text>
            <TextInput
              style={styles.input}
              placeholder="Ex: Estratégia RSI + MACD"
              placeholderTextColor="#64748B"
              value={strategyName}
              onChangeText={setStrategyName}
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Descrição</Text>
            <TextInput
              style={[styles.input, styles.textArea]}
              placeholder="Descreva sua estratégia..."
              placeholderTextColor="#64748B"
              value={strategyDescription}
              onChangeText={setStrategyDescription}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />
          </View>
        </View>

        <View style={styles.formSection}>
          <Text style={styles.sectionTitle}>Indicadores</Text>
          <Text style={styles.sectionSubtitle}>Selecione os indicadores para sua estratégia</Text>
          {indicators && indicators.length > 0 ? (
            indicators.map((indicator) => {
              const isSelected = selectedIndicators.includes(indicator.id);
              return (
                <TouchableOpacity
                  key={indicator.id}
                  style={[styles.indicatorCard, isSelected && styles.indicatorCardSelected]}
                  onPress={() => toggleIndicator(indicator.id)}
                >
                  <View style={styles.indicatorHeader}>
                    <View style={styles.indicatorInfo}>
                      <View style={[styles.checkbox, isSelected && styles.checkboxSelected]}>
                        {isSelected && <Ionicons name="checkmark" size={16} color="#FFFFFF" />}
                      </View>
                      <View style={styles.indicatorText}>
                        <Text style={styles.indicatorName}>{indicator.name}</Text>
                        <Text style={styles.indicatorDescription}>{indicator.description}</Text>
                      </View>
                    </View>
                    <Ionicons
                      name={isSelected ? 'chevron-up' : 'chevron-down'}
                      size={20}
                      color="#8E8E93"
                    />
                  </View>

                  {isSelected && (
                    <View style={styles.paramsContainer}>
                      {convertIndicatorParamsWithSaved(indicator, indicatorParams[indicator.id]).length > 0 ? (
                        convertIndicatorParamsWithSaved(indicator, indicatorParams[indicator.id]).map((param) => {
                          const limits = getParamLimits(param.key, indicator.type);
                          const numValue = Number(param.value);

                          // Use RangeSlider para parâmetros numéricos com limites definidos
                          if (limits && !isNaN(numValue)) {
                            return (
                              <View key={param.key} style={styles.paramRow}>
                                <View style={styles.paramLabelContainer}>
                                  <Text style={styles.paramLabel}>{param.label}</Text>
                                  <TouchableOpacity
                                    style={styles.infoButton}
                                    onPress={() => showParamInfo(param.key)}
                                  >
                                    <Ionicons name="information-circle-outline" size={16} color="#007AFF" />
                                  </TouchableOpacity>
                                </View>
                                <View style={styles.sliderContainer}>
                                  <RangeSlider
                                    min={limits.min}
                                    max={limits.max}
                                    value={numValue}
                                    onChange={(value) => updateParam(indicator.id, param.key, String(value))}
                                    step={intParams.has(param.key) ? 1 : 0.1}
                                    showLabels={false}
                                  />
                                </View>
                              </View>
                            );
                          }

                          // Fallback para TextInput para parâmetros sem limites definidos
                          return (
                            <View key={param.key} style={styles.paramRow}>
                              <View style={styles.paramLabelContainer}>
                                <Text style={styles.paramLabel}>{param.label}</Text>
                                <TouchableOpacity
                                  style={styles.infoButton}
                                  onPress={() => showParamInfo(param.key)}
                                >
                                  <Ionicons name="information-circle-outline" size={16} color="#007AFF" />
                                </TouchableOpacity>
                              </View>
                              <TextInput
                                style={styles.paramInput}
                                value={String(param.value ?? '')}
                                onChangeText={(value) => updateParam(indicator.id, param.key, value)}
                                keyboardType={getKeyboardType(param.key)}
                              />
                            </View>
                          );
                        })
                      ) : (
                        <Text style={styles.noParamsText}>Este indicador não possui parâmetros configuráveis</Text>
                      )}
                    </View>
                  )}
                </TouchableOpacity>
              );
            })
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyText}>Nenhum indicador disponível</Text>
            </View>
          )}
        </View>

        {error && (
          <View style={styles.errorContainer}>
            <Ionicons name="alert-circle" size={20} color="#EF4444" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {/* Botões de seleção de indicadores */}
        <View style={styles.selectionButtonsContainer}>
          <TouchableOpacity
            style={styles.selectionButton}
            onPress={() => setSelectedIndicators(indicators.map(i => i.id))}
          >
            <Text style={styles.selectionButtonText}>Marcar tudo</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.selectionButton, styles.selectionButtonSecondary]}
            onPress={() => setSelectedIndicators([])}
          >
            <Text style={[styles.selectionButtonText, styles.selectionButtonTextSecondary]}>Desmarcar tudo</Text>
          </TouchableOpacity>
        </View>

        {/* Filtro de Melhores Combinações de Indicadores */}
        {indicatorRankings.length > 0 && (
          <View style={styles.rankingFilterContainer}>
            <TouchableOpacity
              style={styles.rankingFilterButton}
              onPress={() => setShowRankingDropdown(!showRankingDropdown)}
            >
              <Ionicons name="trophy" size={16} color={colors.primary} />
              <Text style={styles.rankingFilterButtonText}>
                Aplicar melhor combinação
              </Text>
              <Ionicons
                name={showRankingDropdown ? 'chevron-up' : 'chevron-down'}
                size={16}
                color={colors.textMuted}
              />
            </TouchableOpacity>

            {showRankingDropdown && (
              <View style={styles.rankingDropdown}>
                <Text style={styles.rankingDropdownTitle}>
                  Melhores combinações da sua conta
                </Text>
                {loadingRankings ? (
                  <ActivityIndicator size="small" color={colors.primary} />
                ) : (
                  indicatorRankings.slice(0, 10).map((ranking, index) => (
                    <TouchableOpacity
                      key={`${ranking.combination}-${index}`}
                      style={styles.rankingItem}
                      onPress={() => applyIndicatorCombination(ranking.combination)}
                    >
                      <View style={styles.rankingItemHeader}>
                        <View style={styles.rankingPosition}>
                          <Text style={styles.rankingPositionText}>#{index + 1}</Text>
                        </View>
                        <View style={styles.rankingItemInfo}>
                          <Text style={styles.rankingItemCombination}>
                            {ranking.combination}
                          </Text>
                          <Text style={styles.rankingItemStats}>
                            {ranking.win_rate.toFixed(0)}% win rate • {ranking.total_trades} trades
                          </Text>
                        </View>
                        <View style={styles.rankingItemProfit}>
                          <Text
                            style={[
                              styles.rankingItemProfitText,
                              { color: ranking.total_profit >= 0 ? '#34C759' : '#FF3B30' }
                            ]}
                          >
                            {ranking.total_profit >= 0 ? '+' : ''}
                            {ranking.total_profit.toFixed(2)}
                          </Text>
                        </View>
                      </View>
                    </TouchableOpacity>
                  ))
                )}
              </View>
            )}
          </View>
        )}

        <TouchableOpacity
          style={[styles.saveButton, saving && styles.saveButtonDisabled]}
          onPress={handleSave}
          disabled={saving}
        >
          {saving ? (
            <ActivityIndicator size="small" color="#0F172A" />
          ) : (
            <Text style={styles.saveButtonText}>Salvar Alterações</Text>
          )}
        </TouchableOpacity>

        {/* Modal de Informação */}
        <Modal
          visible={infoModalVisible}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setInfoModalVisible(false)}
        >
          <View style={styles.infoModal}>
            <View style={styles.infoModalContent}>
              <Text style={styles.infoModalTitle}>{currentInfo?.title}</Text>
              <Text style={styles.infoModalDescription}>{currentInfo?.description}</Text>
              <TouchableOpacity
                style={styles.infoModalCloseButton}
                onPress={() => setInfoModalVisible(false)}
              >
                <Ionicons name="close-circle" size={20} color="#FFFFFF" />
                <Text style={styles.infoModalCloseButtonText}>Entendi</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>

        {/* Modal de Salvar */}
        <Modal
          visible={saveModalVisible}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setSaveModalVisible(false)}
        >
          <View style={styles.saveModal}>
            <View style={styles.saveModalContent}>
              <Ionicons
                name={saveModalType === 'success' ? 'checkmark-circle' : 'alert-circle'}
                size={48}
                color={saveModalType === 'success' ? '#10B981' : '#EF4444'}
              />
              <Text style={[styles.saveModalTitle, saveModalType === 'success' ? styles.successTitle : styles.errorTitle]}>
                {saveModalType === 'success' ? 'Sucesso!' : 'Erro'}
              </Text>
              <Text style={styles.saveModalMessage}>{saveModalMessage}</Text>
              <TouchableOpacity
                style={styles.saveModalButton}
                onPress={() => {
                  setSaveModalVisible(false);
                  if (saveModalType === 'success') {
                    navigation.goBack();
                  }
                }}
              >
                <Text style={styles.saveModalButtonText}>OK</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
    marginTop: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 20,
    paddingTop: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
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
    flex: 1,
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
  },
  scrollContainer: {
    flex: 1,
  },
  scrollContent: {
    paddingVertical: 16,
  },
  formSection: {
    padding: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
  },
  sectionSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: 16,
  },
  inputGroup: {
    gap: 8,
  },
  label: {
    fontSize: 14,
    color: colors.text,
    marginBottom: 4,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    color: colors.text,
  },
  textArea: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  indicatorCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  indicatorCardSelected: {
    borderColor: colors.primary,
    borderWidth: 1,
  },
  indicatorHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  indicatorInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  checkbox: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  checkboxSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  indicatorText: {
    flex: 1,
  },
  indicatorName: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 2,
  },
  indicatorDescription: {
    fontSize: 12,
    color: colors.textMuted,
  },
  paramsContainer: {
    marginTop: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.borderStrong,
  },
  paramRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  paramLabelContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  paramLabel: {
    fontSize: 14,
    color: colors.textMuted,
    flex: 1,
  },
  infoButton: {
    marginLeft: 8,
    padding: 4,
  },
  paramInput: {
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 8,
    padding: 10,
    fontSize: 14,
    color: colors.text,
    width: 100,
    textAlign: 'center',
  },
  sliderContainer: {
    flex: 1,
    marginLeft: 10,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  errorText: {
    color: colors.danger,
    fontSize: 14,
    marginTop: 12,
    textAlign: 'center',
  },
  saveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    padding: 14,
    borderRadius: 12,
    gap: 8,
    margin: 20,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  saveModal: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
  },
  saveModalContent: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 32,
    alignItems: 'center',
    width: '80%',
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  saveModalTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    marginTop: 16,
    marginBottom: 8,
  },
  successTitle: {
    color: colors.success,
  },
  errorTitle: {
    color: colors.danger,
  },
  saveModalMessage: {
    fontSize: 16,
    color: colors.text,
    textAlign: 'center',
    marginBottom: 24,
  },
  saveModalButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 32,
    paddingVertical: 12,
    borderRadius: 12,
  },
  saveModalButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  emptyState: {
    padding: 20,
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
  },
  infoModal: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  infoModalContent: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    margin: 20,
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoModalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 12,
  },
  infoModalDescription: {
    fontSize: 14,
    color: colors.text,
  },
  infoModalCloseButton: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    padding: 12,
    borderRadius: 12,
    marginTop: 16,
    gap: 8,
  },
  infoModalCloseButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  selectionButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  selectionButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  selectionButtonSecondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.primary,
  },
  selectionButtonText: {
    color: colors.primaryText,
    fontSize: 13,
    fontWeight: '600',
  },
  selectionButtonTextSecondary: {
    color: colors.primary,
  },
  selectionButtonsContainer: {
    flexDirection: 'row',
    gap: 12,
    marginHorizontal: 20,
    marginBottom: 16,
  },
  noParamsText: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    padding: 16,
  },
  rankingFilterContainer: {
    marginHorizontal: 20,
    marginBottom: 16,
  },
  rankingFilterButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 16,
    gap: 8,
  },
  rankingFilterButtonText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '600',
  },
  rankingDropdown: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 12,
    marginTop: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  rankingDropdownTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textMuted,
    marginBottom: 10,
    textAlign: 'center',
  },
  rankingItem: {
    backgroundColor: colors.background,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  rankingItemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  rankingPosition: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  rankingPositionText: {
    color: colors.primaryText,
    fontSize: 12,
    fontWeight: 'bold',
  },
  rankingItemInfo: {
    flex: 1,
  },
  rankingItemCombination: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 2,
  },
  rankingItemStats: {
    fontSize: 11,
    color: colors.textMuted,
  },
  rankingItemProfit: {
    alignItems: 'flex-end',
  },
  rankingItemProfitText: {
    fontSize: 14,
    fontWeight: 'bold',
  },
});
