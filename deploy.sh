#!/bin/bash

# Script de Deploy para VPS Hostinger
# Tunestrade API

set -e

echo "================================"
echo "TUNESTRADE - DEPLOY VPS"
echo "================================"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funções
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verificar se está no diretório correto
if [ ! -f "docker-compose.yml" ]; then
    log_error "Arquivo docker-compose.yml não encontrado!"
    log_error "Execute este script no diretório do projeto tunestrade"
    exit 1
fi

# Criar .env se não existir
if [ ! -f ".env" ]; then
    log_warn "Arquivo .env não encontrado. Criando..."
    cat > .env << EOF
# Database
DB_PASSWORD=senha_segura_$(openssl rand -hex 8)

# JWT
JWT_SECRET=$(openssl rand -hex 32)

# Admin
ADMIN_API_KEY=admin_$(openssl rand -hex 16)

# Environment
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
EOF
    log_info "Arquivo .env criado com valores aleatórios!"
    log_warn "Edite o arquivo .env para configurar seus valores reais"
fi

# Pull do código mais recente
log_info "Atualizando código do GitHub..."
git pull origin main

# Build e start dos containers
log_info "Construindo containers..."
docker-compose build --no-cache

log_info "Iniciando serviços..."
docker-compose up -d

# Verificar status
log_info "Verificando status dos containers..."
sleep 5
docker-compose ps

# Verificar logs
log_info "Últimas linhas de log:"
docker-compose logs --tail=20 app

echo ""
echo "================================"
log_info "DEPLOY CONCLUÍDO!"
echo "================================"
echo ""
echo "API disponível em: http://$(curl -s ifconfig.me):8000"
echo "Health check: http://$(curl -s ifconfig.me):8000/health"
echo ""
echo "Comandos úteis:"
echo "  docker-compose logs -f app    # Ver logs em tempo real"
echo "  docker-compose restart app    # Reiniciar API"
echo "  docker-compose down           # Parar todos os serviços"
echo ""
