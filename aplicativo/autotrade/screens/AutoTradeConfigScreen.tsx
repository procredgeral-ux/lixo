import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Switch, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import Ionicons from 'react-native-vector-icons/Ionicons';
import { apiClient } from '../services/api';
import { CustomAlert } from '../components/CustomAlert';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface Account {
  id: string;
  name: string;
}

interface AutoTradeConfigData {
  account_id: string;
  amount: number;
  stop1: number;
  stop2: number;
  no_hibernate_on_consecutive_stop: boolean;
  stop_amount_win: number;
  stop_amount_loss: number;
  soros: number;
  martingale: number;
  timeframe: number;
  min_confidence: number;
  cooldown_seconds: number | string;
  trade_timing: 'on_signal' | 'on_candle_close';
  execute_all_signals?: boolean;
  // Redução Inteligente
  smart_reduction_enabled?: boolean;
  smart_reduction_loss_trigger?: number;
  smart_reduction_win_restore?: number;
  smart_reduction_percentage?: number;
  smart_reduction_cascading?: boolean;  // Redução recursiva/cascata
}

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function AutoTradeConfigScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const route = useRoute();
  const params = route.params as { strategyId?: string } || {};
  const strategyId = params?.strategyId;

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);

  const [config, setConfig] = useState<AutoTradeConfigData>({
    account_id: '',
    amount: 1.0,
    stop1: 3,
    stop2: 5,
    no_hibernate_on_consecutive_stop: false,
    stop_amount_win: 0,
    stop_amount_loss: 0,
    soros: 0,
    martingale: 0,
    timeframe: 5,
    min_confidence: 0.7,
    cooldown_seconds: 0,
    trade_timing: 'on_signal',
    execute_all_signals: false,
    // Redução Inteligente
    smart_reduction_enabled: false,
    smart_reduction_loss_trigger: 3,
    smart_reduction_win_restore: 2,
    smart_reduction_percentage: 50,
    smart_reduction_cascading: false,  // Caducar Redução - redução recursiva
  });
  const [existingConfigId, setExistingConfigId] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confidenceText, setConfidenceText] = useState(config.min_confidence.toString());
  const [alertVisible, setAlertVisible] = useState(false);
  const [alertConfig, setAlertConfig] = useState<{ title: string; message: string; type?: 'success' | 'error' | 'warning' | 'info'; buttons?: Array<{ text: string; onPress?: () => void; style?: 'default' | 'cancel' | 'destructive' }> } | null>(null);
  const [stopsExpanded, setStopsExpanded] = useState(false);
  const [basicExpanded, setBasicExpanded] = useState(true);
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  const [controlExpanded, setControlExpanded] = useState(false);
  const [smartReductionExpanded, setSmartReductionExpanded] = useState(false);
  const [availableTimeframes, setAvailableTimeframes] = useState<number[]>([]);

  // Atualizar confidenceText quando config.min_confidence muda
  useEffect(() => {
    setConfidenceText(config.min_confidence.toString());
  }, [config.min_confidence]);

  // Load available timeframes
  useEffect(() => {
    const loadAvailableTimeframes = async () => {
      try {
        const response = await apiClient.get<{ available_timeframes: Array<{ value: number; label: string }> }>('/autotrade-config/available-timeframes');
        setAvailableTimeframes(response.available_timeframes.map(tf => tf.value));
      } catch (error) {
        console.error('Erro ao carregar timeframes disponíveis:', error);
      }
    };
    loadAvailableTimeframes();
  }, []);

  // Load accounts and existing config
  useEffect(() => {
    const loadData = async () => {
      try {
        // Load accounts
        const accountsResponse = await apiClient.get<Account[]>('/accounts');
        setAccounts(accountsResponse);
        
        // Load existing autotrade config for this strategy
        if (strategyId) {
          try {
            const configResponse = await apiClient.get<any>(`/autotrade-config?strategy_id=${strategyId}`);
            if (configResponse && configResponse.length > 0) {
              const existingConfig = configResponse[0];
              setExistingConfigId(existingConfig.id);
              setConfig({
                account_id: existingConfig.account_id,
                amount: existingConfig.amount,
                stop1: existingConfig.stop1,
                stop2: existingConfig.stop2,
                no_hibernate_on_consecutive_stop: existingConfig.no_hibernate_on_consecutive_stop ?? false,
                stop_amount_win: existingConfig.stop_amount_win || 0,
                stop_amount_loss: existingConfig.stop_amount_loss || 0,
                soros: existingConfig.soros,
                martingale: existingConfig.martingale,
                timeframe: existingConfig.timeframe,
                min_confidence: existingConfig.min_confidence,
                cooldown_seconds: existingConfig.cooldown_seconds || 0,
                trade_timing: existingConfig.trade_timing || 'on_signal',
                execute_all_signals: existingConfig.execute_all_signals ?? false,
                // Redução Inteligente
                smart_reduction_enabled: existingConfig.smart_reduction_enabled ?? false,
                smart_reduction_loss_trigger: existingConfig.smart_reduction_loss_trigger || 3,
                smart_reduction_win_restore: existingConfig.smart_reduction_win_restore || 2,
                smart_reduction_percentage: existingConfig.smart_reduction_percentage || 50,
                smart_reduction_cascading: existingConfig.smart_reduction_cascading ?? false,
              });
              setSelectedAccount(existingConfig.account_id);
            } else if (accountsResponse.length > 0) {
              // No existing config for this strategy, try to reuse legacy account config
              const firstAccount = accountsResponse[0];
              setSelectedAccount(firstAccount.id);
              try {
                const legacyResponse = await apiClient.get<any>(`/autotrade-config?account_id=${firstAccount.id}`);
                const legacyConfig = Array.isArray(legacyResponse)
                  ? legacyResponse.find((item: any) => !item.strategy_id)
                  : null;

                if (legacyConfig) {
                  setExistingConfigId(legacyConfig.id);
                  setConfig({
                    account_id: legacyConfig.account_id,
                    amount: legacyConfig.amount,
                    stop1: legacyConfig.stop1,
                    stop2: legacyConfig.stop2,
                    no_hibernate_on_consecutive_stop: legacyConfig.no_hibernate_on_consecutive_stop ?? false,
                    stop_amount_win: legacyConfig.stop_amount_win || 0,
                    stop_amount_loss: legacyConfig.stop_amount_loss || 0,
                    soros: legacyConfig.soros,
                    martingale: legacyConfig.martingale,
                    timeframe: legacyConfig.timeframe,
                    min_confidence: legacyConfig.min_confidence,
                    cooldown_seconds: legacyConfig.cooldown_seconds || 0,
                    trade_timing: legacyConfig.trade_timing || 'on_signal',
                    execute_all_signals: legacyConfig.execute_all_signals ?? false,
                    // Redução Inteligente
                    smart_reduction_enabled: legacyConfig.smart_reduction_enabled ?? false,
                    smart_reduction_loss_trigger: legacyConfig.smart_reduction_loss_trigger || 3,
                    smart_reduction_win_restore: legacyConfig.smart_reduction_win_restore || 2,
                    smart_reduction_percentage: legacyConfig.smart_reduction_percentage || 50,
                    smart_reduction_cascading: legacyConfig.smart_reduction_cascading ?? false,
                  });
                } else {
                  setConfig(prev => ({ ...prev, account_id: firstAccount.id }));
                }
              } catch (legacyErr) {
                console.error('Erro ao carregar configuração legada:', legacyErr);
                setConfig(prev => ({ ...prev, account_id: firstAccount.id }));
              }
            }
          } catch (err) {
            console.error('Erro ao carregar configuração existente:', err);
            if (accountsResponse.length > 0) {
              const firstAccount = accountsResponse[0];
              setSelectedAccount(firstAccount.id);
              setConfig(prev => ({ ...prev, account_id: firstAccount.id }));
            }
          }
        } else if (accountsResponse.length > 0) {
          // No strategyId, load existing config for the account
          const firstAccount = accountsResponse[0];
          setSelectedAccount(firstAccount.id);

          try {
            // Check if there's an existing config for this account without strategy
            const configResponse = await apiClient.get<any>(`/autotrade-config?account_id=${firstAccount.id}`);
            if (configResponse && configResponse.length > 0) {
              const existingConfig = configResponse[0];
              setExistingConfigId(existingConfig.id);
              setConfig({
                account_id: existingConfig.account_id,
                amount: existingConfig.amount,
                stop1: existingConfig.stop1,
                stop2: existingConfig.stop2,
                no_hibernate_on_consecutive_stop: existingConfig.no_hibernate_on_consecutive_stop ?? false,
                stop_amount_win: existingConfig.stop_amount_win || 0,
                stop_amount_loss: existingConfig.stop_amount_loss || 0,
                soros: existingConfig.soros,
                martingale: existingConfig.martingale,
                timeframe: existingConfig.timeframe,
                min_confidence: existingConfig.min_confidence,
                cooldown_seconds: existingConfig.cooldown_seconds || 0,
                trade_timing: existingConfig.trade_timing || 'on_signal',
                execute_all_signals: existingConfig.execute_all_signals ?? false,
                // Redução Inteligente
                smart_reduction_enabled: existingConfig.smart_reduction_enabled ?? false,
                smart_reduction_loss_trigger: existingConfig.smart_reduction_loss_trigger || 3,
                smart_reduction_win_restore: existingConfig.smart_reduction_win_restore || 2,
                smart_reduction_percentage: existingConfig.smart_reduction_percentage || 50,
                smart_reduction_cascading: existingConfig.smart_reduction_cascading ?? false,
              });
            } else {
              // No existing config, initialize with default values
              setConfig(prev => ({ ...prev, account_id: firstAccount.id }));
            }
          } catch (err) {
            console.error('Erro ao carregar configuração existente:', err);
            setConfig(prev => ({ ...prev, account_id: firstAccount.id }));
          }
        }
      } catch (err) {
        console.error('Erro ao carregar dados:', err);
      } finally {
        setLoadingAccounts(false);
      }
    };

    loadData();
  }, [strategyId]);

  const handleSave = async () => {
    try {
      setLoading(true);
      setError(null);

      console.log('[AutoTradeConfig] Salvando configuração...');
      console.log('[AutoTradeConfig] config:', config);
      console.log('[AutoTradeConfig] stop_amount_win:', config.stop_amount_win);
      console.log('[AutoTradeConfig] stop_amount_loss:', config.stop_amount_loss);
      console.log('[AutoTradeConfig] typeof stop_amount_win:', typeof config.stop_amount_win);
      console.log('[AutoTradeConfig] typeof stop_amount_loss:', typeof config.stop_amount_loss);

      const parsedConfidence = parseFloat(confidenceText);
      const normalizedConfidence = !Number.isNaN(parsedConfidence)
        ? Math.max(0, Math.min(1, parsedConfidence))
        : config.min_confidence;
      const payload = { ...config, min_confidence: normalizedConfidence };
      const savePayload = strategyId ? { ...payload, strategy_id: strategyId } : payload;

      // Validar configuração antes de salvar
      if (!payload.account_id) {
        setError('Selecione uma conta');
        return;
      }

      if (payload.amount <= 0) {
        setError('Valor da operação deve ser maior que 0');
        return;
      }

      if (payload.stop_amount_win < 0 || payload.stop_amount_loss < 0) {
        setError('Stop gain e stop loss não podem ser negativos');
        return;
      }

      // Se "Não hibernar" está ativado e stop gain/stop loss são 0, impedir salvar
      if (payload.no_hibernate_on_consecutive_stop && payload.stop1 === 0 && payload.stop2 === 0) {
        console.log('[AutoTradeConfig] no_hibernate_on_consecutive_stop:', payload.no_hibernate_on_consecutive_stop);
        console.log('[AutoTradeConfig] stop1 === 0:', payload.stop1 === 0);
        console.log('[AutoTradeConfig] stop2 === 0:', payload.stop2 === 0);
        setError('Não é possível salvar com "Não hibernar" ativado e stop gain/stop loss em 0. O "Não hibernar" não pode ficar ligado se stop gain e stop loss forem 0. Defina valores maiores que 0 para ambos ou desative "Não hibernar".');
        return;
      }

      setConfig(payload);
      if (!Number.isNaN(parsedConfidence)) {
        setConfidenceText(normalizedConfidence.toString());
      }

      if (existingConfigId) {
        // Atualizar configuração existente
        await apiClient.put(`/autotrade-config/${existingConfigId}`, savePayload);
      } else {
        // Criar nova configuração
        await apiClient.post('/autotrade-config', {
          ...savePayload,
        });
      }

      setAlertConfig({
        title: 'Sucesso',
        message: 'Configuração salva com sucesso!',
        type: 'success',
        buttons: [{ text: 'OK', onPress: () => navigation.goBack() }],
      });
      setAlertVisible(true);
    } catch (err) {
      setError('Erro ao salvar configuração');
      console.error('Erro ao salvar configuração:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#7DD3FC" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Configuração Auto Trade</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loadingAccounts ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#7DD3FC" />
          <Text style={styles.loadingText}>Carregando contas...</Text>
        </View>
      ) : (
        <>
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scrollContent}>
          {/* Account Selection */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Conta</Text>
            
            {accounts.length === 0 ? (
              <View style={styles.emptyState}>
                <Ionicons name="wallet-outline" size={32} color="#2F3B52" />
                <Text style={styles.emptyText}>Nenhuma conta encontrada</Text>
              </View>
            ) : (
              <View style={styles.accountSelector}>
                {accounts.map((account) => (
                  <TouchableOpacity
                    key={account.id}
                    style={[
                      styles.accountOption,
                      selectedAccount === account.id && styles.accountOptionActive,
                    ]}
                    onPress={() => {
                      setSelectedAccount(account.id);
                      setConfig(prev => ({ ...prev, account_id: account.id }));
                    }}
                  >
                    <Text style={[
                      styles.accountName,
                      selectedAccount === account.id && styles.accountNameActive,
                    ]}>
                      {account.name}
                    </Text>
                    {selectedAccount === account.id && (
                      <Ionicons name="checkmark-circle" size={16} color="#7DD3FC" />
                    )}
                  </TouchableOpacity>
                ))}
              </View>
            )}
          </View>

          {/* Configurações Básicas */}
          <View style={styles.section}>
            <TouchableOpacity
              style={styles.accordionHeader}
              onPress={() => setBasicExpanded(!basicExpanded)}
              activeOpacity={0.7}
            >
              <Text style={styles.sectionTitle}>Configurações Básicas</Text>
              <Ionicons
                name={basicExpanded ? 'chevron-up' : 'chevron-down'}
                size={20}
                color="#7DD3FC"
              />
            </TouchableOpacity>

            {basicExpanded && (
              <View style={styles.accordionContent}>
                <View style={styles.field}>
                  <Text style={styles.label}>Valor da Operação ($)</Text>
                  <TextInput
                    style={styles.input}
                    value={config.amount.toString()}
                    onChangeText={(text) => setConfig({ ...config, amount: parseFloat(text) || 0 })}
                    keyboardType="numeric"
                    placeholder="1.00"
                  />
                </View>

                <View style={styles.field}>
                  <Text style={styles.label}>Timeframe (segundos)</Text>
                  <View style={styles.timeframeOptions}>
                    {[{ value: 3, label: '3s' },
                    { value: 5, label: '5s' },
                    { value: 30, label: '30s' },
                    { value: 60, label: '1min' },
                    { value: 300, label: '5min' },
                    { value: 900, label: '15min' },
                    { value: 3600, label: '1h' },
                    { value: 14400, label: '4h' },
                  ].map((option) => {
                    const isAvailable = availableTimeframes.includes(option.value);
                    return (
                      <TouchableOpacity
                        key={option.value}
                        style={[
                          styles.timeframeButton,
                          config.timeframe === option.value && styles.timeframeButtonActive,
                          !isAvailable && styles.timeframeButtonDisabled,
                        ]}
                        onPress={() => {
                          if (isAvailable) {
                            setConfig({ ...config, timeframe: option.value });
                          }
                        }}
                        disabled={!isAvailable}
                      >
                        <Text style={[
                          styles.timeframeButtonText,
                          config.timeframe === option.value && styles.timeframeButtonTextActive,
                          !isAvailable && styles.timeframeButtonTextDisabled,
                        ]}>
                          {option.label}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                  </View>
                </View>

                <View style={styles.field}>
                  <Text style={styles.label}>Confiança Mínima (0.0 - 1.0)</Text>
                  <TextInput
                    style={styles.input}
                    value={confidenceText}
                    onChangeText={(text) => {
                      // Manter o texto digitado como string para permitir digitação de valores parciais
                      setConfidenceText(text);
                    }}
                    onBlur={() => {
                      // Quando o usuário terminar de digitar, converter e validar
                      const value = parseFloat(confidenceText);
                      if (!isNaN(value)) {
                        // Limitar entre 0.0 e 1.0
                        const clampedValue = Math.max(0, Math.min(1, value));
                        setConfig({ ...config, min_confidence: clampedValue });
                        setConfidenceText(clampedValue.toString());
                      } else {
                        // Se não for um número válido, voltar para o valor atual
                        setConfidenceText(config.min_confidence.toString());
                      }
                    }}
                    keyboardType="decimal-pad"
                    placeholder="0.7"
                  />
                  <Text style={styles.hint}>
                    Valores entre 0.0 (baixa) e 1.0 (alta). Recomendado: 0.5-0.7
                  </Text>
                </View>
              </View>
            )}
          </View>

        {/* Configurações de Execução */}
        <View style={styles.section}>
          <TouchableOpacity
            style={styles.accordionHeader}
            onPress={() => setControlExpanded(!controlExpanded)}
            activeOpacity={0.7}
          >
            <Text style={styles.sectionTitle}>Configurações de Execução</Text>
            <Ionicons
              name={controlExpanded ? 'chevron-up' : 'chevron-down'}
              size={20}
              color="#7DD3FC"
            />
          </TouchableOpacity>

          {controlExpanded && (
            <View style={styles.accordionContent}>
              <View style={styles.field}>
                <Text style={styles.label}>Timing de Execução</Text>
                <View style={styles.toggleRow}>
                  <TouchableOpacity
                    style={[
                      styles.timingButton,
                      config.trade_timing === 'on_signal' && styles.timingButtonActive,
                    ]}
                    onPress={() => setConfig({ ...config, trade_timing: 'on_signal' })}
                  >
                    <Text style={[
                      styles.timingButtonText,
                      config.trade_timing === 'on_signal' && styles.timingButtonTextActive,
                    ]}>
                      No Sinal
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.timingButton,
                      config.trade_timing === 'on_candle_close' && styles.timingButtonActive,
                    ]}
                    onPress={() => setConfig({ ...config, trade_timing: 'on_candle_close' })}
                  >
                    <Text style={[
                      styles.timingButtonText,
                      config.trade_timing === 'on_candle_close' && styles.timingButtonTextActive,
                    ]}>
                      No Fechamento da Vela
                    </Text>
                  </TouchableOpacity>
                </View>
                <Text style={styles.hint}>
                  No Sinal: Executa imediatamente ao receber o sinal
                  No Fechamento da Vela: Aguarda o fechamento da vela para executar
                </Text>
              </View>

              {/* Executar Todos os Sinais */}
              <View style={styles.toggleRow}>
                <View style={styles.toggleText}>
                  <Text style={styles.label}>Executar Todos os Sinais</Text>
                  <Text style={styles.hint}>
                    Quando ativado, executa operações para todos os sinais recebidos, independentemente da estratégia vencedora.
                  </Text>
                </View>
                <Switch
                  value={config.execute_all_signals}
                  onValueChange={(value) => setConfig({ ...config, execute_all_signals: value })}
                  trackColor={{ false: '#1C1F2A', true: '#7DD3FC' }}
                  thumbColor={config.execute_all_signals ? '#0F172A' : '#94A3B8'}
                  ios_backgroundColor="#1C1F2A"
                />
              </View>
            </View>
          )}
        </View>

        {/* Stop Loss/Stop Gain e Stop Amount */}
        <View style={styles.section}>
          <TouchableOpacity
            style={styles.accordionHeader}
            onPress={() => setStopsExpanded(!stopsExpanded)}
            activeOpacity={0.7}
          >
            <Text style={styles.sectionTitle}>Stops (Configurações de Parada)</Text>
            <Ionicons
              name={stopsExpanded ? 'chevron-up' : 'chevron-down'}
              size={20}
              color="#7DD3FC"
            />
          </TouchableOpacity>

          {stopsExpanded && (
            <View style={styles.accordionContent}>
              {/* Stop Loss/Stop Gain */}
              <View style={styles.subsection}>
                <Text style={styles.subsectionTitle}>Stop Loss / Stop Gain (Consecutivos)</Text>

                <View style={styles.toggleRow}>
                  <View style={styles.toggleText}>
                    <Text style={styles.label}>Não hibernar ao atingir stop</Text>
                    <Text style={styles.hint}>
                      Quando ligado a estratégia não é desligada ao atingir um dos stops,
                      apenas respeita o tempo configurado no Cooldown e volta a executar novamente.
                    </Text>
                  </View>
                  <Switch
                    value={config.no_hibernate_on_consecutive_stop}
                    onValueChange={(value) => {
                      // Só permitir ativar se stop1 > 0 ou stop2 > 0
                      if (value && config.stop1 === 0 && config.stop2 === 0) {
                        setAlertConfig({
                          title: 'Atenção',
                          message: 'Para ativar "Não hibernar ao atingir stop", você precisa configurar Stop Gain ou Stop Loss com valor maior que 0.',
                          type: 'warning',
                          buttons: [{ text: 'OK', onPress: () => setAlertVisible(false) }],
                        });
                        setAlertVisible(true);
                        return;
                      }
                      setConfig({ ...config, no_hibernate_on_consecutive_stop: value });
                    }}
                    trackColor={{ false: '#1C1F2A', true: '#7DD3FC' }}
                    thumbColor={config.no_hibernate_on_consecutive_stop ? '#0F172A' : '#94A3B8'}
                    ios_backgroundColor="#1C1F2A"
                  />
                </View>

                <View style={styles.field}>
                  <View style={styles.fieldHeader}>
                    <Text style={styles.label}>Stop Gain (vitórias consecutivas)</Text>
                    <Text style={styles.fieldValue}>{config.stop1 > 0 ? `${config.stop1} trades` : 'Desativado'}</Text>
                  </View>
                  <TextInput
                    style={styles.input}
                    value={config.stop1.toString()}
                    onChangeText={(text) => setConfig({ ...config, stop1: parseInt(text) || 0 })}
                    keyboardType="numeric"
                    placeholder="0 = desativado"
                  />
                  <Text style={styles.hint}>
                    Número de vitórias consecutivas para parar. 0 = desativado
                  </Text>
                </View>

                <View style={styles.field}>
                  <View style={styles.fieldHeader}>
                    <Text style={styles.label}>Stop Loss (perdas consecutivas)</Text>
                    <Text style={styles.fieldValue}>{config.stop2 > 0 ? `${config.stop2} trades` : 'Desativado'}</Text>
                  </View>
                  <TextInput
                    style={styles.input}
                    value={config.stop2.toString()}
                    onChangeText={(text) => setConfig({ ...config, stop2: parseInt(text) || 0 })}
                    keyboardType="numeric"
                    placeholder="0 = desativado"
                  />
                  <Text style={styles.hint}>
                    Número de perdas consecutivas para parar. 0 = desativado
                  </Text>
                </View>
              </View>

              {/* Stop Amount */}
              <View style={styles.subsection}>
                <Text style={styles.subsectionTitle}>Stop Amount (Saldo da Conta)</Text>

                <View style={styles.field}>
                  <View style={styles.fieldHeader}>
                    <Text style={styles.label}>Stop Amount Win ($)</Text>
                    <Text style={styles.fieldValue}>{config.stop_amount_win > 0 ? `US$ ${config.stop_amount_win.toFixed(2)}` : 'Desativado'}</Text>
                  </View>
                  <TextInput
                    style={styles.input}
                    value={config.stop_amount_win.toString()}
                    onChangeText={(text) => setConfig({ ...config, stop_amount_win: parseFloat(text) || 0 })}
                    keyboardType="decimal-pad"
                    placeholder="0 = desativado"
                  />
                  <Text style={styles.hint}>
                    Valor do saldo para parar (lucro). 0 = desativado
                  </Text>
                </View>

                <View style={styles.field}>
                  <View style={styles.fieldHeader}>
                    <Text style={styles.label}>Stop Amount Loss ($)</Text>
                    <Text style={styles.fieldValue}>{config.stop_amount_loss > 0 ? `US$ ${config.stop_amount_loss.toFixed(2)}` : 'Desativado'}</Text>
                  </View>
                  <TextInput
                    style={styles.input}
                    value={config.stop_amount_loss.toString()}
                    onChangeText={(text) => setConfig({ ...config, stop_amount_loss: parseFloat(text) || 0 })}
                    keyboardType="decimal-pad"
                    placeholder="0 = desativado"
                  />
                  <Text style={styles.hint}>
                    Valor do saldo para parar (perda). 0 = desativado
                  </Text>
                </View>
              </View>
            </View>
          )}
        </View>

        {/* Estratégias Avançadas */}
        <View style={styles.section}>
          <TouchableOpacity
            style={styles.accordionHeader}
            onPress={() => setAdvancedExpanded(!advancedExpanded)}
            activeOpacity={0.7}
          >
            <Text style={styles.sectionTitle}>Configurações de Risco</Text>
            <Ionicons
              name={advancedExpanded ? 'chevron-up' : 'chevron-down'}
              size={20}
              color="#7DD3FC"
            />
          </TouchableOpacity>

          {advancedExpanded && (
            <View style={styles.accordionContent}>
              <View style={styles.field}>
                <View style={styles.fieldHeader}>
                  <Text style={styles.label}>Soros</Text>
                  <Text style={styles.fieldValue}>{config.soros} níveis</Text>
                </View>
                <View style={styles.sliderContainer}>
                  <TextInput
                    style={styles.sliderInput}
                    value={config.soros.toString()}
                    onChangeText={(text) => setConfig({ ...config, soros: parseInt(text) || 0 })}
                    keyboardType="numeric"
                    placeholder="0"
                  />
                  <Text style={styles.sliderNote}>0 = desativado</Text>
                </View>
              </View>

              <View style={styles.field}>
                <View style={styles.fieldHeader}>
                  <Text style={styles.label}>Martingale</Text>
                  <Text style={styles.fieldValue}>{config.martingale} níveis</Text>
                </View>
                <View style={styles.sliderContainer}>
                  <TextInput
                    style={styles.sliderInput}
                    value={config.martingale.toString()}
                    onChangeText={(text) => setConfig({ ...config, martingale: parseInt(text) || 0 })}
                    keyboardType="numeric"
                    placeholder="0"
                  />
                  <Text style={styles.sliderNote}>0 = desativado</Text>
                </View>
              </View>
            </View>
          )}
        </View>

        {/* Redução Inteligente */}
        <View style={styles.section}>
          <TouchableOpacity
            style={styles.accordionHeader}
            onPress={() => setSmartReductionExpanded(!smartReductionExpanded)}
            activeOpacity={0.7}
          >
            <Text style={styles.sectionTitle}>Redução Inteligente</Text>
            <Ionicons
              name={smartReductionExpanded ? 'chevron-up' : 'chevron-down'}
              size={20}
              color="#7DD3FC"
            />
          </TouchableOpacity>

          {smartReductionExpanded && (
            <View style={styles.accordionContent}>
              <View style={styles.toggleRow}>
                <View style={styles.toggleText}>
                  <Text style={styles.label}>Ativar Redução Inteligente</Text>
                  <Text style={styles.hint}>
                    Reduz o valor da operação após sequência de perdas e restaura após sequência de ganhos.
                  </Text>
                </View>
                <Switch
                  value={config.smart_reduction_enabled}
                  onValueChange={(value) => {
                    // Impedir ativação se amount = 1
                    if (value && config.amount === 1) {
                      setAlertConfig({
                        title: 'Atenção',
                        message: 'Não é possível ativar a Redução Inteligente quando o valor da operação é $1.00. Aumente o valor da operação para usar esta funcionalidade.',
                        type: 'warning',
                        buttons: [{ text: 'OK', onPress: () => setAlertVisible(false) }],
                      });
                      setAlertVisible(true);
                      return;
                    }
                    setConfig({ ...config, smart_reduction_enabled: value });
                  }}
                  trackColor={{ false: '#1C1F2A', true: '#7DD3FC' }}
                  thumbColor={config.smart_reduction_enabled ? '#0F172A' : '#94A3B8'}
                  ios_backgroundColor="#1C1F2A"
                />
              </View>

              {config.smart_reduction_enabled && (
                <>
                  <View style={styles.toggleRow}>
                    <View style={styles.toggleText}>
                      <Text style={styles.label}>Caducar Redução (Cascata)</Text>
                      <Text style={styles.hint}>
                        Quando ativado, se já estiver em redução e atingir o trigger de losses novamente, aplica outra redução sobre o valor já reduzido. Mínimo: $1.00
                      </Text>
                    </View>
                    <Switch
                      value={config.smart_reduction_cascading}
                      onValueChange={(value) => setConfig({ ...config, smart_reduction_cascading: value })}
                      trackColor={{ false: '#1C1F2A', true: '#7DD3FC' }}
                      thumbColor={config.smart_reduction_cascading ? '#0F172A' : '#94A3B8'}
                      ios_backgroundColor="#1C1F2A"
                    />
                  </View>

                  <View style={styles.field}>
                    <View style={styles.fieldHeader}>
                      <Text style={styles.label}>Losses Consecutivos para Reduzir</Text>
                      <Text style={styles.fieldValue}>{config.smart_reduction_loss_trigger} losses</Text>
                    </View>
                    <TextInput
                      style={styles.input}
                      value={config.smart_reduction_loss_trigger?.toString()}
                      onChangeText={(text) => setConfig({ ...config, smart_reduction_loss_trigger: parseInt(text) || 3 })}
                      keyboardType="numeric"
                      placeholder="3"
                    />
                    <Text style={styles.hint}>
                      Número de perdas consecutivas para reduzir o valor da operação.
                    </Text>
                  </View>

                  <View style={styles.field}>
                    <View style={styles.fieldHeader}>
                      <Text style={styles.label}>Wins Consecutivos para Restaurar</Text>
                      <Text style={styles.fieldValue}>{config.smart_reduction_win_restore} wins</Text>
                    </View>
                    <TextInput
                      style={styles.input}
                      value={config.smart_reduction_win_restore?.toString()}
                      onChangeText={(text) => setConfig({ ...config, smart_reduction_win_restore: parseInt(text) || 2 })}
                      keyboardType="numeric"
                      placeholder="2"
                    />
                    <Text style={styles.hint}>
                      Número de vitórias consecutivas para voltar ao valor normal.
                    </Text>
                  </View>

                  <View style={styles.field}>
                    <View style={styles.fieldHeader}>
                      <Text style={styles.label}>Percentual de Redução (%)</Text>
                      <Text style={styles.fieldValue}>{config.smart_reduction_percentage}%</Text>
                    </View>
                    <TextInput
                      style={styles.input}
                      value={config.smart_reduction_percentage?.toString()}
                      onChangeText={(text) => setConfig({ ...config, smart_reduction_percentage: parseInt(text) || 50 })}
                      keyboardType="numeric"
                      placeholder="50"
                    />
                    <Text style={styles.hint}>
                      Percentual de redução do valor da operação (ex: 50% reduz pela metade).
                    </Text>
                  </View>
                </>
              )}
            </View>
          )}
        </View>

        {/* Controle */}
        <View style={styles.section}>
          <TouchableOpacity
            style={styles.accordionHeader}
            onPress={() => setControlExpanded(!controlExpanded)}
            activeOpacity={0.7}
          >
            <Text style={styles.sectionTitle}>Configurações de Tempo</Text>
            <Ionicons
              name={controlExpanded ? 'chevron-up' : 'chevron-down'}
              size={20}
              color="#7DD3FC"
            />
          </TouchableOpacity>

          {controlExpanded && (
            <View style={styles.accordionContent}>
              <View style={styles.field}>
                <Text style={styles.label}>Cooldown (segundos)</Text>
                <Text style={styles.hint}>Formato: número fixo (ex: 30) ou intervalo randomizado (ex: 5-30)</Text>
                <TextInput
                  style={styles.input}
                  value={config.cooldown_seconds?.toString() || '0'}
                  onChangeText={(text) => {
                    // Aceitar números ou formato "min-max" para cooldown randomizado
                    const isValid = /^\d+$|^\d+-\d+$/.test(text) || text === '';
                    if (isValid || text === '') {
                      setConfig({ ...config, cooldown_seconds: text || '0' });
                    }
                  }}
                  keyboardType="default"
                  placeholder="0 ou 5-30"
                />
              </View>
            </View>
          )}
        </View>

        {error && (
          <View style={styles.errorContainer}>
            <Ionicons name="warning" size={20} color="#F87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        <View style={styles.actions}>
          <TouchableOpacity
            style={styles.cancelButton}
            onPress={() => navigation.goBack()}
            disabled={loading}
          >
            <Text style={styles.cancelButtonText}>Cancelar</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.saveButton, loading && styles.saveButtonDisabled]}
            onPress={handleSave}
            disabled={loading}
          >
            {loading ? (
              <Text style={styles.saveButtonText}>Salvando...</Text>
            ) : (
              <>
                <Ionicons name="checkmark" size={18} color="#0F172A" />
                <Text style={styles.saveButtonText}>Salvar</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
      </>
      )}
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
  scrollContent: {
    padding: 20,
    paddingBottom: 100,
    gap: 24,
  },
  section: {
    gap: 16,
  },
  sectionTitle: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  emptyState: {
    alignItems: 'center',
    padding: 20,
    gap: 12,
  },
  emptyText: {
    color: colors.textSoft,
    fontSize: 14,
  },
  accountSelector: {
    gap: 8,
  },
  accountOption: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  accountOptionActive: {
    backgroundColor: colors.primarySoft,
    borderColor: colors.primary,
  },
  accountName: {
    color: colors.textMuted,
    fontSize: 14,
  },
  accountNameActive: {
    color: colors.primary,
    fontWeight: '500',
  },
  field: {
    gap: 8,
  },
  fieldHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  label: {
    color: colors.textMuted,
    fontSize: 14,
  },
  fieldValue: {
    color: colors.text,
    fontSize: 14,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
    padding: 12,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  toggleText: {
    flex: 1,
    gap: 6,
  },
  input: {
    backgroundColor: colors.surfaceAlt,
    color: colors.text,
    fontSize: 16,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  timeframeOptions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  timeframeButton: {
    width: '23%',
    padding: 12,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  timeframeButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  timeframeButtonDisabled: {
    opacity: 0.3,
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.border,
  },
  timeframeButtonText: {
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: '500',
  },
  timeframeButtonTextActive: {
    color: colors.primaryText,
  },
  timeframeButtonTextDisabled: {
    color: '#475569',
  },
  sliderContainer: {
    gap: 8,
  },
  sliderInput: {
    backgroundColor: colors.surfaceAlt,
    color: colors.text,
    fontSize: 16,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sliderNote: {
    color: colors.textSoft,
    fontSize: 12,
  },
  hint: {
    color: colors.textSoft,
    fontSize: 12,
    marginTop: 4,
  },
  timingButton: {
    flex: 1,
    padding: 12,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  timingButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  timingButtonText: {
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: '500',
  },
  timingButtonTextActive: {
    color: colors.primaryText,
  },
  accordionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  accordionContent: {
    gap: 16,
    paddingTop: 16,
  },
  subsection: {
    gap: 12,
  },
  subsectionTitle: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    padding: 12,
    borderRadius: 12,
    marginBottom: 16,
  },
  errorText: {
    color: colors.danger,
    fontSize: 14,
  },
  actions: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
  },
  cancelButton: {
    flex: 1,
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.borderStrong,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  cancelButtonText: {
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: '500',
  },
  saveButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.primary,
  },
  saveButtonDisabled: {
    opacity: 0.5,
  },
  saveButtonText: {
    color: colors.primaryText,
    fontSize: 14,
    fontWeight: '600',
  },
});
