import React, { useState, useMemo, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
  Switch,
  TextInput,
  Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { Ionicons } from '@expo/vector-icons';
import ConfirmModal from '../components/ConfirmModal';
import { apiClient } from '../services/api';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function ConfiguracoesScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const { user, logout, fetchUser } = useAuth();
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [darkModeEnabled, setDarkModeEnabled] = useState(true);
  const [showLogoutModal, setShowLogoutModal] = useState(false);
  const [showTelegramModal, setShowTelegramModal] = useState(false);
  const [telegramUsername, setTelegramUsername] = useState('');
  const [telegramLinked, setTelegramLinked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [successTitle, setSuccessTitle] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [showErrorModal, setShowErrorModal] = useState(false);
  const [errorTitle, setErrorTitle] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [userRole, setUserRole] = useState<'free' | 'vip' | 'vip_plus'>('free');
  const [vipEndDate, setVipEndDate] = useState<string | null>(null);

  // Carregar dados do usuário ao montar o componente
  useEffect(() => {
    fetchUser();
    loadUserInfo();
  }, []);

  useEffect(() => {
    if (user?.telegram_chat_id || user?.telegram_username) {
      setTelegramLinked(true);
      if (user?.telegram_username) {
        setTelegramUsername(user.telegram_username);
      }
    }
  }, [user]);

  const loadUserInfo = async () => {
    try {
      console.log('[ConfiguracoesScreen] Carregando dados do usuário...');
      const userData = await apiClient.get('/users/me');
      console.log('[ConfiguracoesScreen] Dados do usuário:', userData);
      console.log('[ConfiguracoesScreen] role:', userData.role);
      console.log('[ConfiguracoesScreen] vip_end_date:', userData.vip_end_date);
      setUserRole(userData.role || 'free');
      setVipEndDate(userData.vip_end_date || null);
    } catch (err) {
      console.error('Error loading user info:', err);
      // Definir valores padrão em caso de erro
      setUserRole('free');
      setVipEndDate(null);
    }
  };

  const getRoleInfo = () => {
    const roleMap = {
      free: { label: 'Free', color: '#94A3B8', icon: 'person-outline' },
      vip: { label: 'VIP', color: '#FBBF24', icon: 'star-outline' },
      vip_plus: { label: 'VIP+', color: '#7DD3FC', icon: 'star' }
    };
    return roleMap[userRole] || roleMap.free;
  };

  const getVipStatus = () => {
    if (userRole === 'free') return null;
    if (!vipEndDate) return 'Ativo';
    const now = new Date();
    const end = new Date(vipEndDate);
    const daysRemaining = Math.ceil((end.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
    if (daysRemaining <= 0) return 'Expirado';
    return `${daysRemaining} dias restantes`;
  };

  // Carregar dados do usuário ao abrir o modal
  const handleOpenTelegramModal = () => {
    if (user?.telegram_username) {
      setTelegramUsername(user.telegram_username);
      setTelegramLinked(true);
    } else {
      setTelegramUsername('');
      setTelegramLinked(false);
    }
    setShowTelegramModal(true);
  };

  const handleLogout = async () => {
    await logout();
    navigation.reset({
      index: 0,
      routes: [{ name: 'Login' as never }],
    });
  };

  const handleLinkTelegram = async () => {
    if (!telegramUsername.trim()) {
      setErrorTitle('Erro');
      setErrorMessage('Por favor, informe seu @username do Telegram');
      setShowErrorModal(true);
      return;
    }

    setLoading(true);
    try {
      await apiClient.post('/users/me/link-telegram', {
        telegram_username: telegramUsername.startsWith('@') ? telegramUsername : `@${telegramUsername}`,
      });

      await fetchUser();
      setShowTelegramModal(false);
      setSuccessTitle('✅ Telegram Vinculado!');
      setSuccessMessage('Você receberá notificações de Stop Loss/Stop Gain no Telegram.');
      setShowSuccessModal(true);
    } catch (error: any) {
      setErrorTitle('Erro');
      setErrorMessage(error.response?.data?.detail || 'Erro ao vincular Telegram');
      setShowErrorModal(true);
    } finally {
      setLoading(false);
    }
  };

  const handleUnlinkTelegram = async () => {
    setLoading(true);
    try {
      await apiClient.delete('/users/me/unlink-telegram');
      await fetchUser();
      setTelegramLinked(false);
      setTelegramUsername('');
      setSuccessTitle('✅ Telegram Desvinculado');
      setSuccessMessage('Você não receberá mais notificações no Telegram.');
      setShowSuccessModal(true);
      setShowTelegramModal(false);
    } catch (error: any) {
      setErrorTitle('Erro');
      setErrorMessage(error.response?.data?.detail || 'Erro ao desvincular Telegram');
      setShowErrorModal(true);
    } finally {
      setLoading(false);
    }
  };

  const settings = useMemo(() => [
    {
      id: 'profile',
      icon: 'person-outline',
      label: 'Perfil',
      description: 'Editar informações pessoais',
      action: () => navigation.navigate('Profile' as never),
    },
    {
      id: 'telegram',
      icon: 'paper-plane-outline',
      label: 'Telegram',
      description: telegramLinked ? 'Vinculado' : 'Não vinculado',
      action: handleOpenTelegramModal,
    },
    {
      id: 'theme',
      icon: 'color-palette-outline',
      label: 'Tema',
      description: 'Aparência do aplicativo',
      switch: true,
      value: darkModeEnabled,
      onValueChange: setDarkModeEnabled,
    },
  ], [telegramLinked, darkModeEnabled, handleOpenTelegramModal]);

  const accountSettings = [
    {
      id: 'ssid',
      icon: 'key-outline',
      label: 'SSIDs',
      description: 'Configurar identificadores de conta',
      action: () => navigation.navigate('SsidRegistration' as never),
    },
    {
      id: 'security',
      icon: 'lock-closed-outline',
      label: 'Segurança',
      description: 'Senha e autenticação',
      action: () => navigation.navigate('Security' as never),
    },
  ];

  const roleInfo = getRoleInfo();
  const vipStatus = getVipStatus();

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.content}>
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Configurações</Text>
        </View>

        {/* Seção Plano */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Plano</Text>
          <View style={styles.planCard}>
            <View style={styles.planHeader}>
              <Ionicons name={roleInfo.icon as any} size={20} color={roleInfo.color} />
              <Text style={[styles.planTitle, { color: roleInfo.color }]}>{roleInfo.label}</Text>
            </View>
            {vipStatus && (
              <Text style={styles.planStatus}>{vipStatus}</Text>
            )}
            {user?.is_superuser && (
              <View style={styles.adminBadge}>
                <Ionicons name="shield-checkmark" size={14} color="#FFFFFF" />
                <Text style={styles.adminBadgeText}>Administrador</Text>
              </View>
            )}
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Geral</Text>
          {settings.slice(0, 2).map((setting) => (
            <TouchableOpacity
              key={setting.id}
              style={styles.settingItem}
              onPress={setting.action}
              activeOpacity={setting.switch ? 1 : 0.7}
            >
              <View style={styles.settingIconContainer}>
                <Ionicons name={setting.icon as any} size={24} color="#007AFF" />
              </View>
              <View style={styles.settingInfo}>
                <Text style={styles.settingLabel}>{setting.label}</Text>
                <Text style={styles.settingDescription}>{setting.description}</Text>
              </View>
              {setting.switch ? (
                <Switch
                  value={setting.value}
                  onValueChange={setting.onValueChange}
                  trackColor={{ false: '#3A3A3A', true: '#007AFF' }}
                  thumbColor={setting.value ? '#FFFFFF' : '#8E8E93'}
                  ios_backgroundColor="#3A3A3A"
                />
              ) : (
                <Ionicons name="chevron-forward" size={20} color="#8E8E93" />
              )}
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Conta</Text>
          {accountSettings.map((setting) => (
            <TouchableOpacity
              key={setting.id}
              style={styles.settingItem}
              onPress={setting.action}
            >
              <View style={styles.settingIconContainer}>
                <Ionicons name={setting.icon as any} size={24} color="#007AFF" />
              </View>
              <View style={styles.settingInfo}>
                <Text style={styles.settingLabel}>{setting.label}</Text>
                <Text style={styles.settingDescription}>{setting.description}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color="#8E8E93" />
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Aplicativo</Text>
          {settings.slice(3).map((setting) => (
            <TouchableOpacity
              key={setting.id}
              style={styles.settingItem}
              onPress={setting.action}
              activeOpacity={setting.switch ? 1 : 0.7}
            >
              <View style={styles.settingIconContainer}>
                <Ionicons name={setting.icon as any} size={24} color="#007AFF" />
              </View>
              <View style={styles.settingInfo}>
                <Text style={styles.settingLabel}>{setting.label}</Text>
                <Text style={styles.settingDescription}>{setting.description}</Text>
              </View>
              {setting.switch ? (
                <Switch
                  value={setting.value}
                  onValueChange={setting.onValueChange}
                  trackColor={{ false: '#3A3A3A', true: '#007AFF' }}
                  thumbColor={setting.value ? '#FFFFFF' : '#8E8E93'}
                  ios_backgroundColor="#3A3A3A"
                />
              ) : (
                <Ionicons name="chevron-forward" size={20} color="#8E8E93" />
              )}
            </TouchableOpacity>
          ))}
        </View>

        <TouchableOpacity style={styles.logoutButton} onPress={() => setShowLogoutModal(true)}>
          <Ionicons name="log-out-outline" size={24} color="#FFFFFF" />
          <Text style={styles.logoutButtonText}>Sair da conta</Text>
        </TouchableOpacity>

        <Text style={styles.versionText}>TunesTrade v1.0.0</Text>
      </ScrollView>

      <ConfirmModal
        visible={showLogoutModal}
        title="Sair da conta"
        message="Tem certeza que deseja sair da sua conta?"
        confirmText="Sair"
        cancelText="Cancelar"
        type="danger"
        onConfirm={handleLogout}
        onCancel={() => setShowLogoutModal(false)}
      />

      <Modal
        visible={showTelegramModal}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setShowTelegramModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Configurar Telegram</Text>
              <TouchableOpacity onPress={() => setShowTelegramModal(false)}>
                <Ionicons name="close" size={24} color="#E2E8F0" />
              </TouchableOpacity>
            </View>

            <View style={styles.modalBody}>
              <View style={styles.infoBox}>
                <Ionicons name="information-circle-outline" size={24} color="#7DD3FC" />
                <View style={styles.infoContent}>
                  <Text style={styles.infoTitle}>Como configurar:</Text>
                  <Text style={styles.infoText}>
                    1. Abra o Telegram e procure por @tunestrade_bot
                    {'\n'}2. Envie qualquer mensagem para o bot
                    {'\n'}3. Informe seu @username abaixo
                  </Text>
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>@username do Telegram</Text>
                <TextInput
                  style={styles.input}
                  placeholder="@seuusername"
                  placeholderTextColor="#94A3B8"
                  value={telegramUsername}
                  onChangeText={setTelegramUsername}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>

              {telegramLinked && (
                <TouchableOpacity
                  style={styles.unlinkButton}
                  onPress={handleUnlinkTelegram}
                  disabled={loading}
                >
                  <Ionicons name="trash-outline" size={20} color="#F87171" />
                  <Text style={styles.unlinkButtonText}>Desvincular Telegram</Text>
                </TouchableOpacity>
              )}

              <TouchableOpacity
                style={[styles.button, loading && styles.buttonDisabled]}
                onPress={handleLinkTelegram}
                disabled={loading}
              >
                {loading ? (
                  <Text style={styles.buttonText}>Carregando...</Text>
                ) : (
                  <Text style={styles.buttonText}>Salvar</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal
        visible={showSuccessModal}
        animationType="fade"
        transparent={true}
        onRequestClose={() => setShowSuccessModal(false)}
      >
        <View style={styles.successOverlay}>
          <View style={styles.successContainer}>
            <View style={styles.successIconContainer}>
              <Ionicons name="checkmark-circle" size={48} color="#34C759" />
            </View>
            <Text style={styles.successTitle}>{successTitle}</Text>
            <Text style={styles.successMessage}>{successMessage}</Text>
            <TouchableOpacity
              style={styles.successButton}
              onPress={() => setShowSuccessModal(false)}
            >
              <Text style={styles.successButtonText}>OK</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      <Modal
        visible={showErrorModal}
        animationType="fade"
        transparent={true}
        onRequestClose={() => setShowErrorModal(false)}
      >
        <View style={styles.successOverlay}>
          <View style={styles.successContainer}>
            <View style={styles.successIconContainer}>
              <Ionicons name="alert-circle" size={48} color="#F87171" />
            </View>
            <Text style={styles.successTitle}>{errorTitle}</Text>
            <Text style={styles.successMessage}>{errorMessage}</Text>
            <TouchableOpacity
              style={[styles.successButton, styles.errorButton]}
              onPress={() => setShowErrorModal(false)}
            >
              <Text style={styles.successButtonText}>OK</Text>
            </TouchableOpacity>
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
  safeArea: {
    flex: 1,
  },
  content: {
    flex: 1,
  },
  header: {
    padding: 20,
    paddingTop: 10,
  },
  headerTitle: {
    fontSize: 32,
    fontWeight: '700',
    color: colors.text,
  },
  userSection: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    margin: 20,
    padding: 20,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
  },
  userAvatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  userInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 4,
  },
  userEmail: {
    fontSize: 14,
    color: colors.textMuted,
  },
  editButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
  },
  section: {
    marginTop: 24,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textMuted,
    textTransform: 'uppercase',
    marginBottom: 12,
    paddingHorizontal: 20,
  },
  settingItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    padding: 16,
    marginHorizontal: 20,
    marginBottom: 8,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
  },
  settingIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  settingInfo: {
    flex: 1,
  },
  settingLabel: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 2,
  },
  settingDescription: {
    fontSize: 14,
    color: colors.textMuted,
  },
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.danger,
    margin: 20,
    padding: 16,
    borderRadius: 12,
  },
  logoutButtonText: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 8,
  },
  versionText: {
    fontSize: 12,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 20,
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
    borderColor: colors.border,
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
    backgroundColor: colors.surface,
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
    marginBottom: 16,
  },
  buttonDisabled: {
    backgroundColor: colors.surfaceAlt,
  },
  buttonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '700',
  },
  skipButton: {
    alignItems: 'center',
  },
  skipButtonText: {
    color: colors.textMuted,
    fontSize: 14,
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
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 24,
    width: '100%',
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  modalBody: {
    width: '100%',
  },
  unlinkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    padding: 12,
    borderRadius: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.3)',
  },
  unlinkButtonText: {
    color: colors.danger,
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 8,
  },
  successOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  successContainer: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 24,
    width: '100%',
    maxWidth: 400,
    borderWidth: 1,
    borderColor: colors.border,
  },
  successIconContainer: {
    alignItems: 'center',
    marginBottom: 16,
  },
  successTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 8,
  },
  successMessage: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 20,
  },
  successButton: {
    backgroundColor: colors.primary,
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  successButtonText: {
    color: colors.primaryText,
    fontSize: 14,
    fontWeight: '600',
  },
  errorButton: {
    backgroundColor: '#FF3B30',
  },
  planCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 20,
    marginHorizontal: 20,
    marginBottom: 8,
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
    marginTop: 4,
  },
  adminBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.success,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    marginTop: 8,
    alignSelf: 'flex-start',
  },
  adminBadgeText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '600',
    marginLeft: 4,
  },
});
