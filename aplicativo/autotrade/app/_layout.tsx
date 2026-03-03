import { Stack } from 'expo-router';
import { AuthProvider, useAuth } from '../contexts/AuthContext';

function AuthLayout() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return null; // Ou mostrar um loading screen
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="register" />
    </Stack>
  );
}

export default function Layout() {
  return (
    <AuthProvider>
      <AuthLayout />
    </AuthProvider>
  );
}
