import React, { useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { AuthProvider } from './contexts/AuthContext';
import { ConnectionProvider } from './contexts/ConnectionContext';
import SplashScreen from './components/SplashScreen';
import LoginScreen from './screens/LoginScreen';
import RegisterScreen from './screens/RegisterScreen';
import DashboardScreen from './screens/DashboardScreen';
import EstrategiasScreen from './screens/EstrategiasScreen';
import SinaisScreen from './screens/SinaisScreen';
import HistoricoScreen from './screens/HistoricoScreen';
import ConfiguracoesScreen from './screens/ConfiguracoesScreen';
import ProfileScreen from './screens/ProfileScreen';
import SecurityScreen from './screens/SecurityScreen';
import SsidRegistrationScreen from './screens/SsidRegistrationScreen';
import ExtractSsidScreen from './screens/ExtractSsidScreen';
import ExtractSsidDemoScreen from './screens/ExtractSsidDemoScreen';
import CreateStrategyScreen from './screens/CreateStrategyScreen';
import AutoTradeConfigScreen from './screens/AutoTradeConfigScreen';
import EditStrategyScreen from './screens/EditStrategyScreen';
import PerformanceScreen from './screens/PerformanceScreen';
import StrategyPerformanceScreen from './screens/StrategyPerformanceScreen';
import MaintenanceScreen from './screens/MaintenanceScreen';
import ConnectionLostScreen from './screens/ConnectionLostScreen';
import AdminScreen from './screens/AdminScreen';

const Stack = createNativeStackNavigator();

const MyTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: '#1A1A1A',
    card: '#2A2A2A',
    text: '#FFFFFF',
    border: '#3A3A3A',
    primary: '#007AFF',
  },
};

interface MaintenanceStatus {
  is_under_maintenance: boolean;
  last_checked_at: string | null;
}

export default function App() {
  const [isSplashVisible, setIsSplashVisible] = useState(true);

  const handleSplashFinish = () => {
    setIsSplashVisible(false);
  };

  if (isSplashVisible) {
    return <SplashScreen onFinish={handleSplashFinish} />;
  }

  return (
    <ConnectionProvider>
      <AuthProvider>
        <NavigationContainer theme={MyTheme}>
          <Stack.Navigator
            screenOptions={{
              headerShown: false,
              animation: 'none',
            }}
          >
            <Stack.Screen name="Login" component={LoginScreen} />
            <Stack.Screen name="Register" component={RegisterScreen} />
            <Stack.Screen name="ConnectionLost" component={ConnectionLostScreen} />
            <Stack.Screen name="Maintenance" component={MaintenanceScreen} />
            <Stack.Screen name="Dashboard" component={DashboardScreen} />
            <Stack.Screen name="Estrategias" component={EstrategiasScreen} />
            <Stack.Screen name="Sinais" component={SinaisScreen} />
            <Stack.Screen name="Historico" component={HistoricoScreen} />
            <Stack.Screen name="Configuracoes" component={ConfiguracoesScreen} />
            <Stack.Screen name="Profile" component={ProfileScreen} />
            <Stack.Screen name="Security" component={SecurityScreen} />
            <Stack.Screen name="SsidRegistration" component={SsidRegistrationScreen} />
            <Stack.Screen name="ExtractSsid" component={ExtractSsidScreen} />
            <Stack.Screen name="ExtractSsidDemo" component={ExtractSsidDemoScreen} />
            <Stack.Screen name="ExtractSsidReal" component={ExtractSsidScreen} />
            <Stack.Screen name="CreateStrategy" component={CreateStrategyScreen} />
            <Stack.Screen name="EditStrategy" component={EditStrategyScreen} />
            <Stack.Screen name="AutoTradeConfig" component={AutoTradeConfigScreen} />
            <Stack.Screen name="Performance" component={PerformanceScreen} />
            <Stack.Screen name="StrategyPerformance" component={StrategyPerformanceScreen} />
            <Stack.Screen name="Admin" component={AdminScreen} />
          </Stack.Navigator>
          <StatusBar style="auto" />
        </NavigationContainer>
      </AuthProvider>
    </ConnectionProvider>
  );
}
