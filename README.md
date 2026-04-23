# AnimeKAI API

API REST em Flask para buscar dados do AnimeKai (home, busca, detalhes, episodios, servidores e source de video).

## Requisitos

- Python 3.10+
- Dependencias do `requirements.txt`

## Instalacao

```bash
pip install -r requirements.txt
```

## Executar localmente

```bash
python3 app.py
```

API padrao em: `http://localhost:5000`

## Visao geral da API

Todos os endpoints retornam JSON.

Padrao de sucesso (geralmente):

```json
{
	"success": true,
	"...": "dados do endpoint"
}
```

Padrao de erro:

```json
{
	"error": "mensagem"
}
```

## Tabela de endpoints

| Metodo | Endpoint | Parametros | Retorno esperado |
|---|---|---|---|
| GET | `/` | - | Metadados da API (`api`, `version`, `endpoints`) |
| GET | `/api/home` | - | Destaques da home: `banner`, `latest_updates`, `top_trending` |
| GET | `/api/most-searched` | - | Lista de termos mais buscados: `count`, `results[]` |
| GET | `/api/search` | `keyword` (query, obrigatorio) | Resultado da busca: `keyword`, `count`, `results[]` |
| GET | `/api/anime/<slug>` | `slug` (path, obrigatorio) | Detalhes do anime: `ani_id`, titulos, descricao, `detail`, `seasons[]` |
| GET | `/api/episodes/<ani_id>` | `ani_id` (path, obrigatorio) | Episodios do anime: `count`, `episodes[]` (inclui `token`) |
| GET | `/api/servers/<ep_token>` | `ep_token` (path, obrigatorio) | Servidores por idioma: `watching`, `servers` |
| GET | `/api/source/<link_id>` | `link_id` (path, obrigatorio) | Fonte final de video: `embed_url`, `skip`, `sources[]`, `tracks[]`, `download` |

## Fluxo recomendado de uso

Para chegar no stream final, a sequencia mais comum e:

1. Buscar anime por nome em `/api/search?keyword=...` e pegar o `slug`.
2. Consultar `/api/anime/<slug>` para obter o `ani_id`.
3. Consultar `/api/episodes/<ani_id>` e pegar o `token` do episodio.
4. Consultar `/api/servers/<ep_token>` e pegar o `link_id` do servidor desejado.
5. Consultar `/api/source/<link_id>` para obter `sources` (m3u8/mp4), legendas (`tracks`) e `skip`.

## Exemplos de uso (curl)

### 1) Health/check rapido

```bash
curl "http://localhost:5000/"
```

### 2) Buscar anime

```bash
curl "http://localhost:5000/api/search?keyword=one%20piece"
```

Exemplo de retorno (resumido):

```json
{
	"success": true,
	"keyword": "one piece",
	"count": 1,
	"results": [
		{
			"title": "One Piece",
			"slug": "one-piece-100",
			"url": "https://anikai.to/watch/one-piece-100"
		}
	]
}
```

### 3) Detalhes do anime

```bash
curl "http://localhost:5000/api/anime/one-piece-100"
```

Exemplo de retorno (resumido):

```json
{
	"success": true,
	"ani_id": "12345",
	"title": "One Piece",
	"detail": {
		"genres": ["Action", "Adventure"]
	},
	"seasons": []
}
```

### 4) Episodios

```bash
curl "http://localhost:5000/api/episodes/12345"
```

Exemplo de retorno (resumido):

```json
{
	"success": true,
	"ani_id": "12345",
	"count": 2,
	"episodes": [
		{
			"number": "1",
			"title": "Episode 1",
			"token": "ep_token_a",
			"has_sub": true,
			"has_dub": false
		}
	]
}
```

### 5) Servidores por episodio

```bash
curl "http://localhost:5000/api/servers/ep_token_a"
```

Exemplo de retorno (resumido):

```json
{
	"success": true,
	"watching": "Episode 1",
	"servers": {
		"sub": [
			{
				"name": "Server 1",
				"link_id": "link_abc"
			}
		]
	}
}
```

### 6) Source final de video

```bash
curl "http://localhost:5000/api/source/link_abc"
```

Exemplo de retorno (resumido):

```json
{
	"success": true,
	"embed_url": "https://...",
	"skip": {
		"intro": [0, 90]
	},
	"sources": [
		{
			"file": "https://...m3u8"
		}
	],
	"tracks": [],
	"download": "https://..."
}
```

## Status codes

- `200`: Sucesso
- `400`: Parametro faltando ou invalido (ex.: `keyword` vazio em `/api/search`)
- `500`: Falha interna na coleta/parse/decode dos dados upstream

## Docker (producao)

### 1) Build da imagem

```bash
docker build -t animekai-api:latest .
```

### 2) Rodar container

```bash
docker run -d --name animekai-api -p 5000:5000 --restart unless-stopped animekai-api:latest
```

### 3) Testar

```bash
curl http://SEU_IP_DO_SERVIDOR:5000/
```

### 4) Atualizar deploy

```bash
docker pull animekai-api:latest || true
docker stop animekai-api || true
docker rm animekai-api || true
docker run -d \
	--name animekai-api \
	-p 5000:5000 \
	--restart unless-stopped \
	animekai-api:latest
```

## Observacoes

- A aplicacao no container roda com Gunicorn em `0.0.0.0:5000`.
- Se usar Nginx/Caddy como proxy reverso, aponte para `localhost:5000` no servidor.
