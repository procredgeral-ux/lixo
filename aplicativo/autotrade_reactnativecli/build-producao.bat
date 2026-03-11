@echo off
chcp 65001 >nul
:: ==========================================
:: SCRIPT DE BUILD PRODUCAO - AUTOTRADE APP
:: Logs desabilitados | Otimizado | Assinado
:: API: https://lixo-production.up.railway.app
:: ==========================================

echo ==========================================
echo  AUTOTRADE - BUILD DE PRODUCAO
echo ==========================================
echo  API: lixo-production.up.railway.app
echo.

:: Verificar Node.js
echo [1/8] Verificando ambiente...
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado!
    exit /b 1
)

:: Verificar API_URL
echo [2/8] Verificando configuracao da API...
findstr /C:"lixo-production.up.railway.app" constants\api.ts >nul
if errorlevel 1 (
    echo [AVISO] API_URL parece nao estar configurada para producao!
    echo         Verifique constants/api.ts antes de continuar.
    echo.
    choice /C SN /M "Deseja continuar mesmo assim"
    if errorlevel 2 exit /b 1
)

:: Verificar keystore
if not exist "android\app\release.keystore" (
    echo.
    echo [!] Keystore nao encontrado!
    echo     Usando debug.keystore para testes...
    echo.
)

:: Verificar signing.properties
echo [3/8] Verificando configuracao de assinatura...
if not exist "android\app\signing.properties" (
    echo [AVISO] Arquivo signing.properties nao encontrado
    echo         Usando debug signing para teste
)

:: Limpar builds antigos
echo [4/8] Limpando builds antigos...
cd android
call gradlew clean >nul 2>&1
cd ..

:: Instalar dependencias
echo [5/8] Instalando dependencias...
call npm ci
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    exit /b 1
)

:: Gerar bundle de producao
echo [6/8] Gerando bundle JS de producao (sem logs)...
if not exist "android\app\src\main\assets" mkdir "android\app\src\main\assets"
set NODE_ENV=production
npx react-native bundle --platform android --dev false --entry-file index.js --bundle-output android/app/src/main/assets/index.android.bundle --assets-dest android/app/src/main/res
if errorlevel 1 (
    echo [ERRO] Falha ao gerar bundle
    exit /b 1
)

:: Build APK Release
echo [7/8] Compilando APK de producao...
cd android
call gradlew assembleRelease --console=plain
if errorlevel 1 (
    echo [ERRO] Build falhou!
    cd ..
    exit /b 1
)
cd ..

:: Build AAB (para Play Store)
echo [8/8] Gerando Android App Bundle (AAB)...
cd android
call gradlew bundleRelease --console=plain
if errorlevel 1 (
    echo [AVISO] Falha ao gerar AAB, mas APK foi criado com sucesso
) else (
    echo     [OK] AAB gerado com sucesso
)
cd ..

:: Resultado
echo.
echo ==========================================
echo  BUILD CONCLUIDO COM SUCESSO!
echo ==========================================
echo.
echo Arquivos gerados:
echo.
echo [APK para instalacao direta]:
echo     android\app\build\outputs\apk\release\app-release.apk
echo.
echo [AAB para Google Play Store]:
echo     android\app\build\outputs\bundle\release\app-release.aab
echo.
echo ==========================================
echo  CARACTERISTICAS DO BUILD:
echo ==========================================
echo   [OK] Logs console.* REMOVIDOS
echo   [OK] Codigo ofuscado e minificado
echo   [OK] Recursos comprimidos
echo   [OK] APK assinado
echo   [OK] Hermes engine ativado
echo ==========================================
echo.

exit /b 0
