from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import json as _json
import re
from datetime import datetime, timezone
import time
import logging
import os

DEBUG_MODE = os.getenv("API_DEBUG", "0").strip().lower() in {"1", "true", "yes"}

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(funcName)s: %(message)s",
)
log = logging.getLogger(__name__)
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

API_NAME = "Anime Kai REST API"
API_VERSION = "1.2.5"
APP_STARTED_AT = time.time()

ANIMEKAI_URL = "https://anikai.to/"
ANIMEKAI_HOME_URL = "https://anikai.to/home"
ANIMEKAI_SEARCH_URL = "https://anikai.to/ajax/anime/search"
ANIMEKAI_EPISODES_URL = "https://anikai.to/ajax/episodes/list"
ANIMEKAI_SERVERS_URL = "https://anikai.to/ajax/links/list"
ANIMEKAI_LINKS_VIEW_URL = "https://anikai.to/ajax/links/view"

ENCDEC_URL = "https://enc-dec.app/api/enc-kai"
ENCDEC_DEC_KAI = "https://enc-dec.app/api/dec-kai"
ENCDEC_DEC_MEGA = "https://enc-dec.app/api/dec-mega"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://anikai.to/",
}

AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest"
}

def check_upstream_service(name, url, method="GET", accept_4xx=False, treat_expected_error_as_up=None, **request_kwargs):
    started_at = time.perf_counter()
    try:
        timeout = request_kwargs.pop("timeout", 10)
        response = requests.request(method, url, timeout=timeout, **request_kwargs)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        healthy = (200 <= response.status_code < 400) or (accept_4xx and 400 <= response.status_code < 500)
        details = {
            "name": name,
            "status": "up" if healthy else "down",
            "http_status": response.status_code,
            "response_time_ms": elapsed_ms,
        }

        if not healthy and treat_expected_error_as_up:
            body_text = response.text or ""
            if treat_expected_error_as_up in body_text:
                details["status"] = "up"
                details["note"] = "reachable_but_payload_invalid"

        return details
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return {
            "name": name,
            "status": "down",
            "response_time_ms": elapsed_ms,
            "error": str(e),
        }

def encode_token(text):
    try:
        r = requests.get(ENCDEC_URL, params={"text": text}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("result") if data.get("status") == 200 else None
    except Exception as e:
        log.error("encode_token falhou: %s", e)
        return None

def decode_kai(text):
    try:
        r = requests.post(ENCDEC_DEC_KAI, json={"text": text}, timeout=15)
        r.raise_for_status()
        data = r.json()
        log.debug("decode_kai response: %s", data)
        return data.get("result") if data.get("status") == 200 else None
    except Exception as e:
        log.error("decode_kai falhou: %s", e)
        return None

def decode_mega(text):
    try:
        r = requests.post(ENCDEC_DEC_MEGA, json={
            "text": text,
            "agent": HEADERS["User-Agent"],
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        log.debug("decode_mega response: %s", data)
        return data.get("result") if data.get("status") == 200 else None
    except Exception as e:
        log.error("decode_mega falhou: %s", e)
        return None

def extract_count_from_span(span):
    for key in ("data-ep", "data-episodes", "data-count", "data-num"):
        val = span.get(key)
        if isinstance(val, str) and val.isdigit():
            return val

    text = span.get_text(strip=True)
    m = re.search(r"\d+", text)
    return m.group(0) if m else ""

def parse_info_spans(info_el):
    sub_eps = ""
    dub_eps = ""
    anime_type = ""
    for span in info_el.find_all("span") if info_el else []:
        cls = span.get("class", [])
        cls_text = " ".join(cls).lower()
        text = span.get_text(strip=True)
        text_lower = text.lower()
        if "sub" in cls_text or "sub" in text_lower:
            count = extract_count_from_span(span)
            if count:
                sub_eps = count
        elif "dub" in cls_text or "dub" in text_lower:
            count = extract_count_from_span(span)
            if count:
                dub_eps = count
        else:
            b_tag = span.find("b")
            if b_tag:
                anime_type = text
    return sub_eps, dub_eps, anime_type

def extract_sub_dub_from_container(container):
    sub_eps = ""
    dub_eps = ""
    if not container:
        return sub_eps, dub_eps

    for node in container.find_all(["span", "div"]):
        cls = node.get("class", [])
        cls_text = " ".join(cls).lower()
        text = node.get_text(" ", strip=True)
        text_lower = text.lower()

        if not sub_eps and ("sub" in cls_text or "sub" in text_lower):
            count = extract_count_from_span(node)
            if count:
                sub_eps = count

        if not dub_eps and ("dub" in cls_text or "dub" in text_lower):
            count = extract_count_from_span(node)
            if count:
                dub_eps = count

        if sub_eps and dub_eps:
            break

    return sub_eps, dub_eps

def extract_total_episodes(info_el, detail):
    if isinstance(detail, dict):
        for key in ("episodes", "episode", "eps"):
            val = detail.get(key)
            if isinstance(val, str):
                m = re.search(r"\d+", val)
                if m:
                    return m.group(0)

    if info_el:
        for span in info_el.find_all("span"):
            text = span.get_text(strip=True)
            if span.find("b") and text.isdigit():
                return text

    return ""

def extract_counts_from_episodes(episodes):
    sub_count = 0
    dub_count = 0
    for ep in episodes:
        if ep.get("has_sub"):
            sub_count += 1
        if ep.get("has_dub"):
            dub_count += 1

    return {
        "sub": str(sub_count) if sub_count else "",
        "dub": str(dub_count) if dub_count else "",
        "total": str(len(episodes)) if episodes else "",
    }

def maybe_error_response(res):
    if isinstance(res, tuple) and len(res) == 2:
        payload, status = res
        return jsonify(payload), status
    if isinstance(res, dict) and "error" in res:
        return jsonify(res), 500
    return None

def scrape_most_searched():
    try:
        response = requests.get(ANIMEKAI_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        most_searched_div = soup.find("div", class_="most_searched")
        if not most_searched_div:
            most_searched_div = soup.find("div", class_="most-searched")

        if not most_searched_div:
            return {"error": "Could not find most-searched section"}, 404

        results = []
        for link in most_searched_div.find_all("a"):
            name = link.get_text(strip=True)
            href = link.get("href", "")
            keyword = href.split("keyword=")[-1].replace("+", " ") if "keyword=" in href else ""
            if name:
                results.append({
                    "name": name,
                    "keyword": keyword,
                    "search_url": f"{ANIMEKAI_URL.rstrip('/')}{href}" if href.startswith("/") else href,
                })
        return results
    except Exception as e:
        return {"error": str(e)}, 500

def search_anime(keyword):
    try:
        response = requests.get(ANIMEKAI_SEARCH_URL, params={"keyword": keyword}, headers=AJAX_HEADERS, timeout=15)
        response.raise_for_status()
        html = response.json().get("result", {}).get("html", "")
        if not html: return []

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.find_all("a", class_="aitem"):
            title_tag = item.find("h6", class_="title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            japanese_title = title_tag.get("data-jp", "") if title_tag else ""
            poster_img = item.select_one(".poster img")
            poster = poster_img.get("src", "") if poster_img else ""
            href = item.get("href", "")
            slug = href.replace("/watch/", "") if href.startswith("/watch/") else href

            sub, dub, anime_type = "", "", ""
            year = ""
            rating = ""
            total_eps = ""
            
            for span in item.select(".info span"):
                cls = span.get("class", [])
                if "sub" in cls: sub = span.get_text(strip=True)
                elif "dub" in cls: dub = span.get_text(strip=True)
                elif "rating" in cls: rating = span.get_text(strip=True)
                else:
                    b_tag = span.find("b")
                    text = span.get_text(strip=True)
                    if b_tag and text.isdigit(): total_eps = text
                    elif b_tag: anime_type = text
                    else: year = text

            if title:
                results.append({
                    "title": title,
                    "japanese_title": japanese_title,
                    "slug": slug,
                    "url": f"{ANIMEKAI_URL.rstrip('/')}{href}",
                    "poster": poster,
                    "sub_episodes": sub,
                    "dub_episodes": dub,
                    "total_episodes": total_eps,
                    "year": year,
                    "type": anime_type,
                    "rating": rating,
                })
        return results
    except Exception as e:
        return {"error": str(e)}, 500

def scrape_home():
    try:
        response = requests.get(ANIMEKAI_HOME_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        banner = []
        for slide in soup.select(".swiper-slide"):
            style = slide.get("style", "")
            bg_image = style.split("url(")[1].split(")")[0] if "url(" in style else ""
            title_tag = slide.select_one("p.title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            japanese_title = title_tag.get("data-jp", "") if title_tag else ""
            description = slide.select_one("p.desc").get_text(strip=True) if slide.select_one("p.desc") else ""
            
            sub, dub, anime_type = parse_info_spans(slide.select_one(".info"))
            
            genres = ""
            info_el = slide.select_one(".info")
            if info_el:
                for span in info_el.find_all("span"):
                    if not span.get("class") and not span.find("b"):
                        text = span.get_text(strip=True)
                        if text and not text.isdigit(): genres = text

            rating, release, quality = "", "", ""
            mics = slide.select_one(".mics")
            if mics:
                for div in mics.find_all("div", recursive=False):
                    l, v = div.select_one("div"), div.select_one("span")
                    if l and v:
                        lbl = l.get_text(strip=True).lower()
                        if lbl == "rating": rating = v.get_text(strip=True)
                        elif lbl == "release": release = v.get_text(strip=True)
                        elif lbl == "quality": quality = v.get_text(strip=True)

            if title:
                banner.append({
                    "title": title,
                    "japanese_title": japanese_title,
                    "description": description,
                    "poster": bg_image,
                    "url": f"{ANIMEKAI_URL.rstrip('/')}{slide.select_one('a.watch-btn').get('href', '')}" if slide.select_one('a.watch-btn') else "",
                    "sub_episodes": sub,
                    "dub_episodes": dub,
                    "type": anime_type,
                    "genres": genres,
                    "rating": rating,
                    "release": release,
                    "quality": quality,
                })

        latest = []
        for item in soup.select(".aitem-wrapper.regular .aitem"):
            title_tag = item.select_one("a.title")
            href = item.select_one("a.poster").get("href", "") if item.select_one("a.poster") else ""
            episode = href.split("#ep=")[-1] if "#ep=" in href else ""
            href = href.split("#ep=")[0]
            
            sub, dub, anime_type = parse_info_spans(item.select_one(".info"))
            
            if title_tag:
                latest.append({
                    "title": title_tag.get_text(strip=True),
                    "japanese_title": title_tag.get("data-jp", ""),
                    "poster": item.select_one("img.lazyload").get("data-src", "") if item.select_one("img.lazyload") else "",
                    "url": f"{ANIMEKAI_URL.rstrip('/')}{href}",
                    "current_episode": episode,
                    "sub_episodes": sub,
                    "dub_episodes": dub,
                    "type": anime_type,
                })

        trending = {}
        for tab_id, tab_label in {"trending": "NOW", "day": "DAY", "week": "WEEK", "month": "MONTH"}.items():
            container = soup.select_one(f".aitem-col.top-anime[data-id='{tab_id}']")
            if not container: continue
            items = []
            for item in container.find_all("a", class_="aitem"):
                style = item.get("style", "")
                poster = style.split("url(")[1].split(")")[0] if "url(" in style else ""
                sub, dub, anime_type = parse_info_spans(item.select_one(".info"))
                
                items.append({
                    "rank": item.select_one(".num").get_text(strip=True) if item.select_one(".num") else "",
                    "title": item.select_one(".detail .title").get_text(strip=True) if item.select_one(".detail .title") else "",
                    "japanese_title": item.select_one(".detail .title").get("data-jp", "") if item.select_one(".detail .title") else "",
                    "poster": poster,
                    "url": f"{ANIMEKAI_URL.rstrip('/')}{item.get('href', '')}",
                    "sub_episodes": sub,
                    "dub_episodes": dub,
                    "type": anime_type,
                })
            trending[tab_label] = items

        return {"banner": banner, "latest_updates": latest, "top_trending": trending}
    except Exception as e:
        return {"error": str(e)}, 500

def scrape_anime_info(slug):
    try:
        url = f"{ANIMEKAI_URL}watch/{slug}"
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        ani_id = ""
        sync = soup.select_one("script#syncData")
        if sync:
            try: ani_id = _json.loads(sync.string).get("anime_id", "")
            except: pass

        info_el = soup.select_one(".main-entity .info")
        sub, dub, atype = parse_info_spans(info_el)

        
        detail = {}
        for div in soup.select(".detail > div > div"):
            text = div.get_text(separator="|", strip=True)
            if ":" in text:
                k, v = text.split(":", 1)
                k = k.strip().lower().replace(" ", "_").replace(":", "")
                links = div.select("span a")
                detail[k] = [a.get_text(strip=True) for a in links] if links else v.strip().strip("|")

        if not sub or not dub:
            main_entity = soup.select_one(".main-entity")
            fallback_sub, fallback_dub = extract_sub_dub_from_container(main_entity)
            sub = sub or fallback_sub
            dub = dub or fallback_dub

        total_episodes = extract_total_episodes(info_el, detail)

        if (not sub or not dub or not total_episodes) and ani_id:
            episodes_res = fetch_episodes(ani_id)
            if isinstance(episodes_res, list):
                counts = extract_counts_from_episodes(episodes_res)
                sub = sub or counts["sub"]
                dub = dub or counts["dub"]
                if not total_episodes:
                    total_episodes = counts["total"]

        if total_episodes:
            detail["episodes"] = total_episodes

        seasons = []
        for s in soup.select(".swiper-wrapper.season .aitem"):
            is_active = "active" in s.get("class", [])
            d = s.select_one(".detail")
            seasons.append({
                "title": d.select_one("span").get_text(strip=True) if d else "",
                "episodes": d.select_one(".btn").get_text(strip=True) if d else "",
                "poster": s.select_one("img").get("src", "") if s.select_one("img") else "",
                "url": f"{ANIMEKAI_URL.rstrip('/')}{s.select_one('a.poster').get('href', '')}" if s.select_one('a.poster') else "",
                "active": is_active,
            })

        bg_el = soup.select_one(".watch-section-bg")
        banner = bg_el.get("style", "").split("url(")[1].split(")")[0] if bg_el and "url(" in bg_el.get("style", "") else ""

        return {
            "ani_id": ani_id,
            "title": soup.select_one("h1.title").get_text(strip=True) if soup.select_one("h1.title") else "",
            "japanese_title": soup.select_one("h1.title").get("data-jp", "") if soup.select_one("h1.title") else "",
            "description": soup.select_one(".desc").get_text(strip=True) if soup.select_one(".desc") else "",
            "poster": soup.select_one(".poster img[itemprop='image']").get("src", "") if soup.select_one(".poster img[itemprop='image']") else "",
            "banner": banner,
            "sub_episodes": sub,
            "dub_episodes": dub,
            "total_episodes": total_episodes,
            "type": atype,
            "rating": info_el.select_one(".rating").get_text(strip=True) if info_el and info_el.select_one(".rating") else "",
            "mal_score": soup.select_one(".rate-box .value").get_text(strip=True) if soup.select_one(".rate-box .value") else "",
            "detail": detail,
            "seasons": seasons,
        }
    except Exception as e:
        return {"error": str(e)}, 500

def fetch_episodes(ani_id):
    try:
        encoded = encode_token(ani_id)
        if not encoded: return {"error": "Token encryption failed"}, 500
        
        response = requests.get(ANIMEKAI_EPISODES_URL, params={"ani_id": ani_id, "_": encoded}, headers=AJAX_HEADERS, timeout=15)
        response.raise_for_status()
        html = response.json().get("result", "")
        if not html: return []

        soup = BeautifulSoup(html, "html.parser")
        ep_nodes = soup.select(".eplist a")
        episodes = []
        for ep in ep_nodes:
            langs = ep.get("langs", "0")
            episodes.append({
                "number": ep.get("num", ""),
                "slug": ep.get("slug", ""),
                "title": ep.select_one("span").get_text(strip=True) if ep.select_one("span") else "",
                "japanese_title": ep.select_one("span").get("data-jp", "") if ep.select_one("span") else "",
                "token": ep.get("token", ""),
                "has_sub": bool(int(langs) & 1) if langs.isdigit() else False,
                "has_dub": bool(int(langs) & 2) if langs.isdigit() else False,
            })
        return episodes
    except Exception as e:
        return {"error": str(e)}, 500

def fetch_servers(ep_token):
    try:
        encoded = encode_token(ep_token)
        if not encoded: return {"error": "Token encryption failed"}, 500
        
        response = requests.get(ANIMEKAI_SERVERS_URL, params={"token": ep_token, "_": encoded}, headers=AJAX_HEADERS, timeout=15)
        response.raise_for_status()
        html = response.json().get("result", "")
        soup = BeautifulSoup(html, "html.parser")

        servers = {}
        for group in soup.select(".server-items"):
            lang = group.get("data-id", "unknown")
            servers[lang] = [{
                "name": s.get_text(strip=True),
                "server_id": s.get("data-sid", ""),
                "episode_id": s.get("data-eid", ""),
                "link_id": s.get("data-lid", ""),
            } for s in group.select(".server")]
        
        return {
            "watching": soup.select_one(".server-note p").get_text(strip=True) if soup.select_one(".server-note p") else "",
            "servers": servers
        }
    except Exception as e:
        return {"error": str(e)}, 500

def resolve_source(link_id):
    """
    Fluxo:
      1. encode_token(link_id)          → token para assinar a request
      2. GET links/view                 → encrypted_result
      3. decode_kai(encrypted_result)   → embed_url + skip times  ← mínimo necessário
      4. GET <embed>/media/<video_id>   → encrypted_media          (opcional)
      5. decode_mega(encrypted_media)   → sources + tracks         (opcional)

    Se o passo 3 funcionar, a resposta sempre carrega embed_url e skip,
    mesmo que os passos 4-5 falhem ou deem timeout.
    """
    try:
        encoded = encode_token(link_id)
        if not encoded:
            return {"error": "Token encryption failed"}, 500

        resp = requests.get(
            ANIMEKAI_LINKS_VIEW_URL,
            params={"id": link_id, "_": encoded},
            headers=AJAX_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        encrypted_result = resp.json().get("result", "")
        log.debug("encrypted_result preview: %s", str(encrypted_result)[:120])

        if not encrypted_result:
            return {"error": "Empty result from animekai"}, 500

        embed_data = decode_kai(encrypted_result)
        if not embed_data:
            return {"error": "Embed decryption failed"}, 500

        embed_url = embed_data.get("url", "")
        skip      = embed_data.get("skip", {})

        if not embed_url:
            return {"error": "No embed URL found"}, 500

        sources  = []
        tracks   = []
        download = ""

        try:
            video_id   = embed_url.rstrip("/").split("/")[-1]
            embed_base = embed_url.rsplit("/e/", 1)[0] if "/e/" in embed_url else embed_url.rsplit("/", 1)[0]

            media_resp = requests.get(
                f"{embed_base}/media/{video_id}",
                headers=HEADERS,
                timeout=15,
            )
            media_resp.raise_for_status()
            encrypted_media = media_resp.json().get("result", "")

            final_data = decode_mega(encrypted_media)
            if final_data:
                sources  = final_data.get("sources", [])
                tracks   = final_data.get("tracks", [])
                download = final_data.get("download", "")
            else:
                log.warning("decode_mega falhou para link_id=%s — retornando apenas embed_url", link_id)

        except Exception as e:
            log.warning("Falha ao buscar sources/tracks para link_id=%s: %s", link_id, e)

        return {
            "embed_url": embed_url,
            "skip":      skip,
            "sources":   sources,
            "tracks":    tracks,
            "download":  download,
        }

    except Exception as e:
        log.exception("resolve_source falhou para link_id=%s", link_id)
        return {"error": str(e)}, 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "success": True,
        "api": API_NAME,
        "version": API_VERSION,
        "endpoints": {
            "/health": "Quick API health (use ?upstream=1 for dependency checks)",
            "/api/home": "Get banner, latest updates, and trending",
            "/api/most-searched": "Get most-searched anime keywords",
            "/api/search?keyword=...": "Search anime",
            "/api/anime/<slug>": "Get anime details and ani_id",
            "/api/episodes/<ani_id>": "Get episode list and ep tokens",
            "/api/servers/<ep_token>": "Get available servers for an episode",
            "/api/source/<link_id>": "Get embed_url, skip times, and (if available) m3u8 sources",
        }
    })

@app.route("/health", methods=["GET"])
def health():
    started_at = time.perf_counter()

    include_upstream = request.args.get("upstream", "0").strip().lower() in {"1", "true", "yes"}
    dependency_checks = {
        "api_process": {
            "name": "api_process",
            "status": "up",
            "note": "Flask process is running",
        }
    }

    if include_upstream:
        dependency_checks.update({
            "animekai_home": check_upstream_service(
                name="animekai_home",
                url=ANIMEKAI_HOME_URL,
                headers=HEADERS,
                timeout=2,
            ),
            "encdec_enc_kai": check_upstream_service(
                name="encdec_enc_kai",
                url=ENCDEC_URL,
                params={"text": "health"},
                timeout=2,
            ),
        })

    total_services = len(dependency_checks)
    up_services = sum(1 for check in dependency_checks.values() if check.get("status") == "up")
    overall_status = "ok" if up_services == total_services else "degraded"
    status_code = 200 if overall_status == "ok" else 503
    uptime_seconds = max(0, int(time.time() - APP_STARTED_AT))
    health_response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)

    return jsonify({
        "success": overall_status == "ok",
        "status": overall_status,
        "api": API_NAME,
        "version": API_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "response_time_ms": health_response_time_ms,
    }), status_code

@app.route("/api/most-searched", methods=["GET"])
def api_most_searched():
    res = scrape_most_searched()
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, "count": len(res), "results": res})

@app.route("/api/search", methods=["GET"])
def api_search():
    kw = request.args.get("keyword", "").strip()
    if not kw: return jsonify({"error": "Keyword is required"}), 400
    res = search_anime(kw)
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, "keyword": kw, "count": len(res), "results": res})

@app.route("/api/home", methods=["GET"])
def api_home():
    res = scrape_home()
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, **res})

@app.route("/api/anime/<slug>", methods=["GET"])
def api_anime_info(slug):
    res = scrape_anime_info(slug)
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, **res})

@app.route("/api/episodes/<ani_id>", methods=["GET"])
def api_episodes(ani_id):
    res = fetch_episodes(ani_id)
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, "ani_id": ani_id, "count": len(res), "episodes": res})

@app.route("/api/servers/<ep_token>", methods=["GET"])
def api_servers(ep_token):
    res = fetch_servers(ep_token)
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, **res})

@app.route("/api/source/<link_id>", methods=["GET"])
def api_source(link_id):
    res = resolve_source(link_id)
    err = maybe_error_response(res)
    if err: return err
    return jsonify({"success": True, **res})

if DEBUG_MODE:
    @app.route("/debug/source/<link_id>", methods=["GET"])
    def debug_source(link_id):
        """
        Executa cada passo de resolve_source de forma isolada e retorna
        os payloads intermediários. Disponível apenas com API_DEBUG=1.
        """
        steps = {}

        encoded = encode_token(link_id)
        steps["encode_token"] = {"result": encoded, "ok": bool(encoded)}
        if not encoded:
            return jsonify(steps)

        resp = requests.get(
            ANIMEKAI_LINKS_VIEW_URL,
            params={"id": link_id, "_": encoded},
            headers=AJAX_HEADERS,
            timeout=15,
        )
        encrypted_result = resp.json().get("result", "") if resp.ok else ""
        steps["links_view"] = {
            "status_code": resp.status_code,
            "body_preview": resp.text[:500],
        }
        steps["encrypted_result_preview"] = str(encrypted_result)[:200]

        if encrypted_result:
            r = requests.post(ENCDEC_DEC_KAI, json={"text": encrypted_result}, timeout=15)
            steps["decode_kai"] = {"status_code": r.status_code, "body": r.json()}

            embed_data = r.json().get("result") if r.ok and r.json().get("status") == 200 else None
            if embed_data and embed_data.get("url"):
                embed_url  = embed_data["url"]
                video_id   = embed_url.rstrip("/").split("/")[-1]
                embed_base = embed_url.rsplit("/e/", 1)[0] if "/e/" in embed_url else embed_url.rsplit("/", 1)[0]
                m = requests.get(f"{embed_base}/media/{video_id}", headers=HEADERS, timeout=15)
                steps["media_fetch"] = {"status_code": m.status_code, "body_preview": m.text[:300]}

                if m.ok:
                    enc_media = m.json().get("result", "")
                    dm = requests.post(ENCDEC_DEC_MEGA, json={"text": enc_media, "agent": HEADERS["User-Agent"]}, timeout=15)
                    steps["decode_mega"] = {"status_code": dm.status_code, "body": dm.json()}

        return jsonify(steps)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)