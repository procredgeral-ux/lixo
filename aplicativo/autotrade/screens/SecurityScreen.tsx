import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/api';
import ConfirmModal from '../components/ConfirmModal';
import { colors } from '../theme';
import { contentMaxWidth } from '../responsive';

import { useMaintenanceCheck } from '../hooks/useMaintenanceCheck';

export default function SecurityScreen() {
  useMaintenanceCheck();
  const navigation = useNavigation();
  const [loading, setLoading] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [modalConfig, setModalConfig] = useState({
    title: '',
    message: '',
    type: 'info' as 'info' | 'danger' | 'warning',
    icon: '',
    onConfirm: () => {},
  });

  const showModal = (title: string, message: string, type: 'info' | 'danger' | 'warning' = 'info', icon?: string, onConfirm?: () => void) => {
    setModalConfig({
      title,
      message,
      type,
      icon: icon || '',
      onConfirm: onConfirm || (() => setModalVisible(false)),
    });
    setModalVisible(true);
  };

  const [formData, setFormData] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  const [errors, setErrors] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  const validateForm = () => {
    const newErrors = {
      current_password: '',
      new_password: '',
      confirm_password: '',
    };

    if (!formData.current_password) {
      newErrors.current_password = 'Senha atual é obrigatória';
    }

    if (!formData.new_password) {
      newErrors.new_password = 'Nova senha é obrigatória';
    } else if (formData.new_password.length < 6) {
      newErrors.new_password = 'A senha deve ter pelo menos 6 caracteres';
    }

    if (!formData.confirm_password) {
      newErrors.confirm_password = 'Confirme a nova senha';
    } else if (formData.new_password !== formData.confirm_password) {
      newErrors.confirm_password = 'As senhas não coincidem';
    }

    setErrors(newErrors);
    return !newErrors.current_password && !newErrors.new_password && !newErrors.confirm_password;
  };

  const handleChange = (field: 'current_password' | 'new_password' | 'confirm_password', value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  const handleSave = async () => {
    if (!validateForm()) {
      const errorMessages = Object.values(errors).filter(msg => msg !== '');
      if (errorMessages.length > 0) {
        showModal(
          '⚠️ Validação',
          errorMessages.join('\n'),
          'warning',
          'alert-circle-outline'
        );
      }
      return;
    }

    setLoading(true);
    try {
      await apiClient.post('/users/me/change-password', {
        current_password: formData.current_password,
        new_password: formData.new_password,
      });

      showModal(
        '✅ Sucesso',
        'Senha alterada com sucesso!',
        'info',
        'checkmark-circle-outline',
        () => {
          setFormData({
            current_password: '',
            new_password: '',
            confirm_password: '',
          });
          navigation.goBack();
        }
      );
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Erro ao alterar senha';
      showModal(
        '❌ Erro',
        errorMessage,
        'danger',
        'warning-outline'
      );
    } finally {
      setLoading(false);
    }
  };

  const getPasswordStrength = (password: string): { strength: string; color: string } => {
    if (!password) return { strength: '', color: '#64748B' };
    
    let strength = 0;
    if (password.length >= 6) strength++;
    if (password.length >= 10) strength++;
    if (/[A-Z]/.test(password)) strength++;
    if (/[0-9]/.test(password)) strength++;
    if (/[^A-Za-z0-9]/.test(password)) strength++;

    if (strength <= 1) return { strength: 'Fraca', color: '#F87171' };
    if (strength <= 2) return { strength: 'Média', color: '#F59E0B' };
    if (strength <= 3) return { strength: 'Boa', color: '#34C759' };
    return { strength: 'Forte', color: '#10B981' };
  };

  const passwordStrength = getPasswordStrength(formData.new_password);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.content} contentContainerStyle={styles.scrollContainer}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Ionicons name="arrow-back" size={24} color="#F8FAFC" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Segurança</Text>
          <View style={{ width: 24 }} />
        </View>

        {/* Info Section */}
        <View style={styles.infoSection}>
          <Ionicons name="shield-checkmark-outline" size={32} color="#7DD3FC" />
          <View style={styles.infoContent}>
            <Text style={styles.infoTitle}>Alterar Senha</Text>
            <Text style={styles.infoDescription}>
              Digite sua senha atual e crie uma nova senha segura para proteger sua conta.
            </Text>
          </View>
        </View>

        {/* Form */}
        <View style={styles.form}>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Senha Atual</Text>
            <View style={[styles.inputContainer, errors.current_password && styles.inputContainerError]}>
              <TextInput
                style={styles.input}
                value={formData.current_password}
                onChangeText={(value) => handleChange('current_password', value)}
                placeholder="Digite sua senha atual"
                placeholderTextColor="#64748B"
                secureTextEntry={!showCurrentPassword}
              />
              <TouchableOpacity onPress={() => setShowCurrentPassword(!showCurrentPassword)}>
                <Ionicons 
                  name={showCurrentPassword ? 'eye-outline' : 'eye-off-outline'} 
                  size={20} 
                  color="#64748B" 
                />
              </TouchableOpacity>
            </View>
            {errors.current_password && <Text style={styles.errorText}>{errors.current_password}</Text>}
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Nova Senha</Text>
            <View style={[styles.inputContainer, errors.new_password && styles.inputContainerError]}>
              <TextInput
                style={styles.input}
                value={formData.new_password}
                onChangeText={(value) => handleChange('new_password', value)}
                placeholder="Digite a nova senha"
                placeholderTextColor="#64748B"
                secureTextEntry={!showNewPassword}
              />
              <TouchableOpacity onPress={() => setShowNewPassword(!showNewPassword)}>
                <Ionicons 
                  name={showNewPassword ? 'eye-outline' : 'eye-off-outline'} 
                  size={20} 
                  color="#64748B" 
                />
              </TouchableOpacity>
            </View>
            {errors.new_password && <Text style={styles.errorText}>{errors.new_password}</Text>}
            
            {formData.new_password && (
              <View style={styles.passwordStrengthContainer}>
                <View style={styles.passwordStrengthBar}>
                  <View 
                    style={[
                      styles.passwordStrengthFill, 
                      { backgroundColor: passwordStrength.color }
                    ]} 
                  />
                </View>
                <Text style={[styles.passwordStrengthText, { color: passwordStrength.color }]}>
                  Força: {passwordStrength.strength}
                </Text>
              </View>
            )}
          </View>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Confirmar Nova Senha</Text>
            <View style={[styles.inputContainer, errors.confirm_password && styles.inputContainerError]}>
              <TextInput
                style={styles.input}
                value={formData.confirm_password}
                onChangeText={(value) => handleChange('confirm_password', value)}
                placeholder="Confirme a nova senha"
                placeholderTextColor="#64748B"
                secureTextEntry={!showConfirmPassword}
              />
              <TouchableOpacity onPress={() => setShowConfirmPassword(!showConfirmPassword)}>
                <Ionicons 
                  name={showConfirmPassword ? 'eye-outline' : 'eye-off-outline'} 
                  size={20} 
                  color="#64748B" 
                />
              </TouchableOpacity>
            </View>
            {errors.confirm_password && <Text style={styles.errorText}>{errors.confirm_password}</Text>}
          </View>

          {/* Password Requirements */}
          <View style={styles.requirementsSection}>
            <Text style={styles.requirementsTitle}>Requisitos da Senha:</Text>
            <View style={styles.requirementItem}>
              <Ionicons 
                name={formData.new_password.length >= 6 ? 'checkmark-circle' : 'ellipse-outline'} 
                size={16} 
                color={formData.new_password.length >= 6 ? '#34C759' : '#64748B'} 
              />
              <Text style={styles.requirementText}>Mínimo de 6 caracteres</Text>
            </View>
            <View style={styles.requirementItem}>
              <Ionicons 
                name={/[A-Z]/.test(formData.new_password) ? 'checkmark-circle' : 'ellipse-outline'} 
                size={16} 
                color={/[A-Z]/.test(formData.new_password) ? '#34C759' : '#64748B'} 
              />
              <Text style={styles.requirementText}>Pelo menos uma letra maiúscula</Text>
            </View>
            <View style={styles.requirementItem}>
              <Ionicons 
                name={/[0-9]/.test(formData.new_password) ? 'checkmark-circle' : 'ellipse-outline'} 
                size={16} 
                color={/[0-9]/.test(formData.new_password) ? '#34C759' : '#64748B'} 
              />
              <Text style={styles.requirementText}>Pelo menos um número</Text>
            </View>
            <View style={styles.requirementItem}>
              <Ionicons 
                name={/[^A-Za-z0-9]/.test(formData.new_password) ? 'checkmark-circle' : 'ellipse-outline'} 
                size={16} 
                color={/[^A-Za-z0-9]/.test(formData.new_password) ? '#34C759' : '#64748B'} 
              />
              <Text style={styles.requirementText}>Pelo menos um caractere especial</Text>
            </View>
          </View>

          {/* Save Button */}
          <TouchableOpacity
            style={[styles.saveButton, loading && styles.saveButtonDisabled]}
            onPress={handleSave}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator size="small" color="#FFFFFF" />
            ) : (
              <Text style={styles.saveButtonText}>Alterar Senha</Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>

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
      />
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
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  headerTitle: {
    color: colors.text,
    fontSize: 20,
    fontWeight: '600',
  },
  infoSection: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 16,
    padding: 20,
    marginBottom: 24,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  infoContent: {
    flex: 1,
  },
  infoTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 4,
  },
  infoDescription: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  form: {
    gap: 20,
  },
  formGroup: {
    gap: 8,
  },
  label: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '500',
  },
  inputContainer: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    flexDirection: 'row',
    alignItems: 'center',
  },
  inputContainerError: {
    borderColor: colors.danger,
  },
  input: {
    flex: 1,
    color: colors.text,
    fontSize: 16,
    paddingVertical: 14,
  },
  errorText: {
    color: colors.danger,
    fontSize: 12,
    marginTop: 4,
  },
  passwordStrengthContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 4,
  },
  passwordStrengthBar: {
    height: 4,
    backgroundColor: colors.surfaceAlt,
    borderRadius: 2,
    overflow: 'hidden',
  },
  passwordStrengthFill: {
    height: '100%',
    borderRadius: 2,
    width: '0%',
  },
  passwordStrengthText: {
    fontSize: 12,
    fontWeight: '500',
  },
  requirementsSection: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 16,
    padding: 20,
    marginBottom: 24,
  },
  requirementsTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 12,
  },
  requirementItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  requirementText: {
    color: colors.textMuted,
    fontSize: 12,
  },
  saveButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: colors.primaryText,
    fontSize: 16,
    fontWeight: '600',
  },
});
