# 🚀 GUIA DE BUILD DE PRODUÇÃO - AUTOTRADE

## 🌐 API DE PRODUÇÃO

**URL:** `https://lixo-production.up.railway.app`

O aplicativo está configurado para apontar automaticamente para a API de produção no Railway.

---

## ✅ BUILD OTIMIZADO - LOGS DESABILITADOS

Este guia configura o aplicativo para **produção real** com:
- ❌ `console.log` completamente removidos
- ❌ Logs de debug Android removidos
- ✅ Código ofuscado e minificado
- ✅ APK assinado para distribuição
- ✅ AAB pronto para Google Play Store

---

## 📋 PRÉ-REQUISITOS

- Node.js >= 18
- JDK 17
- Android Studio / SDK
- Windows (para .bat) ou adaptar para Linux/Mac

---

## 🔧 CONFIGURAÇÃO RÁPIDA

### 1️⃣ Criar Keystore (Primeira vez apenas)

```bash
cd android/app
keytool -genkey -v -keystore release.keystore -alias autotrade -keyalg RSA -keysize 2048 -validity 10000
```

> **Guarde a senha em local seguro!** Você vai precisar dela para atualizar o app futuramente.

---

### 2️⃣ Configurar Assinatura

Edite `android/app/signing.properties`:

```properties
STORE_FILE=release.keystore
STORE_PASSWORD=sua_senha_aqui
KEY_ALIAS=autotrade
KEY_PASSWORD=sua_senha_aqui
```

---

## 🚀 COMPILAR PARA PRODUÇÃO

### **Windows (Script Automatizado)**

```bash
build-producao.bat
```

Esse script faz automaticamente:
1. ✅ Verifica ambiente
2. ✅ Cria keystore se não existir
3. ✅ Limpa builds antigos
4. ✅ Instala dependências (`npm ci`)
5. ✅ Gera bundle JS **sem logs** (`NODE_ENV=production`)
6. ✅ Compila APK assinado
7. ✅ Gera AAB para Play Store

---

### **Manual (Se preferir)**

```bash
# Limpar
cd android && gradlew clean && cd ..

# Instalar dependências
npm ci

# Gerar bundle SEM logs (crucial!)
set NODE_ENV=production
npx react-native bundle --platform android --dev false --entry-file index.js --bundle-output android/app/src/main/assets/index.android.bundle --assets-dest android/app/src/main/res

# Build APK Release
cd android && gradlew assembleRelease

# Build AAB (Play Store)
cd android && gradlew bundleRelease
```

---

## 📦 ARQUIVOS GERADOS

Após build bem-sucedido:

| Arquivo | Local | Uso |
|---------|-------|-----|
| **APK** | `android/app/build/outputs/apk/release/app-release.apk` | Instalação direta |
| **AAB** | `android/app/build/outputs/bundle/release/app-release.aab` | Google Play Store |

---

## 🔒 COMO FUNCIONA A REMOÇÃO DE LOGS

### JavaScript (Console)
O plugin `babel-plugin-transform-remove-console` **remove completamente** todas as chamadas `console.*` durante o build de produção:

```javascript
// Seu código original
console.log('Dados:', data);
console.error('Erro:', err);

// Após build de produção - COMPLETAMENTE REMOVIDO
// Não gera código, não impacta performance
```

### Android (Logcat)
Regras ProGuard removem logs nativos:
```proguard
-assumenosideeffects class android.util.Log { ... }
```

---

## 🧪 VERIFICAR SE LOGS FORAM REMOVIDOS

### 1. Instalar APK em dispositivo físico
```bash
adb install android/app/build/outputs/apk/release/app-release.apk
```

### 2. Verificar logcat (não deve aparecer logs do app)
```bash
adb logcat | grep "ReactNative"
```

Se configurado corretamente, **nenhum log** do seu app deve aparecer.

---

## 📝 CHECKLIST ANTES DE PUBLICAR

- [ ] Criar keystore e guardar senha em local seguro
- [ ] Configurar `signing.properties` com senhas corretas
- [ ] Executar `build-producao.bat` sem erros
- [ ] Testar APK instalado em dispositivo físico
- [ ] Verificar que logs não aparecem no logcat
- [ ] Testar todas as funcionalidades principais
- [ ] Verificar tamanho do APK (deve ser menor com minifyEnabled)
- [ ] Validar AAB no Play Console (se for publicar na Play Store)

---

## 🐛 SOLUÇÃO DE PROBLEMAS

### "Keystore file not found"
```bash
cd android/app
keytool -genkey -v -keystore release.keystore -alias autotrade -keyalg RSA -keysize 2048 -validity 10000
```

### "SigningConfig not found"
Verifique se `signing.properties` existe em `android/app/` e contém as senhas corretas.

### "Build falha com erro de memória"
```gradle
// Em android/gradle.properties
org.gradle.jvmargs=-Xmx4096m
```

### Logs ainda aparecem
1. Verifique se `NODE_ENV=production` foi setado
2. Limpe cache: `npx react-native start --reset-cache`
3. Reinstale node_modules: `rmdir /s /q node_modules && npm install`

---

## 🔄 PUBLICAR NA PLAY STORE

1. Acesse [Google Play Console](https://play.google.com/console)
2. Crie nova versão
3. Faça upload do arquivo `app-release.aab`
4. Preencha informações obrigatórias
5. Envie para revisão

---

## 📱 COMPARTILHAR APK DIRETAMENTE

O APK gerado pode ser:
- Enviado por WhatsApp/Telegram
- Hospedado em servidor
- Instalado via USB com ADB

> ⚠️ **Aviso:** APKs instalados fora da Play Store requerem "Instalação de fontes desconhecidas" ativada nas configurações do Android.

---

## 🎯 COMANDOS ÚTEIS

```bash
# Instalar APK no dispositivo conectado
adb install android/app/build/outputs/apk/release/app-release.apk

# Ver logs do dispositivo (para debug)
adb logcat

# Limpar completamente
cd android && gradlew clean && cd .. && rmdir /s /q node_modules && npm install

# Verificar assinatura do APK
keytool -list -printcert -jarfile android/app/build/outputs/apk/release/app-release.apk
```

---

**Build de produção configurado com sucesso! 🎉**
