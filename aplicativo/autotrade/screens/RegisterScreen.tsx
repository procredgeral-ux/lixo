import React, { useState, useRef, useEffect } from 'react';
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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../services/api';
import { API_CONFIG } from '../constants/api';
import { Ionicons } from '@expo/vector-icons';
import ConfirmModal from '../components/ConfirmModal';
import AnimatedTextCarousel from '../components/AnimatedTextCarousel';
import { carouselMaxWidth, contentMaxWidth } from '../responsive';

const carouselPhrases = [
  'Comece sua jornada de day trade',
  'Estratégias personalizadas para você',
  'Automação inteligente 24/7',
  'Negocie com precisão',
  'Algoritmos avançados de trading',
  'Maximize seus lucros',
  'Análise técnica automática',
];

export default function RegisterScreen() {
  const navigation = useNavigation();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<{
    name?: string;
    email?: string;
    password?: string;
    confirmPassword?: string;
  }>({});
  const [modalVisible, setModalVisible] = useState(false);
  const [modalConfig, setModalConfig] = useState({
    title: '',
    message: '',
    type: 'info' as 'info' | 'danger' | 'warning',
    icon: '',
    onConfirm: () => {},
    showOnlyConfirm: false,
  });

  const { register, maintenanceLogout, setMaintenanceLogout } = useAuth();

  useEffect(() => {
    if (maintenanceLogout) {
      navigation.reset({ index: 0, routes: [{ name: 'Login' as never }] });
      setMaintenanceLogout(false);
    }
  }, [maintenanceLogout]);

  // Animation refs
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    // Start entrance animations
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 600,
      useNativeDriver: true,
    }).start();
  }, []);

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

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  const validatePassword = (password: string): boolean => {
    return password.length >= 8;
  };

  const handleRegister = async () => {
    const newErrors: {
      name?: string;
      email?: string;
      password?: string;
      confirmPassword?: string;
    } = {};

    if (!name.trim()) {
      newErrors.name = 'Nome é obrigatório';
    } else if (name.trim().length < 2) {
      newErrors.name = 'Nome deve ter pelo menos 2 caracteres';
    }

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

    if (!confirmPassword) {
      newErrors.confirmPassword = 'Confirme sua senha';
    } else if (password !== confirmPassword) {
      newErrors.confirmPassword = 'As senhas não coincidem';
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
      // Verificar se a corretora está em manutenção antes de permitir cadastro
      try {
        const maintenanceData = await apiClient.get<any>('/maintenance/status');

        if (maintenanceData && maintenanceData.is_under_maintenance) {
          navigation.navigate('Maintenance' as never);
          setIsLoading(false);
          return;
        }
      } catch (error) {
        console.error('[RegisterScreen] Erro ao verificar manutenção, continuando com cadastro:', error);
        // Não assumir manutenção apenas por erro de rede - continuar com cadastro
      }

      await register(name.trim(), email.trim(), password);
      showModal(
        'Sucesso',
        'Cadastro realizado com sucesso! Você será redirecionado para o login.',
        'info',
        'checkmark-circle-outline',
        () => {
          setModalVisible(false);
          // Navegar para Login com email e senha preenchidos
          (navigation.navigate as any)('Login', {
            email: email.trim(),
            password: password
          });
        },
        true
      );
    } catch (error: any) {
      showModal(
        'Erro',
        error.message || 'Falha ao cadastrar usuário',
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
                  <Ionicons name="person-add-outline" size={40} color="#7DD3FC" />
                </View>
              </Animated.View>
              <View style={styles.carouselWrapper}>
                <AnimatedTextCarousel phrases={carouselPhrases} />
              </View>
            </View>

            <View style={styles.titleSection}>
              <Animated.Text style={[styles.title, { opacity: fadeAnim }]}>
                Criar conta
              </Animated.Text>
              <Animated.Text style={[styles.subtitle, { opacity: fadeAnim }]}>
                Preencha os dados para se cadastrar
              </Animated.Text>
            </View>

            <Animated.View style={[styles.form, { opacity: fadeAnim }]}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Nome completo</Text>
                <View style={[styles.inputContainer, errors.name && styles.inputContainerError]}>
                  <Ionicons name="person-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    placeholder="Seu nome"
                    placeholderTextColor="#64748B"
                    value={name}
                    onChangeText={setName}
                    autoCapitalize="words"
                    autoCorrect={false}
                  />
                </View>
                {errors.name && <Text style={styles.errorText}>{errors.name}</Text>}
              </View>

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
                    placeholder="Mínimo 8 caracteres"
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
                    <Ionicons name={showPassword ? 'eye-outline' : 'eye-off-outline'} size={20} color="#64748B" />
                  </TouchableOpacity>
                </View>
                {errors.password && <Text style={styles.errorText}>{errors.password}</Text>}
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Confirmar senha</Text>
                <View style={[styles.inputContainer, errors.confirmPassword && styles.inputContainerError]}>
                  <Ionicons name="lock-closed-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    placeholder="Confirme sua senha"
                    placeholderTextColor="#64748B"
                    value={confirmPassword}
                    onChangeText={setConfirmPassword}
                    secureTextEntry={!showConfirmPassword}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  <TouchableOpacity
                    style={styles.eyeIcon}
                    onPress={() => setShowConfirmPassword(!showConfirmPassword)}
                  >
                    <Ionicons name={showConfirmPassword ? 'eye-outline' : 'eye-off-outline'} size={20} color="#64748B" />
                  </TouchableOpacity>
                </View>
                {errors.confirmPassword && <Text style={styles.errorText}>{errors.confirmPassword}</Text>}
              </View>

              <TouchableOpacity
                style={[styles.button, isLoading && styles.buttonDisabled]}
                onPress={handleRegister}
                disabled={isLoading}
                activeOpacity={0.8}
              >
                {isLoading ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.buttonText}>Cadastrar</Text>
                )}
              </TouchableOpacity>

              <View style={styles.loginContainer}>
                <Text style={styles.loginText}>Já tem uma conta? </Text>
                <TouchableOpacity onPress={() => navigation.navigate('Login' as never)} activeOpacity={0.7}>
                  <Text style={styles.loginLink}>Faça login</Text>
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
  loginContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loginText: {
    fontSize: 14,
    color: '#94A3B8',
  },
  loginLink: {
    color: '#7DD3FC',
    fontSize: 14,
    fontWeight: '600',
  },
});
