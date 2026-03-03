import React, { useState, useRef } from 'react';
import { View, StyleSheet, Text, PanResponder, Platform } from 'react-native';

interface RangeSliderProps {
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  showLabels?: boolean;
  label?: string;
}

const RangeSlider: React.FC<RangeSliderProps> = ({
  min,
  max,
  value,
  onChange,
  step = 1,
  showLabels = true,
  label,
}) => {
  const [sliderWidth, setSliderWidth] = useState(300);
  const [sliderLeft, setSliderLeft] = useState(0);
  const sliderRef = useRef<View>(null);

  const totalRange = max - min;
  const sliderValue = Math.max(min, Math.min(max, value));
  const percent = ((sliderValue - min) / totalRange) * 100;

  const positionToValue = (position: number) => {
    const clampedPosition = Math.max(0, Math.min(sliderWidth, position));
    const rawValue = min + (clampedPosition / sliderWidth) * totalRange;
    const stepped = step >= 1 ? Math.round(rawValue / step) * step : rawValue;
    return Math.max(min, Math.min(max, stepped));
  };

  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: (evt) => {
      const pageX = evt.nativeEvent.pageX;
      const x = pageX - sliderLeft;
      const newValue = positionToValue(x);
      onChange(newValue);
    },
    onPanResponderMove: (evt) => {
      const pageX = evt.nativeEvent.pageX;
      const x = pageX - sliderLeft;
      const newValue = positionToValue(x);
      onChange(newValue);
    },
    onPanResponderRelease: () => {},
  });

  const measureSlider = () => {
    sliderRef.current?.measure((x, y, width, height, pageX, pageY) => {
      setSliderWidth(width);
      setSliderLeft(pageX);
    });
  };

  return (
    <View style={styles.container}>
      {label && <Text style={styles.label}>{label}</Text>}
      {showLabels && (
        <View style={styles.labels}>
          <Text style={styles.valueLabel}>{min}</Text>
          <Text style={styles.valueLabel}>{max}</Text>
        </View>
      )}
      <View
        ref={sliderRef}
        style={styles.sliderContainer}
        onLayout={measureSlider}
        hitSlop={{ top: 20, bottom: 20, left: 0, right: 0 }}
        {...panResponder.panHandlers}
      >
        <View style={styles.track} />
        <View style={[styles.fill, { width: `${percent}%` }]} />
        <View style={[styles.thumb, { left: `${percent}%` }]}>
          <View style={styles.thumbInner} />
        </View>
      </View>
      <View style={styles.valueDisplay}>
        <Text style={styles.currentValue}>
          {sliderValue.toFixed(step < 1 ? 2 : 0)}
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingVertical: 8,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 8,
  },
  labels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  valueLabel: {
    fontSize: 12,
    color: '#64748B',
  },
  sliderContainer: {
    height: 48,
    justifyContent: 'center',
    position: 'relative',
  },
  track: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 22,
    height: 4,
    backgroundColor: '#334155',
    borderRadius: 2,
  },
  fill: {
    position: 'absolute',
    left: 0,
    top: 22,
    height: 4,
    backgroundColor: '#7DD3FC',
    borderRadius: 2,
  },
  thumb: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#7DD3FC',
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: -14,
    top: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 4,
  },
  thumbInner: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: '#FFFFFF',
  },
  valueDisplay: {
    alignItems: 'center',
    marginTop: 4,
  },
  currentValue: {
    fontSize: 16,
    fontWeight: '600',
    color: '#7DD3FC',
  },
});

export default RangeSlider;
