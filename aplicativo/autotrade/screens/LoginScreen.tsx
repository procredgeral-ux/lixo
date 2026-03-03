import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
  Animated,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth, getRememberedCredentials } from '../contexts/AuthContext';
import { useConnection } from '../contexts/ConnectionContext';
import { API_CONFIG } from '../constants/api';
import { Ionicons } from '@expo/vector-icons';
import ConfirmModal from '../components/ConfirmModal';
import AnimatedTextCarousel from '../components/AnimatedTextCarousel';
import { carouselMaxWidth, contentMaxWidth } from '../responsive';

const carouselPhrases = [
  'Automação de day trade inteligente',
  'Estratégias personalizadas para você',
  'Sinais em tempo real 24/7',
  'Maximizando seus lucros',
  'Algoritmos avançados de trading',
  'Negocie enquanto você descansa',
  'Análise técnica automática',
];

export default function LoginScreen({ route }: any) {
  const navigation = useNavigation();
  const { connectionStatus, isOnline } = useConnection();
  const { login, user, fetchUser, maintenanceLogout, setMaintenanceLogout } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [modalVisible, setModalVisible] = useState(false);
  const [modalConfig, setModalConfig] = useState({
    title: '',
    message: '',
    type: 'info' as 'info' | 'danger' | 'warning',
    icon: '',
    onConfirm: () => {},
    showOnlyConfirm: false,
  });

  // Receber parâmetros de navegação (email e senha) quando vier do cadastro
  useEffect(() => {
    if (route?.params?.email) {
      setEmail(route.params.email);
    }
    if (route?.params?.password) {
      setPassword(route.params.password);
    }
  }, [route?.params]);

  // Navegar para ConnectionLostScreen quando a conexão for perdida
  useEffect(() => {
    if (connectionStatus === 'disconnected') {
      navigation.navigate('ConnectionLost' as never);
    }
  }, [connectionStatus, navigation]);

  useEffect(() => {
    if (maintenanceLogout) {
      navigation.reset({ index: 0, routes: [{ name: 'Login' as never }] });
      setMaintenanceLogout(false);
    }
  }, [maintenanceLogout, navigation, setMaintenanceLogout]);

  // Animation refs
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    loadRememberedCredentials();
    // Start entrance animations
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 600,
      useNativeDriver: true,
    }).start();
  }, []);

  // Redirecionar para Admin se usuário for superusuário
  useEffect(() => {
    console.log('[LoginScreen] useEffect - user:', user);
    // Só redirecionar se usuário estiver completamente carregado
    if (user && user.is_superuser) {
      console.log('[LoginScreen] Redirecionando para Admin - usuário é superusuário');
      navigation.reset({
        index: 0,
        routes: [{ name: 'Admin' as never }],
      });
    }
  }, [user?.is_superuser, navigation]);

  const loadRememberedCredentials = async () => {
    const credentials = await getRememberedCredentials();
    if (credentials) {
      setEmail(credentials.email);
      setPassword(credentials.password);
      setRememberMe(true);
    }
  };

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  const validatePassword = (password: string): boolean => {
    return password.length >= 8;
  };

  const showModal = (title: string, message: string, type: 'info' | 'danger' | 'warning' = 'info', icon?: string, onConfirm?: () => void, showOnlyConfirm = false) => {
    setModalConfig({
      title,
      message,
      type,
      icon: icon || '',
      onConfirm: onConfirm || (() => setModalVisible(false)),
      showOnlyConfirm,
    });
    setModalVisible(true);
  };

  const handleLogin = async () => {
    console.log('[LoginScreen] handleLogin chamado');

    // Verificar status de conexão antes de permitir login
    if (connectionStatus === 'maintenance') {
      console.log('[LoginScreen] Manutenção detectada, navegando para tela de manutenção');
      navigation.navigate('Maintenance' as never);
      return;
    }

    if (connectionStatus === 'disconnected') {
      showModal(
        'Sem conexão',
        'Não é possível conectar ao servidor. Verifique sua internet e tente novamente.',
        'warning',
        'wifi-outline',
        undefined,
        true
      );
      return;
    }

    console.log('[LoginScreen] Conexão OK, continuando com login...');

    const newErrors: { email?: string; password?: string } = {};

    if (!email.trim()) {
      newErrors.email = 'Email é obrigatório';
    } else if (!validateEmail(email)) {
      newErrors.email = 'Email inválido';
    }

    if (!password) {
      newErrors.password = 'Senha é obrigatória';
    } else if (!validatePassword(password)) {
      newErrors.password = 'A senha deve ter pelo menos 8 caracteres';
    }

    setErrors(newErrors);

    if (Object.keys(newErrors).length > 0) {
      const errorMessages = Object.values(newErrors).filter(msg => msg !== '');
      if (errorMessages.length > 0) {
        showModal(
          'Validação',
          errorMessages.join('\n'),
          'warning',
          'alert-circle-outline',
          undefined,
          true
        );
      }
      return;
    }

    setIsLoading(true);

    try {
      // Verificar simulação de manutenção primeiro
      if (API_CONFIG.SIMULATE_MAINTENANCE) {
        navigation.reset({
          index: 0,
          routes: [{ name: 'Maintenance' as never }],
        });
        setIsLoading(false);
        return;
      }

      await login(email, password, rememberMe);
      
      // Aguardar próximo ciclo de renderização para garantir que user foi atualizado
      await new Promise(resolve => setTimeout(resolve, 0));
      
      // Buscar dados atualizados do usuário
      await fetchUser();
      
      // Aguardar novamente para garantir atualização
      await new Promise(resolve => setTimeout(resolve, 0));
      
      // Verificar se usuário é superusuário e redirecionar para Admin
      if (user?.is_superuser) {
        navigation.reset({
          index: 0,
          routes: [{ name: 'Admin' as never }],
        });
      } else {
        navigation.reset({
          index: 0,
          routes: [{ name: 'Dashboard' as never }],
        });
      }
    } catch (error: any) {
      showModal(
        'Erro',
        error.message || 'Falha ao fazer login',
        'danger',
        'warning-outline',
        undefined,
        true
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <View style={styles.content}>
            <View style={styles.headerBackground}>
              {/* Logo/Icon */}
              <Animated.View
                style={[
                  styles.logoContainer,
                  {
                    opacity: fadeAnim,
                  },
                ]}
              >
                <View style={styles.logoIcon}>
                  <Image
                    source={require('../logo.png')}
                    style={styles.logoImage}
                    resizeMode="contain"
                  />
                </View>
              </Animated.View>
              <View style={styles.carouselWrapper}>
                <AnimatedTextCarousel phrases={carouselPhrases} />
              </View>
            </View>
            <View style={styles.titleSection}>
              <Animated.Text style={[styles.title, { opacity: fadeAnim }]}>
                Bem-vindo
              </Animated.Text>
              <Animated.Text style={[styles.subtitle, { opacity: fadeAnim }]}>
                Faça login para continuar
              </Animated.Text>
            </View>

            <Animated.View style={[styles.form, { opacity: fadeAnim }]}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Email</Text>
                <View style={[styles.inputContainer, errors.email && styles.inputContainerError]}>
                  <Ionicons name="mail-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    placeholder="seu@email.com"
                    placeholderTextColor="#64748B"
                    value={email}
                    onChangeText={setEmail}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                </View>
                {errors.email && <Text style={styles.errorText}>{errors.email}</Text>}
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Senha</Text>
                <View style={[styles.inputContainer, errors.password && styles.inputContainerError]}>
                  <Ionicons name="lock-closed-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    placeholder="Sua senha"
                    placeholderTextColor="#64748B"
                    value={password}
                    onChangeText={setPassword}
                    secureTextEntry={!showPassword}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  <TouchableOpacity
                    style={styles.eyeIcon}
                    onPress={() => setShowPassword(!showPassword)}
                  >
                    <Ionicons 
                      name={showPassword ? 'eye-outline' : 'eye-off-outline'} 
                      size={20} 
                      color="#64748B" 
                    />
                  </TouchableOpacity>
                </View>
                {errors.password && <Text style={styles.errorText}>{errors.password}</Text>}
              </View>

              <View style={styles.rememberContainer}>
                <TouchableOpacity
                  style={styles.checkboxContainer}
                  onPress={() => setRememberMe(!rememberMe)}
                  activeOpacity={0.7}
                >
                  <View style={[styles.checkbox, rememberMe && styles.checkboxChecked]}>
                    {rememberMe && <Ionicons name="checkmark" size={14} color="#FFFFFF" />}
                  </View>
                  <Text style={styles.rememberText}>Lembrar meus dados</Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={[styles.button, isLoading && styles.buttonDisabled]}
                onPress={handleLogin}
                disabled={isLoading}
                activeOpacity={0.8}
              >
                {isLoading ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.buttonText}>Entrar</Text>
                )}
              </TouchableOpacity>

              <View style={styles.registerContainer}>
                <Text style={styles.registerText}>Não tem uma conta? </Text>
                <TouchableOpacity
                  onPress={() => {
                    if (connectionStatus === 'maintenance') {
                      navigation.navigate('Maintenance' as never);
                    } else if (connectionStatus === 'disconnected') {
                      showModal(
                        'Sem conexão',
                        'Não é possível conectar ao servidor. Verifique sua internet e tente novamente.',
                        'warning',
                        'wifi-outline',
                        undefined,
                        true
                      );
                    } else {
                      navigation.navigate('Register' as never);
                    }
                  }}
                  activeOpacity={0.7}
                >
                  <Text style={styles.registerLink}>Cadastre-se</Text>
                </TouchableOpacity>
              </View>
            </Animated.View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      <ConfirmModal
        visible={modalVisible}
        title={modalConfig.title}
        message={modalConfig.message}
        type={modalConfig.type}
        icon={modalConfig.icon || undefined}
        confirmText="OK"
        cancelText=""
        onConfirm={modalConfig.onConfirm}
        onCancel={() => setModalVisible(false)}
        showOnlyConfirm={modalConfig.showOnlyConfirm}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0B0D12',
  },
  keyboardView: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 0,
    paddingBottom: 28,
  },
  headerBackground: {
    marginHorizontal: -24,
    paddingHorizontal: 24,
    paddingTop: 40,
    paddingBottom: 20,
    backgroundColor: '#151A24',
    borderBottomLeftRadius: 24,
    borderBottomRightRadius: 24,
    alignItems: 'center',
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 8,
  },
  logoIcon: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: 'rgba(125, 211, 252, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'rgba(125, 211, 252, 0.3)',
    overflow: 'hidden',
  },
  logoImage: {
    width: '100%',
    height: '100%',
  },
  carouselWrapper: {
    width: '100%',
    maxWidth: carouselMaxWidth,
    minHeight: 36,
    marginTop: 6,
    justifyContent: 'center',
    alignItems: 'center',
  },
  titleSection: {
    alignItems: 'center',
    marginTop: 18,
    marginBottom: 12,
    paddingHorizontal: 12,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#F8FAFC',
    marginBottom: 4,
    textAlign: 'center',
    letterSpacing: 0.2,
  },
  subtitle: {
    fontSize: 14,
    color: '#9AA7BC',
    textAlign: 'center',
    lineHeight: 20,
    maxWidth: 280,
  },
  form: {
    width: '100%',
    maxWidth: contentMaxWidth,
    alignSelf: 'center',
    marginTop: 8,
    backgroundColor: '#151921',
    borderRadius: 16,
    padding: 18,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  inputGroup: {
    marginBottom: 14,
  },
  label: {
    fontSize: 12,
    fontWeight: '600',
    color: '#C7D2E4',
    marginBottom: 6,
    letterSpacing: 0.3,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F141C',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.08)',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  inputContainerError: {
    borderColor: '#F87171',
  },
  inputIcon: {
    marginRight: 12,
  },
  input: {
    flex: 1,
    fontSize: 16,
    color: '#F8FAFC',
    paddingVertical: 12,
  },
  eyeIcon: {
    padding: 8,
  },
  errorText: {
    color: '#F87171',
    fontSize: 12,
    marginTop: 4,
  },
  rememberContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 14,
  },
  checkboxContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: '#7DD3FC',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  checkboxChecked: {
    backgroundColor: '#7DD3FC',
    borderColor: '#7DD3FC',
  },
  rememberText: {
    fontSize: 14,
    color: '#94A3B8',
  },
  button: {
    backgroundColor: '#7DD3FC',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 16,
    shadowColor: '#7DD3FC',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  buttonDisabled: {
    opacity: 0.6,
    shadowOpacity: 0,
    elevation: 0,
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  registerContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  registerText: {
    fontSize: 14,
    color: '#94A3B8',
  },
  registerLink: {
    color: '#7DD3FC',
    fontSize: 14,
    fontWeight: '600',
  },
});
