# ─── SEARCH.PY — SearXNG Suche & Seiten-Scraping ─────────────────────────────

import re
import requests
from bs4 import BeautifulSoup
import state


SEARXNG_URL = "http://localhost:8888/search"


def detect_language(text: str) -> str:
    """Einfache Spracherkennung — englisch oder deutsch."""
    english_words = {"the", "is", "are", "what", "how", "can", "for", "on", "in",
                     "of", "a", "an", "about", "with", "find", "search", "tell",
                     "me", "information", "research"}
    words = set(text.lower().split())
    return "en-US" if len(words & english_words) >= 2 else "de-DE"


def fetch_page(url: str, query: str = "", max_words: int = 800) -> str:
    """Ruft eine Seite ab und extrahiert relevante Absätze."""
    try:
        headers = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer":         "https://www.google.com/",
            "DNT":             "1",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "form", "iframe", "noscript", "figure", "figcaption",
                         "button", "input", "select", "textarea"]):
            tag.decompose()

        main = (soup.find("article") or soup.find("main") or
                soup.find(id=re.compile(r'content|main|article', re.I)) or
                soup.find(class_=re.compile(r'content|main|article|post|entry', re.I)) or
                soup.find("body"))
        if not main:
            return ""

        blocks = []
        for tag in main.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
            text = tag.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 40:
                blocks.append(text)

        if not blocks:
            text  = main.get_text(separator=" ", strip=True)
            text  = re.sub(r'\s+', ' ', text).strip()
            words = text.split()
            return " ".join(words[:max_words]) + ("..." if len(words) > max_words else "")

        if query:
            query_words = set(re.sub(r'[^\w\s]', '', query.lower()).split())
            stopwords   = {"the","a","an","is","are","for","on","in","of","with","and",
                           "or","to","at","by","from","how","what","can","be","me","i",
                           "you","we","they","this","that"}
            query_words -= stopwords

            def relevance(block):
                block_lower = block.lower()
                matches = sum(1 for w in query_words if w in block_lower)
                return matches * (1 + len(block) / 2000)

            scored = [(relevance(b), i, b) for i, b in enumerate(blocks)]
            scored.sort(key=lambda x: (-x[0], x[1]))
            blocks = [b for _, _, b in scored]

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

    except Exception as e:
        print(f"[Fetch] Fehler bei {url}: {e}")
        return ""


def search_searxng(query: str, max_results: int = 8) -> list:
    language = detect_language(query)
    params   = {"q": query, "format": "json", "language": language}

    print(f"[SearXNG] Suche nach: {query} (lang: {language})")
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

    print(f"[SearXNG] {len(results)} Ergebnisse gefunden")
    for r in results:
        print(f"  → {r['title'][:50]}")

    # Research-Modus: Seiten scrapen
    if state.research_enabled and results:
        print("[Research] Rufe Seiten ab...")
        successful = 0
        for r in results:
            if successful >= 5:
                break
            if r["url"]:
                content = fetch_page(r["url"], query=query)
                if content:
                    r["full_content"] = content
                    successful += 1
                    print(f"[Research] ✓ ({successful}/5) {r['url'][:60]}")
        print(f"[Research] {successful} Seiten erfolgreich abgerufen")

    return results


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
