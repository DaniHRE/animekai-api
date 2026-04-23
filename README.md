# AnimeKAI API

API em Flask para buscar informacoes de animes no AnimeKai.

## Requisitos
- Python 3.10+
- Dependencias em requirements.txt

## Instalar
pip install -r requirements.txt

## Executar
python app.py

## Docker (producao)

### 1. Build da imagem
docker build -t animekai-api:latest .

### 2. Rodar container
docker run -d \
	--name animekai-api \
	-p 5000:5000 \
	--restart unless-stopped \
	animekai-api:latest

### 3. Testar
curl http://SEU_IP_DO_SERVIDOR:5000/

### 4. Atualizar em deploy
docker pull animekai-api:latest || true
docker stop animekai-api || true
docker rm animekai-api || true
docker run -d \
	--name animekai-api \
	-p 5000:5000 \
	--restart unless-stopped \
	animekai-api:latest

Observacao:
- A aplicacao no container roda com Gunicorn escutando em 0.0.0.0:5000.
- Se usar Nginx/Caddy como proxy reverso, aponte para localhost:5000 no servidor.
