import React, { useRef, useEffect } from 'react';
import { Text, StyleSheet, Animated } from 'react-native';

interface AnimatedGradientTextProps {
  children: React.ReactNode;
  style?: any;
}

export default function AnimatedGradientText({ children, style }: AnimatedGradientTextProps) {
  const gradientAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animateGradient = () => {
      Animated.loop(
        Animated.timing(gradientAnim, {
          toValue: 1,
          duration: 3000,
          useNativeDriver: false,
        })
      ).start();
    };

    animateGradient();
  }, []);

  const gradientColors = gradientAnim.interpolate({
    inputRange: [0, 0.25, 0.5, 0.75, 1],
    outputRange: [
      '#7DD3FC', // Azul claro
      '#60A5FA', // Azul
      '#3B82F6', // Azul mais escuro
      '#60A5FA', // Azul
      '#7DD3FC', // Azul claro
    ],
  });

  return (
    <Animated.Text
      style={[
        styles.text,
        style,
        {
          color: gradientColors,
        },
      ]}
    >
      {children}
    </Animated.Text>
  );
}

const styles = StyleSheet.create({
  text: {
    // Estilos base
  },
});
