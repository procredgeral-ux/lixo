import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, ActivityIndicator, Modal } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { apiClient } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { CustomAlert } from '../components/CustomAlert';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

interface MenuItem {
  id: string;
  icon: string;
  label: string;
}

interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  vip_start_date: string | null;
  vip_end_date: string | null;
}

const menuItems: MenuItem[] = [
  { id: 'dashboard', icon: 'bar-chart-outline', label: 'Dashboard' },
  { id: 'estrategias', icon: 'trending-up-outline', label: 'Estratégias' },
  { id: 'sinais', icon: 'trending-down-outline', label: 'Sinais' },
  { id: 'historico', icon: 'list-outline', label: 'Histórico' },
  { id: 'configuracoes', icon: 'settings-outline', label: 'Configurações' },
];

export default function AdminScreen() {
  const navigation = useNavigation();
  const { logout } = useAuth();
  const { user: currentUser } = useAuth();

  const [searchEmail, setSearchEmail] = useState('');
  const [searching, setSearching] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<'free' | 'vip' | 'vip_plus' | null>(null);
  const [durationDays, setDurationDays] = useState(7);
  const [updating, setUpdating] = useState(false);
  const [alertVisible, setAlertVisible] = useState(false);
  const [alertConfig, setAlertConfig] = useState<{ title: string; message: string; type?: 'success' | 'error' | 'warning' | 'info' } | null>(null);
  const [selectedItem, setSelectedItem] = useState('dashboard');
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);

  // Atualizar duração automaticamente ao selecionar plano
  const handlePlanSelect = (plan: 'free' | 'vip' | 'vip_plus') => {
    setSelectedPlan(plan);
    if (plan === 'vip') {
      setDurationDays(7);
    } else if (plan === 'vip_plus') {
      setDurationDays(30);
    } else if (plan === 'free') {
      setDurationDays(0);
    }
  };

  // Carregar usuários ao montar o componente
  useEffect(() => {
    if (currentUser) {
      // Pequeno delay para garantir que o token esteja configurado
      setTimeout(() => {
        loadAllUsers();
      }, 100);
    }
  }, [currentUser]); // Re-carregar quando o usuário mudar

  const handleLogout = async () => {
    await logout();
    navigation.reset({
      index: 0,
      routes: [{ name: 'Login' as never }],
    });
  };

  const handleMenuPress = (item: MenuItem) => {
    setSelectedItem(item.id);
    switch (item.id) {
      case 'dashboard':
        navigation.navigate('Dashboard' as never);
        break;
      case 'estrategias':
        navigation.navigate('Estrategias' as never);
        break;
      case 'sinais':
        navigation.navigate('Sinais' as never);
        break;
      case 'historico':
        navigation.navigate('Historico' as never);
        break;
      case 'configuracoes':
        navigation.navigate('Configuracoes' as never);
        break;
    }
  };

  const loadAllUsers = async () => {
    setLoadingUsers(true);
    try {
      console.log('[AdminScreen] Carregando usuários...');
      const response = await apiClient.get<any>('/admin/users');
      console.log('[AdminScreen] Usuários carregados:', response.length);
      setAllUsers(response);
      setError(null);
    } catch (err: any) {
      console.error('[AdminScreen] Erro ao carregar usuários:', err.message);
      setError('Erro ao carregar usuários. Tente fazer logout e login novamente.');
    } finally {
      setLoadingUsers(false);
    }
  };

  const handleSearchUser = async () => {
    if (!searchEmail.trim()) {
      setError('Por favor, informe o termo de busca');
      return;
    }

    setSearching(true);
    setError(null);
    setUser(null);

    try {
      console.log('[AdminScreen] Buscando usuários com termo:', searchEmail);
      const response = await apiClient.get<any>(`/admin/users?search=${encodeURIComponent(searchEmail)}`);
      console.log('[AdminScreen] Usuários encontrados:', response.length);
      setAllUsers(response);
      setError(null);
    } catch (err: any) {
      console.error('[AdminScreen] Erro na busca:', err);
      setError('Nenhum usuário encontrado');
      setAllUsers([]);
    } finally {
      setSearching(false);
    }
  };

  const handleGrantVIP = async () => {
    if (!user || !selectedPlan) return;

    setUpdating(true);
    try {
      // Enviar como Query parameters em vez de body
      const response = await apiClient.put<any>(
        `/admin/users/${user.id}/plan?role=${selectedPlan}&duration_days=${durationDays}`,
        {}
      );

      // Atualizar usuário localmente
      if (selectedPlan === 'free') {
        setUser({
          ...user,
          role: 'free',
          vip_start_date: null,
          vip_end_date: null,
        });
      } else {
        setUser({
          ...user,
          role: selectedPlan,
          vip_start_date: new Date().toISOString(),
          vip_end_date: new Date(Date.now() + durationDays * 24 * 60 * 60 * 1000).toISOString(),
        });
      }

      // Recarregar lista de usuários para atualizar a tabela
      await loadAllUsers();

      setAlertConfig({
        title: 'Sucesso',
        message: `Plano ${selectedPlan.toUpperCase()} ${selectedPlan === 'free' ? 'definido' : 'concedido'} para ${user.name}!`,
        type: 'success',
      });
      setAlertVisible(true);
      
      // Fechar modal após sucesso
      setModalVisible(false);
    } catch (err: any) {
      console.error('[AdminScreen] Erro ao atualizar plano:', err);
      setError(err.response?.data?.detail || 'Erro ao atualizar plano');
    } finally {
      setUpdating(false);
    }
  };

  const getPlanInfo = () => {
    if (!user) return null;

    const now = new Date();
    const vipStart = user.vip_start_date ? new Date(user.vip_start_date) : null;
    const vipEnd = user.vip_end_date ? new Date(user.vip_end_date) : null;

    let label = 'Free';
    let color = '#94A3B8';
    let icon = 'person-outline';
    let status = 'N/A';

    if (user.role === 'vip' || user.role === 'vip_plus') {
      if (vipEnd && now > vipEnd) {
        label = 'VIP Expirado';
        color = '#EF4444';
        icon = 'alert-circle-outline';
        status = 'Expirado';
      } else if (vipStart && vipEnd) {
        const daysRemaining = Math.ceil((vipEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
        label = user.role === 'vip_plus' ? 'VIP+' : 'VIP';
        color = user.role === 'vip_plus' ? '#7DD3FC' : '#FBBF24';
        icon = user.role === 'vip_plus' ? 'star' : 'star-outline';
        status = `${daysRemaining} dias restantes`;
      }
    }

    return { label, color, icon, status };
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('pt-BR');
  };

  const getPlanColor = (role: string) => {
    switch (role) {
      case 'vip_plus':
        return '#7DD3FC';
      case 'vip':
        return '#FBBF24';
      default:
        return '#94A3B8';
    }
  };

  const getPlanLabel = (role: string) => {
    switch (role) {
      case 'vip_plus':
        return 'VIP+';
      case 'vip':
        return 'VIP';
      default:
        return 'Free';
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      {/* Header com botão de logout */}
      <View style={styles.header}>
        <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={24} color="#EF4444" />
        </TouchableOpacity>
        <View style={styles.headerContent}>
          <Text style={styles.headerTitle}>Administração</Text>
          <Text style={styles.headerSubtitle}>Gerenciar planos VIP dos usuários</Text>
        </View>
      </View>

      <ScrollView style={styles.content}>
        {/* Busca de usuário */}
        <View style={styles.searchSection}>
          <Text style={styles.sectionTitle}>Buscar Usuário</Text>
          <View style={styles.searchInputContainer}>
            <Ionicons name="search-outline" size={20} color="#64748B" style={styles.searchIcon} />
            <TextInput
              style={styles.searchInput}
              placeholder="Email do usuário"
              value={searchEmail}
              onChangeText={setSearchEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholderTextColor="#94A3B8"
            />
            <TouchableOpacity style={styles.searchButton} onPress={handleSearchUser}>
              {searching ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <Ionicons name="arrow-forward" size={20} color="#FFFFFF" />
              )}
            </TouchableOpacity>
          </View>
          {error && <Text style={styles.errorText}>{error}</Text>}
        </View>

        {/* Tabela de usuários */}
        <View style={styles.usersTableSection}>
          <Text style={styles.sectionTitle}>Todos os Usuários</Text>
          {loadingUsers ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color="#3B82F6" />
              <Text style={styles.loadingText}>Carregando usuários...</Text>
            </View>
          ) : (
            <View style={styles.usersTable}>
              {/* Header da tabela */}
              <View style={styles.tableHeader}>
                <Text style={styles.tableHeaderText}>Nome</Text>
                <Text style={styles.tableHeaderText}>Email</Text>
                <Text style={styles.tableHeaderText}>Plano</Text>
                <Text style={styles.tableHeaderText}>Status</Text>
              </View>
              
              {/* Linhas da tabela - limitado a 10 usuários */}
              {allUsers.slice(0, 10).map((u, index) => (
                <TouchableOpacity
                  key={u.id}
                  style={[styles.tableRow, index % 2 === 0 ? styles.tableRowEven : styles.tableRowOdd]}
                  onPress={() => {
                    setUser(u);
                    setSelectedPlan(null);
                    setDurationDays(7);
                    setModalVisible(true);
                  }}
                >
                  <Text style={styles.tableCell}>{u.name}</Text>
                  <Text style={styles.tableCell}>{u.email}</Text>
                  <View style={styles.tableCell}>
                    <View style={styles.planBadge}>
                      <Text style={[styles.planText, { color: getPlanColor(u.role) }]}>{getPlanLabel(u.role)}</Text>
                    </View>
                  </View>
                  <View style={styles.tableCell}>
                    <View style={[styles.statusBadge, { backgroundColor: u.is_active ? '#10B981' : '#EF4444' }]}>
                      <Text style={styles.statusText}>{u.is_active ? 'Ativo' : 'Inativo'}</Text>
                    </View>
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          )}
        </View>

        {/* Modal personalizado para seleção de plano */}
        <Modal
          visible={modalVisible}
          animationType="slide"
          transparent={true}
          onRequestClose={() => setModalVisible(false)}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>Gerenciar Usuário</Text>
                <TouchableOpacity onPress={() => setModalVisible(false)}>
                  <Ionicons name="close" size={24} color="#FFFFFF" />
                </TouchableOpacity>
              </View>

              <ScrollView style={styles.modalBody}>
                {/* Informações do usuário */}
                {user && (
                  <>
                    <View style={styles.userInfoSection}>
                      <Text style={styles.sectionTitle}>Informações do Usuário</Text>
                      <View style={styles.userInfoCard}>
                        <View style={styles.userInfoRow}>
                          <Ionicons name="person-outline" size={20} color="#64748B" />
                          <Text style={styles.userInfoLabel}>Nome:</Text>
                          <Text style={styles.userInfoValue}>{user.name}</Text>
                        </View>
                        <View style={styles.userInfoRow}>
                          <Ionicons name="mail-outline" size={20} color="#64748B" />
                          <Text style={styles.userInfoLabel}>Email:</Text>
                          <Text style={styles.userInfoValue}>{user.email}</Text>
                        </View>
                        <View style={styles.userInfoRow}>
                          <Ionicons name="shield-outline" size={20} color="#64748B" />
                          <Text style={styles.userInfoLabel}>Plano Atual:</Text>
                          {(() => {
                            const planInfo = getPlanInfo();
                            return (
                              <View style={styles.planBadge}>
                                <Ionicons name={planInfo?.icon as any} size={16} color={planInfo?.color} />
                                <Text style={[styles.planText, { color: planInfo?.color }]}>{planInfo?.label}</Text>
                              </View>
                            );
                          })()}
                        </View>
                        {user.vip_start_date && (
                          <View style={styles.userInfoRow}>
                            <Ionicons name="calendar-outline" size={20} color="#64748B" />
                            <Text style={styles.userInfoLabel}>Início VIP:</Text>
                            <Text style={styles.userInfoValue}>{formatDate(user.vip_start_date)}</Text>
                          </View>
                        )}
                        {user.vip_end_date && (
                          <View style={styles.userInfoRow}>
                            <Ionicons name="calendar-outline" size={20} color="#64748B" />
                            <Text style={styles.userInfoLabel}>Fim VIP:</Text>
                            <Text style={styles.userInfoValue}>{formatDate(user.vip_end_date)}</Text>
                          </View>
                        )}
                      </View>
                    </View>

                    {/* Seleção de plano */}
                    <View style={styles.planSection}>
                      <Text style={styles.sectionTitle}>Selecionar Plano</Text>
                      <View style={styles.planOptions}>
                        <TouchableOpacity
                          style={[styles.planOption, selectedPlan === 'free' && styles.planOptionSelected]}
                          onPress={() => handlePlanSelect('free')}
                        >
                          <Ionicons name="person-outline" size={32} color={selectedPlan === 'free' ? '#94A3B8' : '#94A3B8'} />
                          <Text style={[styles.planOptionTitle, selectedPlan === 'free' && styles.planOptionTitleSelected]}>
                            Free
                          </Text>
                          <Text style={styles.planOptionSubtitle}>Acesso básico</Text>
                        </TouchableOpacity>

                        <TouchableOpacity
                          style={[styles.planOption, selectedPlan === 'vip' && styles.planOptionSelected]}
                          onPress={() => handlePlanSelect('vip')}
                        >
                          <Ionicons name="star-outline" size={32} color={selectedPlan === 'vip' ? '#FBBF24' : '#94A3B8'} />
                          <Text style={[styles.planOptionTitle, selectedPlan === 'vip' && styles.planOptionTitleSelected]}>
                            VIP
                          </Text>
                          <Text style={styles.planOptionSubtitle}>Acesso semanal (7 dias)</Text>
                        </TouchableOpacity>

                        <TouchableOpacity
                          style={[styles.planOption, selectedPlan === 'vip_plus' && styles.planOptionSelected]}
                          onPress={() => handlePlanSelect('vip_plus')}
                        >
                          <Ionicons name="star" size={32} color={selectedPlan === 'vip_plus' ? '#7DD3FC' : '#94A3B8'} />
                          <Text style={[styles.planOptionTitle, selectedPlan === 'vip_plus' && styles.planOptionTitleSelected]}>
                            VIP+
                          </Text>
                          <Text style={styles.planOptionSubtitle}>Acesso mensal (30 dias)</Text>
                        </TouchableOpacity>
                      </View>

                      <TouchableOpacity
                        style={[styles.grantButton, !selectedPlan && styles.grantButtonDisabled]}
                        onPress={handleGrantVIP}
                        disabled={!selectedPlan || updating}
                      >
                        {updating ? (
                          <ActivityIndicator size="small" color="#FFFFFF" />
                        ) : (
                          <Text style={styles.grantButtonText}>Premiar Usuário</Text>
                        )}
                      </TouchableOpacity>
                    </View>
                  </>
                )}
              </ScrollView>
            </View>
          </View>
        </Modal>

        {/* Informações do usuário selecionado (removido - movido para modal) */}
      </ScrollView>

      <CustomAlert
        visible={alertVisible}
        title={alertConfig?.title || ''}
        message={alertConfig?.message || ''}
        type={alertConfig?.type}
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
    justifyContent: 'center',
    paddingVertical: 16,
    paddingHorizontal: 16,
    backgroundColor: colors.header,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    position: 'relative',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 2,
  },
  logoutButton: {
    position: 'absolute',
    left: 12,
    padding: 6,
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    borderRadius: 6,
  },
  headerContent: {
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    color: colors.text,
    textAlign: 'center',
    letterSpacing: 0.3,
    textShadowColor: colors.primarySoft,
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 2,
  },
  headerSubtitle: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
    textAlign: 'center',
    letterSpacing: 0.1,
  },
  content: {
    flex: 1,
    padding: 12,
  },
  searchSection: {
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 12,
    letterSpacing: 0.2,
  },
  searchInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceDeep,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
    elevation: 2,
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    color: colors.text,
    fontSize: 14,
    letterSpacing: 0.1,
  },
  searchButton: {
    backgroundColor: colors.primary,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    marginLeft: 8,
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 2,
  },
  errorText: {
    color: colors.danger,
    fontSize: 12,
    marginTop: 8,
    textAlign: 'center',
    backgroundColor: 'rgba(248, 113, 113, 0.1)',
    padding: 8,
    borderRadius: 6,
  },
  usersTableSection: {
    marginBottom: 16,
  },
  loadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 20,
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 12,
    marginLeft: 8,
  },
  usersTable: {
    backgroundColor: colors.surfaceDeep,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    overflow: 'hidden',
  },
  tableHeader: {
    flexDirection: 'row',
    padding: 10,
    backgroundColor: colors.surfaceDeep,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderStrong,
  },
  tableHeaderText: {
    flex: 1,
    color: colors.text,
    fontSize: 11,
    fontWeight: 'bold',
    textAlign: 'center',
    letterSpacing: 0.2,
    textTransform: 'uppercase',
  },
  tableRow: {
    flexDirection: 'row',
    padding: 10,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.05)',
  },
  tableRowEven: {
    backgroundColor: colors.surfaceAlt,
  },
  tableRowOdd: {
    backgroundColor: colors.surface,
  },
  tableCell: {
    flex: 1,
    color: colors.text,
    fontSize: 11,
    textAlign: 'center',
    letterSpacing: 0.1,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 2,
    elevation: 1,
  },
  statusText: {
    color: '#FFFFFF',
    fontSize: 9,
    fontWeight: 'bold',
    letterSpacing: 0.2,
  },
  userInfoSection: {
    marginBottom: 16,
  },
  userInfoCard: {
    backgroundColor: colors.surfaceDeep,
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
    elevation: 2,
  },
  userInfoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  userInfoLabel: {
    color: colors.textMuted,
    fontSize: 12,
    marginLeft: 8,
    marginRight: 6,
    letterSpacing: 0.1,
  },
  userInfoValue: {
    color: colors.text,
    fontSize: 12,
    flex: 1,
    letterSpacing: 0.1,
  },
  planBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceDeep,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  planText: {
    fontSize: 10,
    fontWeight: 'bold',
    marginLeft: 4,
    letterSpacing: 0.2,
  },
  planSection: {
    marginBottom: 16,
  },
  planOptions: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 12,
  },
  planOption: {
    flex: 1,
    backgroundColor: colors.surfaceDeep,
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.borderStrong,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 1,
  },
  planOptionSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
    borderWidth: 1,
  },
  planOptionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text,
    marginTop: 8,
    letterSpacing: 0.2,
  },
  planOptionTitleSelected: {
    color: colors.primary,
  },
  planOptionSubtitle: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 4,
    letterSpacing: 0.1,
  },
  durationSection: {
    marginBottom: 12,
  },
  durationOptions: {
    flexDirection: 'row',
    gap: 8,
  },
  durationOption: {
    backgroundColor: colors.surfaceDeep,
    borderRadius: 6,
    padding: 10,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  durationOptionSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
    borderWidth: 1,
  },
  durationText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.1,
  },
  durationTextSelected: {
    color: '#FFFFFF',
  },
  grantButton: {
    backgroundColor: colors.success,
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
    shadowColor: colors.success,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 3,
  },
  grantButtonDisabled: {
    backgroundColor: colors.surfaceAlt,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0,
    shadowRadius: 0,
    elevation: 0,
  },
  grantButtonText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: 'bold',
    letterSpacing: 0.3,
  },
  bottomNav: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingBottom: 8,
    paddingTop: 6,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 6,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 16,
    width: '90%',
    maxHeight: '90%',
    borderWidth: 1,
    borderColor: colors.borderStrong,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 5,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderStrong,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text,
  },
  modalBody: {
    padding: 16,
  },
});
