import React from 'react';
import SsidExtractor from '../components/SsidExtractor';

export default function ExtractSsidDemoScreen() {
  return (
    <SsidExtractor 
      environment="demo" 
      title="Extrair SSID Demo" 
    />
  );
}