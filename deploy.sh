#!/bin/bash

set -e

echo "🚀 Atualizando Animekai API..."

cd /opt/animekai-api

echo "📥 Pull do repositório..."
GIT_SSH_COMMAND="ssh -i /root/.ssh/animekai_deploy -o IdentitiesOnly=yes" git pull

echo "🐳 Build da imagem Docker..."
docker build -t animekai-api:latest .

echo "🛑 Parando container antigo..."
docker stop animekai-api 2>/dev/null || true
docker rm animekai-api 2>/dev/null || true

echo "▶️ Subindo novo container..."
docker run -d \
  --name animekai-api \
  -p 5000:5000 \
  --restart unless-stopped \
  animekai-api:latest

echo "✅ Deploy finalizado!"