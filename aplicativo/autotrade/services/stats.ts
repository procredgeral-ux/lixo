import { apiClient } from './api';

export interface UserStats {
  balance_demo: number;
  balance_real: number;
  win_rate_demo: number;
  win_rate_real: number;
  loss_rate_demo: number;
  loss_rate_real: number;
  total_trades_demo: number;
  total_trades_real: number;
  // Campos adicionais para dashboard
  lucro_hoje: number;
  lucro_semana: number;
  melhor_estrategia: string;
  taxa_sucesso: number;
  trades_hoje: number;
  maior_ganho: number;
  maior_perda: number;
  tempo_ativo: string;
}

export const statsService = {
  async getUserStats(): Promise<UserStats> {
    return apiClient.get<UserStats>('/users/me/stats');
  },
};
