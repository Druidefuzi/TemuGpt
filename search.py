# ─── SEARCH.PY — SearXNG Suche & Seiten-Scraping ─────────────────────────────

import re
import requests
from bs4 import BeautifulSoup
from config import LM_STUDIO_URL
import state


SEARXNG_URL = "http://localhost:8888/search"

# Maximale Response-Größe beim Scrapen (2 MB)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


# ─── SPRACH-ERKENNUNG ─────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Erkennt die Sprache des Textes via LLM mini-call.
    Fallback auf einfache Heuristik wenn LLM nicht erreichbar."""
    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [
                {"role": "system", "content": "Detect the language of the user's text. Reply with ONLY the language code, nothing else. Examples: de-DE, en-US, fr-FR, es-ES, ja-JP, zh-CN"},
                {"role": "user",   "content": text[:200]}  # Nur die ersten 200 Zeichen
            ],
            "temperature": 0.0,
            "max_tokens":  8,
            "stream":      False
        }, timeout=5)
        resp.raise_for_status()
        lang = resp.json()["choices"][0]["message"].get("content", "").strip()
        # Nur gültige Sprachcodes akzeptieren (z.B. "de-DE", "en-US", "fr-FR")
        lang = re.sub(r'<think>.*?</think>', '', lang, flags=re.DOTALL).strip()
        if re.match(r'^[a-z]{2}-[A-Z]{2}$', lang):
            print(f"[Lang] LLM erkannt: {lang}")
            return lang
        # Einfaches Format wie "de" oder "en" auch akzeptieren
        if re.match(r'^[a-z]{2}$', lang):
            lang_map = {"de": "de-DE", "en": "en-US", "fr": "fr-FR", "es": "es-ES",
                        "it": "it-IT", "ja": "ja-JP", "zh": "zh-CN", "pt": "pt-BR",
                        "ru": "ru-RU", "ko": "ko-KR", "nl": "nl-NL", "pl": "pl-PL"}
            result = lang_map.get(lang, "en-US")
            print(f"[Lang] LLM erkannt (kurz): {lang} → {result}")
            return result
        print(f"[Lang] LLM ungültig: '{lang}', nutze Fallback")
    except Exception as e:
        print(f"[Lang] LLM Fehler: {e}, nutze Fallback")

    return _detect_language_fallback(text)


def _detect_language_fallback(text: str) -> str:
    """Einfache Heuristik als Fallback — Default ist Englisch."""
    german_words = {"der", "die", "das", "ist", "und", "ein", "eine", "für", "auf",
                    "mit", "von", "den", "dem", "des", "wie", "was", "kann", "nicht",
                    "sich", "auch", "nach", "wird", "bei", "noch", "aus", "über",
                    "hat", "sind", "haben", "oder", "aber", "wenn", "ich", "du",
                    "wir", "sie", "ihr", "mein", "dein", "sein", "werden", "wurde",
                    "gibt", "diese", "dieser", "diesem", "welche", "warum", "weil"}
    words = set(text.lower().split())
    german_count = len(words & german_words)
    if german_count >= 2:
        print(f"[Lang] Fallback: de-DE ({german_count} deutsche Wörter)")
        return "de-DE"
    print("[Lang] Fallback: en-US (default)")
    return "en-US"


# ─── REDDIT SPEZIAL-HANDLER ───────────────────────────────────────────────────

def _fetch_reddit(url: str, query: str = "", max_words: int = 800) -> str:
    """Reddit-Seiten via JSON-API oder old.reddit.com abrufen.
    Fallback-Chain: JSON → old.reddit.com → leer."""
    import json as _json

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept":     "application/json, text/html",
    }

    # ── Versuch 1: Reddit JSON-API ────────────────────────────────────────
    json_url = re.sub(r'/?\?.*$', '', url.rstrip('/')) + '.json'
    try:
        resp = requests.get(json_url, headers=headers, timeout=(3, 8))
        if resp.ok:
            data = resp.json()
            blocks = []

            # Post-Daten extrahieren
            if isinstance(data, list) and len(data) > 0:
                # Post-Titel + Selftext
                post_data = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
                title    = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                if title:
                    blocks.append(f"# {title}")
                if selftext:
                    blocks.append(selftext)

                # Top-Kommentare (wenn vorhanden)
                if len(data) > 1:
                    comments = data[1].get("data", {}).get("children", [])
                    for c in comments[:10]:  # Max 10 Top-Kommentare
                        cdata = c.get("data", {})
                        body  = cdata.get("body", "")
                        score = cdata.get("score", 0)
                        if body and score > 1 and len(body) > 30:
                            blocks.append(body)

            if blocks:
                # Zusammensetzen mit Wortlimit
                result = []
                total  = 0
                for block in blocks:
                    words = block.split()
                    if total + len(words) > max_words:
                        remaining = max_words - total
                        if remaining > 20:
                            result.append(" ".join(words[:remaining]) + "...")
                        break
                    result.append(block)
                    total += len(words)
                text = "\n\n".join(result)
                if text.strip():
                    print(f"[Reddit] ✓ JSON: {len(text)} Zeichen — {url[:60]}")
                    return text
    except Exception as e:
        print(f"[Reddit] JSON fehlgeschlagen: {e}")

    # ── Versuch 2: old.reddit.com ─────────────────────────────────────────
    old_url = url.replace("www.reddit.com", "old.reddit.com").replace("://reddit.com", "://old.reddit.com")
    if old_url == url:
        # URL hat kein bekanntes Reddit-Prefix — trotzdem versuchen
        old_url = re.sub(r'https?://([^/]*reddit\.com)', r'https://old.reddit.com', url)

    try:
        resp = requests.get(old_url, headers={**headers, "Accept": "text/html"}, timeout=(3, 8))
        if resp.ok:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Noise entfernen
            for tag in soup(["script", "style", "nav", "footer", "aside", "form"]):
                tag.decompose()

            blocks = []
            # Post-Titel
            title_el = soup.find(class_="title") or soup.find("h1")
            if title_el:
                blocks.append(title_el.get_text(strip=True))

            # Selftext
            selftext_el = soup.find(class_="usertext-body") or soup.find(class_="md")
            if selftext_el:
                blocks.append(selftext_el.get_text(separator=" ", strip=True))

            # Kommentare
            for comment in soup.find_all(class_="comment", limit=10):
                body = comment.find(class_="md")
                if body:
                    text = body.get_text(separator=" ", strip=True)
                    if len(text) > 30:
                        blocks.append(text)

            if blocks:
                result = []
                total  = 0
                for block in blocks:
                    words = block.split()
                    if total + len(words) > max_words:
                        remaining = max_words - total
                        if remaining > 20:
                            result.append(" ".join(words[:remaining]) + "...")
                        break
                    result.append(block)
                    total += len(words)
                text = "\n\n".join(result)
                if text.strip():
                    print(f"[Reddit] ✓ old.reddit: {len(text)} Zeichen — {url[:60]}")
                    return text
    except Exception as e:
        print(f"[Reddit] old.reddit fehlgeschlagen: {e}")

    print(f"[Reddit] ✗ Beide Methoden fehlgeschlagen: {url[:60]}")
    return ""


# ─── SEITEN-SCRAPING ──────────────────────────────────────────────────────────

def fetch_page(url: str, query: str = "", max_words: int = 800) -> str:
    """Ruft eine Seite ab und extrahiert relevante Absätze.

    Verbesserungen:
    - Reddit: JSON-API → old.reddit.com Fallback-Chain
    - Timeout-Tuple (Connect/Read separat)
    - Response-Size-Limit (2 MB)
    - Encoding-Fix für falsch deklarierte Seiten
    - Redirect-Begrenzung
    """
    # Reddit-URLs speziell behandeln
    if "reddit.com" in url:
        return _fetch_reddit(url, query=query, max_words=max_words)

    try:
        headers = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer":         "https://www.google.com/",
            "DNT":             "1",
        }

        session = requests.Session()
        session.max_redirects = 5

        resp = session.get(
            url,
            headers=headers,
            timeout=(3, 8),        # 3s Connect, 8s Read
            allow_redirects=True,
            stream=True            # Streaming für Size-Check
        )
        resp.raise_for_status()

        # Content-Type prüfen — nur HTML verarbeiten
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            print(f"[Fetch] Kein HTML: {content_type[:50]} — {url[:60]}")
            resp.close()
            return ""

        # Encoding aus Header holen BEVOR der Stream konsumiert wird
        header_encoding = resp.encoding  # Aus Content-Type Header, liest keinen Body

        # Size-Check: Nur bis MAX_RESPONSE_BYTES lesen
        chunks = []
        total  = 0
        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=False):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                print(f"[Fetch] Size-Limit ({MAX_RESPONSE_BYTES // 1024}KB) erreicht: {url[:60]}")
                break
        resp.close()
        raw_bytes = b"".join(chunks)

        # Encoding bestimmen: Header → Meta-Tag → UTF-8 Fallback
        encoding = header_encoding or "utf-8"
        # Wenn Header "ISO-8859-1" sagt (oft Default), prüfe ob es eigentlich UTF-8 ist
        if encoding.lower() in ("iso-8859-1", "latin-1", "ascii"):
            try:
                raw_bytes.decode("utf-8", errors="strict")
                encoding = "utf-8"
            except UnicodeDecodeError:
                pass  # Ist tatsächlich ISO-8859-1
        try:
            html = raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = raw_bytes.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")

        # Noise entfernen
        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "form", "iframe", "noscript", "figure", "figcaption",
                         "button", "input", "select", "textarea",
                         "svg", "canvas", "video", "audio"]):
            tag.decompose()

        # Cookie-Banner / Popups entfernen
        for tag in soup.find_all(class_=re.compile(
                r'cookie|consent|gdpr|popup|modal|overlay|banner|newsletter',
                re.I)):
            tag.decompose()

        # Hauptinhalt finden (Fallback-Chain)
        main = (soup.find("article") or soup.find("main") or
                soup.find(id=re.compile(r'content|main|article', re.I)) or
                soup.find(class_=re.compile(r'content|main|article|post|entry', re.I)) or
                soup.find("body"))
        if not main:
            return ""

        # Text-Blöcke extrahieren
        blocks = []
        for tag in main.find_all(["p", "h1", "h2", "h3", "h4", "li", "td", "th", "blockquote"]):
            text = tag.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 40:
                blocks.append(text)

        # Fallback: Gesamttext wenn keine Blöcke
        if not blocks:
            text  = main.get_text(separator=" ", strip=True)
            text  = re.sub(r'\s+', ' ', text).strip()
            words = text.split()
            return " ".join(words[:max_words]) + ("..." if len(words) > max_words else "")

        # Relevanz-Scoring wenn Query vorhanden
        if query:
            query_words = set(re.sub(r'[^\w\s]', '', query.lower()).split())
            stopwords   = {"the", "a", "an", "is", "are", "for", "on", "in", "of",
                           "with", "and", "or", "to", "at", "by", "from", "how",
                           "what", "can", "be", "me", "i", "you", "we", "they",
                           "this", "that", "der", "die", "das", "und", "ist", "ein",
                           "eine", "für", "auf", "mit", "von"}
            query_words -= stopwords

            if query_words:
                def relevance(block):
                    block_lower = block.lower()
                    matches = sum(1 for w in query_words if w in block_lower)
                    return matches * (1 + len(block) / 2000)

                scored = [(relevance(b), i, b) for i, b in enumerate(blocks)]
                scored.sort(key=lambda x: (-x[0], x[1]))
                blocks = [b for _, _, b in scored]

        # Blöcke bis zum Wortlimit zusammensetzen
        result_blocks = []
        total_words   = 0
        for block in blocks:
            words = block.split()
            if total_words + len(words) > max_words:
                remaining = max_words - total_words
                if remaining > 20:
                    result_blocks.append(" ".join(words[:remaining]) + "...")
                break
            result_blocks.append(block)
            total_words += len(words)

        return "\n".join(result_blocks)

    except requests.exceptions.TooManyRedirects:
        print(f"[Fetch] Zu viele Redirects: {url[:60]}")
        return ""
    except requests.exceptions.ConnectionError as e:
        print(f"[Fetch] Verbindungsfehler: {url[:60]} — {e}")
        return ""
    except requests.exceptions.Timeout:
        print(f"[Fetch] Timeout: {url[:60]}")
        return ""
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(f"[Fetch] HTTP {status}: {url[:60]}")
        return ""
    except Exception as e:
        print(f"[Fetch] Fehler: {url[:60]} — {type(e).__name__}: {e}")
        return ""


# ─── SEARXNG SUCHE ────────────────────────────────────────────────────────────

def search_searxng(query: str, max_results: int = 8) -> list:
    """Sucht via SearXNG und gibt Ergebnisse zurück.
    Kein Scraping hier — das passiert in server.py mit SSE-Progress."""
    language = detect_language(query)
    params   = {"q": query, "format": "json", "language": language}

    print(f"[SearXNG] Suche: {query} (lang: {language}, max: {max_results})")
    try:
        resp = requests.get(SEARXNG_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[SearXNG] Fehler: {e}")
        return []

    results = []
    for r in data.get("results", [])[:max_results]:
        results.append({
            "title":   r.get("title", ""),
            "snippet": r.get("content", ""),
            "url":     r.get("url", "")
        })

    print(f"[SearXNG] {len(results)} Ergebnisse")
    for r in results:
        print(f"  → {r['title'][:50]}")

    return results


# ─── FORMATIERUNG ─────────────────────────────────────────────────────────────

def format_search_results(query: str, results: list) -> str:
    """Formatiert Suchergebnisse als Text für das LLM."""
    if not results:
        return f"Keine Suchergebnisse für: {query}. Bitte antworte ehrlich dass keine Ergebnisse gefunden wurden."

    text = f"Suchergebnisse für '{query}':\n\n"
    for i, r in enumerate(results, 1):
        text += f"{i}. **{r['title']}**\n"
        if r.get("full_content"):
            text += f"   {r['full_content']}\n"
            print(f"[Format] ✓ {r['title'][:40]}: {len(r['full_content'])} Zeichen")
        else:
            text += f"   {r['snippet']}\n"
            print(f"[Format] ✗ nur Snippet: {r['title'][:40]}")
        text += "\n"

    print(f"[Format] Gesamt: {len(text)} Zeichen ans LLM")
    return text