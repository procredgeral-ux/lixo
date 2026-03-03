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
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { apiClient, IndicatorCombinationRanking } from '../services/api';
import { CustomAlert } from '../components/CustomAlert';
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

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function CreateStrategyScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const [strategyName, setStrategyName] = useState('');
  const [strategyDescription, setStrategyDescription] = useState('');
  const [selectedIndicators, setSelectedIndicators] = useState<string[]>([]);
  const [indicatorParams, setIndicatorParams] = useState<Record<string, Record<string, any>>>({});
  const [accounts, setAccounts] = useState<any[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoModalVisible, setInfoModalVisible] = useState(false);
  const [currentInfo, setCurrentInfo] = useState<{title: string; description: string} | null>(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [indicatorRankings, setIndicatorRankings] = useState<IndicatorCombinationRanking[]>([]);
  const [loadingRankings, setLoadingRankings] = useState(false);
  const [showRankingDropdown, setShowRankingDropdown] = useState(false);
  const [alertVisible, setAlertVisible] = useState(false);
  const [alertConfig, setAlertConfig] = useState<{ title: string; message: string; type?: 'success' | 'error' | 'warning' | 'info'; buttons?: Array<{ text: string; onPress?: () => void; style?: 'default' | 'cancel' | 'destructive' }> } | null>(null);

  // Explicações e limites dos parâmetros
  const paramExplanations: Record<string, string> = {
    'period': 'Número de velas usadas no cálculo. Valores menores tornam o indicador mais sensível, valores maiores tornam mais suave.',
    'overbought': 'Nível acima do qual o ativo é considerado sobrecomprado. O indicador pode sinalizar venda quando ultrapassa este valor.',
    'oversold': 'Nível abaixo do qual o ativo é considerado sobrevendido. O indicador pode sinalizar compra quando cai abaixo deste valor.',
    'fast_period': 'Período para a média móvel rápida. Valores menores tornam o indicador mais sensível às mudanças de preço.',
    'slow_period': 'Período para a média móvel lenta. Valores maiores tornam o indicador mais suave e menos sensível.',
    'signal_period': 'Período para a linha de sinal. Usado para gerar sinais de compra/venda baseados nos cruzamentos.',
    'std_dev': 'Multiplicador do desvio padrão. Valores maiores alargam as bandas, valores menores as estreitam.',
    'k_period': 'Período para a linha %K do Stochastic. Determina quantas velas são usadas no cálculo.',
    'd_period': 'Período para a linha %D do Stochastic. Suaviza a linha %K para gerar sinais mais confiáveis.',
    'smooth': 'Fator de suavização. Valores maiores tornam o indicador mais suave e menos sensível.',
    'swing_period': 'Número de velas para identificar topos e fundos. Valores menores identificam mais zonas, valores maiores apenas as mais significativas.',
    'zone_strength': 'Mínimo de toques para validar uma zona. Valores maiores exigem mais toques, valores menores exigem menos.',
    'zone_tolerance': 'Tolerância para agrupar zonas próximas. Valores maiores agrupam zonas mais distantes.',
    'min_zone_width': 'Largura mínima da zona em % do preço. Zonas menores que isso são ignoradas.',
    'atr_multiplier': 'Multiplicador do ATR para definir a largura da zona. Valores maiores criam zonas mais largas.',
  };

  // Limites dos parâmetros (min, max)
  const paramLimits: Record<string, { min: number; max: number }> = {
    'period': { min: 2, max: 200 },
    'overbought': { min: 50, max: 100 },
    'oversold': { min: 0, max: 50 },
    'fast_period': { min: 2, max: 100 },
    'slow_period': { min: 5, max: 200 },
    'signal_period': { min: 2, max: 50 },
    'std_dev': { min: 0.5, max: 5 },
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
    'williams_r': {
      overbought: { min: -100, max: 0 },
      oversold: { min: -100, max: 0 },
    },
    'cci': {
      overbought: { min: -200, max: 200 },
      oversold: { min: -200, max: 200 },
    },
    'roc': {
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
      const rawParams = indicatorParams[indicatorId] || {};
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
          setAlertConfig({
            title: 'Parâmetro inválido',
            message: `Indicador ${indicator?.name ?? indicatorId} → ${paramKey}. ${parsed.message ?? ''}`.trim(),
            type: 'warning',
          });
          setAlertVisible(true);
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
    const title = paramKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    setCurrentInfo({
      title,
      description: paramExplanations[paramKey] || 'Sem explicação disponível para este parâmetro.',
    });
    setInfoModalVisible(true);
  };

  // Carregar indicadores, contas e rankings do banco de dados
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        
        // Buscar indicadores
        const indicatorsData = await apiClient.get<{indicators: Indicator[]}>('/indicators/');
        if (indicatorsData.indicators) {
          setIndicators(indicatorsData.indicators);
        }
        
        // Buscar contas
        const accountsData = await apiClient.get<any[]>('/accounts');
        if (accountsData) {
          setAccounts(accountsData);
          // Selecionar a primeira conta automaticamente
          if (accountsData.length > 0) {
            setSelectedAccount(accountsData[0].id);
          }
        }

        // Buscar rankings de combinações de indicadores
        await loadIndicatorRankings();
      } catch (err) {
        setError('Erro ao carregar dados');
        console.error('Erro ao carregar dados:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  // Criar conta automaticamente se não houver nenhuma
  const createAccountIfNeeded = async () => {
    if (accounts.length === 0) {
      try {
        setLoading(true);
        const mode = 'demo';
        const newAccount = await apiClient.post<any>('/accounts', {
          name: 'Conta Principal',
          autotrade_demo: true,
          autotrade_real: false,
        });
        setAccounts([newAccount]);
        setSelectedAccount(newAccount.id);
        setAlertConfig({
          title: 'Conta criada',
          message: 'Uma conta foi criada automaticamente para você. Agora você pode criar estratégias.',
          type: 'info',
        });
        setAlertVisible(true);
      } catch (err) {
        setAlertConfig({
          title: 'Erro',
          message: 'Não foi possível criar uma conta automaticamente. Por favor, entre em contato com o suporte.',
          type: 'error',
        });
        setAlertVisible(true);
        console.error('Erro ao criar conta:', err);
      } finally {
        setLoading(false);
      }
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
        console.log('Carregando parâmetros padrão para indicador:', indicator.name, defaultParams);
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

  const handleCreate = async () => {
    if (!strategyName.trim()) {
      setAlertConfig({
        title: 'Erro',
        message: 'Nome da estratégia é obrigatório',
        type: 'error',
      });
      setAlertVisible(true);
      return;
    }

    if (!selectedAccount) {
      if (accounts.length === 0) {
        // Criar conta automaticamente
        await createAccountIfNeeded();
        return;
      } else {
        setAlertConfig({
          title: 'Erro',
          message: 'Selecione uma conta para a estratégia',
          type: 'error',
        });
        setAlertVisible(true);
        return;
      }
    }

    if (selectedIndicators.length === 0) {
      setAlertConfig({
        title: 'Erro',
        message: 'Selecione pelo menos um indicador',
        type: 'error',
      });
      setAlertVisible(true);
      return;
    }

    // Mostrar modal de confirmação
    setShowConfirmModal(true);
  };

  const confirmCreate = async () => {
    setShowConfirmModal(false);

    const normalizedParams = normalizeIndicatorParams();
    if (!normalizedParams) {
      return;
    }

    try {
      setLoading(true);

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
        type: 'custom', // Sempre 'custom' pois são estratégias personalizadas
        account_id: selectedAccount, // Usar a conta selecionada
        parameters: strategyParameters, // Parâmetros dos indicadores
        assets: ['EURUSD', 'GBPUSD'], // Ativos padrão
        indicators: indicatorPayload,
      };

      // Enviar para o backend
      await apiClient.post<{message: string}>('/strategies', strategyData);

      setAlertConfig({
        title: 'Sucesso',
        message: 'Estratégia criada com sucesso!',
        type: 'success',
      });
      setAlertVisible(true);
      navigation.goBack();
    } catch (err) {
      setAlertConfig({
        title: 'Erro',
        message: 'Erro ao criar estratégia',
        type: 'error',
      });
      setAlertVisible(true);
      console.error('Erro ao criar estratégia:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Nova Estratégia</Text>
      </View>

      <ScrollView 
        style={styles.scrollContainer}
        contentContainerStyle={styles.scrollContent}
        maintainVisibleContentPosition={{
          minIndexForVisible: 0,
          autoscrollToTopThreshold: 10,
        }}
      >
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#007AFF" />
            <Text style={styles.loadingText}>Carregando indicadores...</Text>
          </View>
        ) : error ? (
          <View style={styles.errorContainer}>
            <Ionicons name="warning" size={32} color="#FF3B30" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : (
          <>
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
              {indicators.map((indicator) => {
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
              })}
            </View>

            <View style={styles.formSection}>
              <TouchableOpacity style={styles.createButton} onPress={handleCreate}>
                {loading ? (
                  <ActivityIndicator size="small" color="#0F172A" />
                ) : (
                  <Text style={styles.createButtonText}>Criar Estratégia</Text>
                )}
              </TouchableOpacity>
            </View>

            {/* Modal de Confirmação */}
            <Modal
              visible={showConfirmModal}
              transparent={true}
              animationType="fade"
              onRequestClose={() => setShowConfirmModal(false)}
            >
              <View style={styles.confirmModal}>
                <View style={styles.confirmModalContent}>
                  <Ionicons name="checkmark-circle" size={48} color="#007AFF" />
                  <Text style={styles.confirmModalTitle}>Confirmar Criação</Text>
                  <Text style={styles.confirmModalText}>
                    Você está prestes a criar a estratégia "{strategyName}" com {selectedIndicators.length} indicador(es).
                  </Text>
                  <Text style={styles.confirmModalSubText}>
                    Deseja continuar?
                  </Text>
                  <View style={styles.confirmModalButtons}>
                    <TouchableOpacity
                      style={styles.confirmModalCancelButton}
                      onPress={() => setShowConfirmModal(false)}
                    >
                      <Text style={styles.confirmModalCancelButtonText}>Cancelar</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={styles.confirmModalConfirmButton}
                      onPress={confirmCreate}
                    >
                      <Text style={styles.confirmModalConfirmButtonText}>Confirmar</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            </Modal>
          </>
        )}
      </ScrollView>

      {/* Modal de Informação do Parâmetro */}
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
      <CustomAlert
        visible={alertVisible}
        title={alertConfig?.title || ''}
        message={alertConfig?.message || ''}
        type={alertConfig?.type}
        buttons={alertConfig?.buttons}
        onClose={() => setAlertVisible(false)}
      />
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
  paramLabel: {
    fontSize: 14,
    color: colors.textMuted,
    flex: 1,
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
  paramLabelContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  infoButton: {
    marginLeft: 8,
    padding: 4,
  },
  createButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    padding: 14,
    borderRadius: 12,
    gap: 8,
  },
  createButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
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
    marginBottom: 16,
  },
  noParamsText: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    padding: 16,
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
  confirmModal: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
  },
  confirmModalContent: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 32,
    alignItems: 'center',
    width: '80%',
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  confirmModalTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    marginTop: 16,
    marginBottom: 8,
  },
  confirmModalText: {
    fontSize: 16,
    color: colors.text,
    textAlign: 'center',
    marginBottom: 24,
  },
  confirmModalSubText: {
    fontSize: 13,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 20,
  },
  confirmModalButtons: {
    flexDirection: 'row',
    width: '100%',
    gap: 12,
  },
  confirmModalCancelButton: {
    flex: 1,
    backgroundColor: '#334155',
    borderRadius: 12,
    padding: 12,
    alignItems: 'center',
  },
  confirmModalCancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  confirmModalConfirmButton: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 12,
    padding: 12,
    alignItems: 'center',
  },
  confirmModalConfirmButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.primaryText,
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
