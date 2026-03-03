import React from 'react';
import SsidExtractor from '../components/SsidExtractor';

export default function ExtractSsidScreen() {
  return (
    <SsidExtractor 
      environment="real" 
      title="Extrair SSID" 
    />
  );
}