"""
AffanMarvel Auto-Poster — SAVE TO JSON VERSION
================================================
Saves rewritten articles to articles.json in the repo.
WordPress plugin then pulls and imports them as drafts.
"""

import os
import re
import json
import time
import difflib
import requests
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
POSTED_FILE  = "posted_urls.txt"
OUTPUT_FILE  = "articles.json"
ARTICLES_PER_SOURCE = 10
MAX_TO_REWRITE      = 20

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE NEWS TOPICS
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_NEWS_TOPICS = [
    "Marvel MCU latest news",
    "DC Comics movies news",
    "Anime new season 2026",
    "Superhero movie trailer 2026",
    "Comic book news today",
]

# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE TARGETS
# ─────────────────────────────────────────────────────────────────────────────

SCRAPE_TARGETS = [
    {
        "url":      "https://www.cbr.com/",
        "source":   "CBR-Scrape",
        "item_sel": "h2 a, h3 a",
        "base_url": "https://www.cbr.com",
    },
    {
        "url":      "https://comicbook.com/",
        "source":   "ComicBook-Scrape",
        "item_sel": "h2 a, h3 a",
        "base_url": "https://comicbook.com",
    },
]

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY DETECTION
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Marvel":  ["marvel", "avengers", "iron man", "captain america", "thor",
                 "spider-man", "wolverine", "x-men", "mcu", "deadpool",
                 "black panther", "guardians", "loki", "wanda"],
    "DC":      ["dc comics", "dc universe", "batman", "superman", "wonder woman",
                 "flash", "aquaman", "joker", "justice league", "supergirl",
                 "black adam", "shazam", "dcu", "james gunn"],
    "Anime":   ["anime", "manga", "demon slayer", "jujutsu", "naruto", "one piece",
                 "attack on titan", "dragon ball", "bleach", "my hero academia",
                 "chainsaw man", "isekai", "crunchyroll"],
    "Movies":  ["movie", "film", "trailer", "box office", "cinema", "release date",
                 "director", "cast", "sequel", "prequel", "reboot"],
    "Comics":  ["comic", "issue", "graphic novel", "variant", "writer",
                 "artist", "publisher", "image comics", "dark horse"],
}

def detect_category(title, summary=""):
    text   = (title + " " + summary).lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"

# ─────────────────────────────────────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def load_posted_urls():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(
            line.strip() for line in f
            if line.strip() and not line.startswith("#")
        )

def save_posted_url(url):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")

def titles_are_similar(t1, t2, threshold=0.72):
    return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio() >= threshold

def deduplicate_articles(articles, posted_urls):
    seen_titles = []
    unique      = []
    for art in articles:
        url   = art.get("url", "").strip()
        title = art.get("title", "").strip()
        if not url or not title:
            continue
        if url in posted_urls:
            continue
        if any(titles_are_similar(title, t) for t in seen_titles):
            continue
        unique.append(art)
        seen_titles.append(title)
    return unique

# ─────────────────────────────────────────────────────────────────────────────
# FLOW 2 — GOOGLE NEWS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_google_news_articles():
    articles = []
    for topic in GOOGLE_NEWS_TOPICS:
        try:
            encoded = requests.utils.quote(topic)
            url     = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            print(f"  [Google News] {topic} ...")
            feed  = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= ARTICLES_PER_SOURCE:
                    break
                link  = entry.get("link", "").strip()
                title = re.sub(r"\s*-\s*[^-]+$", "", entry.get("title", "")).strip()
                if link and title and len(title) > 10:
                    articles.append({
                        "url":     link,
                        "title":   title,
                        "summary": entry.get("summary", "").strip()[:600],
                        "source":  "GoogleNews",
                        "flow":    "GoogleNews",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# FLOW 3 — WEB SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_scraped_articles():
    articles = []
    for target in SCRAPE_TARGETS:
        source = target["source"]
        try:
            print(f"  [Scrape] {source} ...")
            resp = requests.get(target["url"], headers=SCRAPE_HEADERS, timeout=20)
            resp.raise_for_status()
            soup  = BeautifulSoup(resp.text, "html.parser")
            tags  = soup.select(target["item_sel"])
            count = 0
            seen  = set()
            for tag in tags:
                if count >= ARTICLES_PER_SOURCE:
                    break
                href  = tag.get("href", "").strip()
                title = tag.get_text(strip=True)
                if not href or not title or len(title) < 15:
                    continue
                if href.startswith("/"):
                    href = target["base_url"] + href
                if not href.startswith("http") or href in seen:
                    continue
                seen.add(href)
                articles.append({
                    "url":     href,
                    "title":   title,
                    "summary": "",
                    "source":  source,
                    "flow":    "Scrape",
                })
                count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error scraping {source}: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# GROQ AI REWRITE
# ─────────────────────────────────────────────────────────────────────────────

def rewrite_with_groq(title, summary, category, source):
    if not GROQ_API_KEY:
        return None

    prompt = f"""You are a pop culture news writer for AffanMarvel.

Write a NEWS BLOG POST:
Title    : {title}
Category : {category}
Summary  : {summary if summary else "Write from title only."}

RULES:
1. New catchy title — do NOT copy original.
2. Exactly 3 paragraphs in <p> tags.
3. 200-280 words total.
4. Do NOT mention source website.
5. End paragraph 3 with a reader question.

Return ONLY this JSON (no markdown, no backticks):
{{"title":"new title","content":"<p>para1</p><p>para2</p><p>para3</p>","excerpt":"one sentence max 25 words","tags":["tag1","tag2","tag3","tag4","tag5"]}}"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       "llama-3.1-8b-instant",
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens":  700,
    }

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code == 429:
                print(f"  ⏳ Rate limited — waiting 30s...")
                time.sleep(30)
                continue

            resp.raise_for_status()
            raw   = resp.json()["choices"][0]["message"]["content"]
            raw   = re.sub(r"```json\s*|```", "", raw).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw = match.group(0)
            raw  = re.sub(r'[\x00-\x1f\x7f]', ' ', raw)
            data = json.loads(raw)
            for key in ("title", "content", "excerpt", "tags"):
                if key not in data:
                    raise ValueError(f"Missing key: {key}")
            return data

        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(5)
                continue
            return None
        except Exception as e:
            print(f"  ⚠ Error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(10)
                continue
            return None
    return None

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print(f"  AffanMarvel Auto-Poster — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not GROQ_API_KEY:
        raise EnvironmentError("Missing GROQ_API_KEY secret!")

    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)} URLs tracked\n")

    all_raw = []

    print("━━━ FLOW 2: GOOGLE NEWS ━━━━━━━━━━━━━━━━━━━━━━━━━")
    gn = fetch_google_news_articles()
    print(f"  Subtotal: {len(gn)}\n")
    all_raw.extend(gn)

    print("━━━ FLOW 3: WEB SCRAPING ━━━━━━━━━━━━━━━━━━━━━━━━")
    sc = fetch_scraped_articles()
    print(f"  Subtotal: {len(sc)}\n")
    all_raw.extend(sc)

    print(f"📦 Total raw       : {len(all_raw)}")
    unique     = deduplicate_articles(all_raw, posted_urls)
    print(f"✅ After dedup     : {len(unique)}")
    to_process = unique[:MAX_TO_REWRITE]
    print(f"🚀 Processing      : {len(to_process)}\n")

    if not to_process:
        print("😴 No new articles. Exiting.")
        # Write empty articles file
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({"generated_at": str(datetime.now()), "articles": []}, f)
        return

    results = []

    for i, article in enumerate(to_process, 1):
        print(f"─── Article {i}/{len(to_process)} ───────────────────────────")
        print(f"  Title  : {article['title'][:75]}")
        category = detect_category(article["title"], article.get("summary", ""))
        print(f"  Category: {category}")
        print("  ✍  Rewriting with Groq...")

        rewritten = rewrite_with_groq(
            title    = article["title"],
            summary  = article.get("summary", ""),
            category = category,
            source   = article["source"],
        )

        if rewritten is None:
            print("  ✗ Skipping")
            time.sleep(3)
            continue

        print(f"  ✓ New title: {rewritten['title'][:65]}")

        results.append({
            "title":      rewritten["title"],
            "content":    rewritten["content"],
            "excerpt":    rewritten["excerpt"],
            "tags":       rewritten.get("tags", []),
            "category":   category,
            "source_url": article["url"],
        })

        save_posted_url(article["url"])

        if i < len(to_process):
            time.sleep(3)

    # Save articles.json for WordPress plugin to import
    output = {
        "generated_at": str(datetime.now()),
        "count":        len(results),
        "articles":     results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved {len(results)} articles to {OUTPUT_FILE}")
    print("=" * 60)
    print(f"  Articles ready   : {len(results)}")
    print(f"  Now go to WP Admin → AffanMarvel Importer → Import!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
