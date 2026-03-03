import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import ConfirmModal from '../components/ConfirmModal';
import { accountService } from '../services/account';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function SsidRegistrationScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const [demoSsid, setDemoSsid] = useState('');
  const [realSsid, setRealSsid] = useState('');
  const [errors, setErrors] = useState<{ demoSsid?: string; realSsid?: string }>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingData, setIsLoadingData] = useState(false);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showErrorModal, setShowErrorModal] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    loadAccountData();
  }, []);

  const loadAccountData = async () => {
    try {
      setIsLoadingData(true);
      const accounts = await accountService.getAccounts();
      if (accounts.length > 0) {
        const account = accounts[0];
        setAccountId(account.id);
        setDemoSsid(account.ssid_demo || '');
        setRealSsid(account.ssid_real || '');
      }
    } catch (error: any) {
      console.error('Error loading account data:', error);
    } finally {
      setIsLoadingData(false);
    }
  };

  const validateSsid = (ssid: string): boolean => {
    return ssid.length >= 4;
  };

  const handleSaveSsid = () => {
    const newErrors: { demoSsid?: string; realSsid?: string } = {};

    if (!demoSsid.trim()) {
      newErrors.demoSsid = 'SSID Demo é obrigatório';
    } else if (!validateSsid(demoSsid)) {
      newErrors.demoSsid = 'SSID Demo deve ter pelo menos 4 caracteres';
    }

    if (!realSsid.trim()) {
      newErrors.realSsid = 'SSID Real é obrigatório';
    } else if (!validateSsid(realSsid)) {
      newErrors.realSsid = 'SSID Real deve ter pelo menos 4 caracteres';
    }

    setErrors(newErrors);

    if (Object.keys(newErrors).length > 0) {
      return;
    }

    setShowConfirmModal(true);
  };

  const confirmSaveSsid = async () => {
    setIsLoading(true);

    try {
      if (!accountId) {
        setErrorMessage('Nenhuma conta encontrada');
        setShowErrorModal(true);
        return;
      }

      await accountService.updateAccount(accountId, {
        ssid_demo: demoSsid,
        ssid_real: realSsid,
      });

      setShowSuccessModal(true);
    } catch (error: any) {
      setErrorMessage(error.message || 'Falha ao salvar SSIDs');
      setShowErrorModal(true);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSuccessClose = () => {
    setShowSuccessModal(false);
    navigation.goBack();
  };

  const handleResetSsids = () => {
    Alert.alert(
      'Resetar SSIDs',
      'Deseja resetar os SSIDs Demo e Real? Isso apagará os SSIDs atuais.',
      [
        { text: 'Cancelar', style: 'cancel' },
        { 
          text: 'Resetar', 
          onPress: async () => {
            try {
              if (!accountId) {
                setErrorMessage('Nenhuma conta encontrada');
                setShowErrorModal(true);
                return;
              }

              console.log('[Reset SSIDs] Resetando SSIDs para conta:', accountId);
              
              const result = await accountService.updateAccount(accountId, {
                ssid_demo: null as any,
                ssid_real: null as any,
              });

              console.log('[Reset SSIDs] Resultado da atualização:', result);

              setDemoSsid('');
              setRealSsid('');
              
              // Recarregar dados da conta para garantir que os campos estejam atualizados
              await loadAccountData();
              
              console.log('[Reset SSIDs] SSIDs após reset:', {
                demoSsid: demoSsid,
                realSsid: realSsid
              });
              
              Alert.alert('Sucesso', 'SSIDs resetados com sucesso!');
            } catch (error: any) {
              console.error('[Reset SSIDs] Erro ao resetar SSIDs:', error);
              setErrorMessage(error.message || 'Falha ao resetar SSIDs');
              setShowErrorModal(true);
            }
          }
        }
      ]
    );
  };

  if (isLoadingData) {
    return (
      <View style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <View style={styles.loadingContainer}>
            <Text style={styles.loadingText}>Carregando dados...</Text>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <View style={styles.content}>
            <TouchableOpacity
              style={styles.backButton}
              onPress={() => navigation.goBack()}
            >
              <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
            </TouchableOpacity>

            <Text style={styles.title}>Cadastrar SSIDs</Text>
            <Text style={styles.subtitle}>
              Configure seus identificadores de conta para operações demo e real
            </Text>

            <View style={styles.form}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>SSID Demo</Text>
                <TextInput
                  style={[styles.input, errors.demoSsid && styles.inputError]}
                  placeholder="Ex: DEMO12345"
                  value={demoSsid}
                  onChangeText={setDemoSsid}
                  autoCapitalize="characters"
                  autoCorrect={false}
                />
                {errors.demoSsid && <Text style={styles.errorText}>{errors.demoSsid}</Text>}
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>SSID Real</Text>
                <TextInput
                  style={[styles.input, errors.realSsid && styles.inputError]}
                  placeholder="Ex: REAL67890"
                  value={realSsid}
                  onChangeText={setRealSsid}
                  autoCapitalize="characters"
                  autoCorrect={false}
                />
                {errors.realSsid && <Text style={styles.errorText}>{errors.realSsid}</Text>}
              </View>

              <View style={styles.infoBox}>
                <Ionicons name="information-circle-outline" size={24} color="#007AFF" />
                <View style={styles.infoContent}>
                  <Text style={styles.infoTitle}>Sobre SSIDs</Text>
                  <Text style={styles.infoText}>
                    SSIDs são identificadores únicos para suas contas de trading. O SSID Demo é usado para operações de teste e o SSID Real para operações com dinheiro real.
                  </Text>
                </View>
              </View>

              <View style={styles.buttonGroup}>
                <TouchableOpacity
                  style={[styles.button, styles.buttonHalf]}
                  onPress={() => navigation.navigate('ExtractSsidDemo' as never)}
                >
                  <Ionicons name="play-circle-outline" size={20} color={colors.primaryText} style={styles.buttonIcon} />
                  <Text style={[styles.buttonText, styles.buttonTextWithIcon]}>
                    Extrair Demo
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[styles.button, styles.buttonHalf]}
                  onPress={() => navigation.navigate('ExtractSsidReal' as never)}
                >
                  <Ionicons name="play-circle-outline" size={20} color={colors.primaryText} style={styles.buttonIcon} />
                  <Text style={[styles.buttonText, styles.buttonTextWithIcon]}>
                    Extrair Real
                  </Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={styles.resetSsidButton}
                onPress={handleResetSsids}
              >
                <Ionicons name="refresh" size={20} color={colors.text} style={styles.buttonIcon} />
                <Text style={[styles.buttonText, styles.buttonTextWithIcon]}>
                  Resetar SSIDs
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>

      <ConfirmModal
        visible={showConfirmModal}
        title="Salvar SSIDs"
        message="Deseja salvar as alterações nos SSIDs?"
        confirmText="Salvar"
        cancelText="Cancelar"
        type="info"
        onConfirm={confirmSaveSsid}
        onCancel={() => setShowConfirmModal(false)}
      />

      <ConfirmModal
        visible={showSuccessModal}
        title="Sucesso"
        message="SSIDs salvos com sucesso!"
        confirmText="OK"
        type="info"
        onConfirm={handleSuccessClose}
        onCancel={handleSuccessClose}
      />

      <ConfirmModal
        visible={showErrorModal}
        title="Erro"
        message={errorMessage}
        confirmText="OK"
        type="danger"
        onConfirm={() => setShowErrorModal(false)}
        onCancel={() => setShowErrorModal(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safeArea: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  content: {
    flex: 1,
    padding: 20,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: colors.textMuted,
    marginBottom: 40,
  },
  form: {
    width: '100%',
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 8,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    color: colors.text,
  },
  inputError: {
    borderColor: colors.danger,
  },
  errorText: {
    color: colors.danger,
    fontSize: 12,
    marginTop: 4,
  },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: colors.surfaceAlt,
    padding: 16,
    borderRadius: 12,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoContent: {
    flex: 1,
    marginLeft: 12,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 4,
  },
  infoText: {
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 16,
  },
  button: {
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonDisabled: {
    backgroundColor: colors.surfaceAlt,
  },
  buttonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 40,
  },
  loadingText: {
    fontSize: 16,
    color: colors.textMuted,
  },
  buttonGroup: {
    flexDirection: 'row',
    gap: 12,
  },
  buttonHalf: {
    flex: 1,
  },
  buttonIcon: {
    marginRight: 8,
  },
  buttonTextWithIcon: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  resetSsidButton: {
    marginTop: 12,
    backgroundColor: '#FF5252',
    borderWidth: 1,
    borderColor: '#FF5252',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
    borderRadius: 12,
  },
});
