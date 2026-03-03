import { apiClient } from './api';

export interface Account {
  id: string;
  user_id: string;
  ssid_demo?: string | null;
  ssid_real?: string | null;
  name: string | null;
  autotrade_demo: boolean;
  autotrade_real: boolean;
  uid: number | null;
  platform: number;
  balance_demo: number;
  balance_real: number;
  currency: string;
  is_active: boolean;
  last_connected: string | null;
  created_at: string;
  updated_at: string;
}

export interface AccountUpdate {
  name?: string;
  autotrade_demo?: boolean;
  autotrade_real?: boolean;
  ssid_demo?: string;
  ssid_real?: string;
}

export const accountService = {
  async getAccounts(): Promise<Account[]> {
    return apiClient.get<Account[]>('/accounts');
  },

  async updateAccount(accountId: string, data: AccountUpdate): Promise<Account> {
    return apiClient.put<Account>(`/accounts/${accountId}`, data);
  },
};
