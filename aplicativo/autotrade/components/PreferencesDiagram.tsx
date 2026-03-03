import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const { width } = Dimensions.get('window');

interface PreferenceData {
  label: string;
  value: number;
  color: string;
  icon: string;
}

const preferenceData: PreferenceData[] = [
  { label: 'Call', value: 35, color: '#007AFF', icon: 'trending-up-outline' },
  { label: 'Put', value: 25, color: '#FF3B30', icon: 'trending-down-outline' },
  { label: 'Neutro', value: 20, color: '#FF9500', icon: 'remove-outline' },
  { label: 'Aguardando', value: 20, color: '#8E8E93', icon: 'time-outline' },
];

export default function PreferencesDiagram() {
  const total = preferenceData.reduce((sum, item) => sum + item.value, 0);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Preferências de Operação</Text>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={styles.chartContainer}>
          <Text style={styles.chartTitle}>Distribuição</Text>
          <View style={styles.pieContainer}>
            {preferenceData.map((item, index) => {
              const angle = (item.value / total) * 360;
              const rotation = preferenceData
                .slice(0, index)
                .reduce((sum, i, idx) => sum + preferenceData[idx].value, 0) * 360 / total;

              return (
                <View
                  key={item.label}
                  style={[
                    styles.pieSlice,
                    {
                      backgroundColor: item.color,
                      transform: `rotate(${rotation}deg)`,
                    },
                  ]}
                />
              );
            })}
            <Text style={styles.pieCenterText}>100%</Text>
          </View>
        </View>

        <View style={styles.legendContainer}>
          <Text style={styles.legendTitle}>Legenda</Text>
          {preferenceData.map((item) => (
            <View key={item.label} style={styles.legendItem}>
              <View style={[styles.legendColor, { backgroundColor: item.color }]} />
              <Text style={styles.legendLabel}>
                <Ionicons name={item.icon as any} size={16} color="#FFFFFF" /> {item.label}
              </Text>
              <Text style={styles.legendValue}>{item.value}%</Text>
            </View>
          ))}
        </View>
      </ScrollView>

      <View style={styles.statsContainer}>
        <Text style={styles.statsTitle}>Estatísticas</Text>
        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Total de Operações</Text>
          <Text style={styles.statValue}>{total}</Text>
        </View>
        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Operações Vencedoras</Text>
          <Text style={styles.statValueSuccess}>
            {preferenceData[0].value}
          </Text>
        </View>
        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Operações Perdidas</Text>
          <Text style={styles.statValueDanger}>
            {preferenceData[1].value}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    margin: 10,
    borderWidth: 1,
    borderColor: '#3A3A3A',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
  },
  title: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#FFFFFF',
    marginBottom: 20,
    textAlign: 'center',
  },
  chartContainer: {
    width: 160,
    height: 160,
    marginRight: 20,
  },
  chartTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 16,
    textAlign: 'center',
  },
  pieContainer: {
    width: 160,
    height: 160,
    position: 'relative',
  },
  pieSlice: {
    width: 160,
    height: 160,
    position: 'absolute',
    borderRadius: 80,
  },
  pieSliceSegment: {
    width: 160,
    height: 160,
    borderRadius: 80,
    borderWidth: 2,
    borderColor: '#1A1A1A',
  },
  pieCenterText: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    fontSize: 12,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  legendContainer: {
    flex: 1,
  },
  legendTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 12,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#3A3A3A',
  },
  legendColor: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginRight: 8,
  },
  legendLabel: {
    flex: 1,
    fontSize: 14,
    color: '#FFFFFF',
  },
  legendValue: {
    fontSize: 14,
    fontWeight: '600',
    color: '#8E8E93',
  },
  statsContainer: {
    marginTop: 20,
    paddingTop: 20,
    borderTopWidth: 1,
    borderTopColor: '#3A3A3A',
  },
  statsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 12,
  },
  statItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  statLabel: {
    fontSize: 14,
    color: '#8E8E93',
  },
  statValue: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  statValueSuccess: {
    color: '#007AFF',
  },
  statValueDanger: {
    color: '#FF3B30',
  },
});
