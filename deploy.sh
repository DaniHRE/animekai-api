#!/bin/bash

set -e

echo "🚀 Atualizando Animekai API..."

cd /opt/animekai-api

echo "📥 Atualizando código (forçado)..."
GIT_SSH_COMMAND="ssh -i /root/.ssh/animekai_deploy -o IdentitiesOnly=yes" git fetch origin
git reset --hard origin/main
git clean -fd

echo "🐳 Build da imagem Docker..."
docker build -t animekai-api:latest .

echo "🛑 Parando container antigo..."
docker stop animekai-api 2>/dev/null || true
docker rm animekai-api 2>/dev/null || true

echo "▶️ Subindo novo container..."
docker run -d \
  --name animekai-api \
  -p 127.0.0.1:5000:5000 \
  --restart unless-stopped \
  animekai-api:latest

echo "🧹 Limpando imagens antigas..."
docker image prune -f

echo "✅ Deploy finalizado!"