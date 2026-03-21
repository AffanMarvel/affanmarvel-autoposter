"""
AffanMarvel Auto-Poster — GROQ + XML-RPC VERSION
==================================================
Uses XML-RPC to post to WordPress (works on InfinityFree!)
Flow 2 : Google News RSS  — 10 articles per topic
Flow 3 : Web Scraping     — 10 articles per site
"""

import os
import re
import json
import time
import difflib
import requests
import feedparser
import xmlrpc.client
import urllib3
from datetime import datetime
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
WP_URL          = os.environ.get("WP_URL", "").rstrip("/")
WP_USERNAME     = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

POSTED_FILE         = "posted_urls.txt"
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
                 "black panther", "guardians", "loki", "wanda", "hawkeye"],
    "DC":      ["dc comics", "dc universe", "batman", "superman", "wonder woman",
                 "flash", "aquaman", "joker", "justice league", "green lantern",
                 "black adam", "shazam", "dcu", "james gunn", "supergirl"],
    "Anime":   ["anime", "manga", "demon slayer", "jujutsu", "naruto", "one piece",
                 "attack on titan", "dragon ball", "bleach", "my hero academia",
                 "chainsaw man", "isekai", "shonen", "seinen", "crunchyroll"],
    "Movies":  ["movie", "film", "trailer", "box office", "cinema", "release date",
                 "director", "cast", "sequel", "prequel", "reboot"],
    "Comics":  ["comic", "issue", "graphic novel", "variant", "run", "arc",
                 "writer", "artist", "publisher", "image comics", "dark horse"],
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
            resp = requests.get(
                target["url"], headers=SCRAPE_HEADERS, timeout=20
            )
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
        print("  ⚠ GROQ_API_KEY not set")
        return None

    prompt = f"""You are a pop culture news writer for AffanMarvel.

Write a NEWS BLOG POST based on:
Title    : {title}
Category : {category}
Summary  : {summary if summary else "Write from title only."}

RULES:
1. New catchy title — do NOT copy the original.
2. Exactly 3 paragraphs wrapped in <p> tags.
3. 200-280 words total.
4. Do NOT mention source website.
5. End paragraph 3 with a reader question.

Return ONLY this JSON (no markdown, no backticks, no extra text):
{{"title":"new title","content":"<p>para1</p><p>para2</p><p>para3</p>","excerpt":"one sentence max 25 words","tags":["tag1","tag2","tag3","tag4","tag5"]}}"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       "llama-3.1-8b-instant",
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens":  800,
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
                wait_time = 30 * (attempt + 1)
                print(f"  ⏳ Rate limited — waiting {wait_time}s...")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            raw   = resp.json()["choices"][0]["message"]["content"]
            raw   = re.sub(r"```json\s*|```", "", raw).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw = match.group(0)
            # Remove control characters
            raw = re.sub(r'[\x00-\x1f\x7f]', ' ', raw)
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
# WORDPRESS XML-RPC (works on InfinityFree!)
# ─────────────────────────────────────────────────────────────────────────────

def post_to_wordpress_xmlrpc(title, content, excerpt, category, tags):
    """Post to WordPress using XML-RPC — bypasses InfinityFree REST API blocks."""
    xmlrpc_url = f"{WP_URL}/xmlrpc.php"

    # Build post data
    post_data = {
        "post_title":   title,
        "post_content": content,
        "post_excerpt": excerpt,
        "post_status":  "draft",
        "terms_names": {
            "category": [category],
            "post_tag": tags,
        },
    }

    try:
        # Use transport that ignores SSL issues
        transport = xmlrpc.client.SafeTransport()

        # Create server connection
        server = xmlrpc.client.ServerProxy(
            xmlrpc_url,
            transport=transport,
            allow_none=True,
        )

        # Post using WordPress XML-RPC API
        post_id = server.wp.newPost(
            0,                  # blog_id (always 0)
            WP_USERNAME,
            WP_APP_PASSWORD,
            post_data,
        )

        post_url = f"{WP_URL}/?p={post_id}"
        print(f"  ✓ Draft created via XML-RPC → ID {post_id} | {post_url}")
        return str(post_id)

    except Exception as e:
        print(f"  ✗ XML-RPC error: {e}")
        # Try fallback with http instead of https
        try:
            http_url = xmlrpc_url.replace("https://", "http://")
            server2  = xmlrpc.client.ServerProxy(http_url, allow_none=True)
            post_id  = server2.wp.newPost(
                0,
                WP_USERNAME,
                WP_APP_PASSWORD,
                post_data,
            )
            print(f"  ✓ Draft created via XML-RPC (http) → ID {post_id}")
            return str(post_id)
        except Exception as e2:
            print(f"  ✗ XML-RPC fallback error: {e2}")
            return None

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def validate_config():
    missing = []
    if not GROQ_API_KEY:    missing.append("GROQ_API_KEY")
    if not WP_URL:          missing.append("WP_URL")
    if not WP_USERNAME:     missing.append("WP_USERNAME")
    if not WP_APP_PASSWORD: missing.append("WP_APP_PASSWORD")
    if missing:
        raise EnvironmentError(f"Missing GitHub Secrets: {', '.join(missing)}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print(f"  AffanMarvel Auto-Poster (Groq+XMLRPC) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    validate_config()
    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)} URLs tracked\n")

    all_raw = []

    print("━━━ FLOW 2: GOOGLE NEWS (10 per topic) ━━━━━━━━━━━")
    gn = fetch_google_news_articles()
    print(f"  Subtotal: {len(gn)} articles\n")
    all_raw.extend(gn)

    print("━━━ FLOW 3: WEB SCRAPING (10 per site) ━━━━━━━━━━━")
    sc = fetch_scraped_articles()
    print(f"  Subtotal: {len(sc)} articles\n")
    all_raw.extend(sc)

    print(f"📦 Total raw collected : {len(all_raw)}")

    unique = deduplicate_articles(all_raw, posted_urls)
    print(f"✅ After deduplication : {len(unique)} unique articles")

    if not unique:
        print("\n😴 No new articles found. All caught up!\n")
        return

    to_process = unique[:MAX_TO_REWRITE]
    print(f"🚀 Processing         : {len(to_process)} articles this run\n")

    success_count = 0
    fail_count    = 0

    for i, article in enumerate(to_process, 1):
        print(f"─── Article {i}/{len(to_process)} ─────────────────────────────")
        print(f"  Title  : {article['title'][:80]}")
        print(f"  Source : {article['source']} [{article['flow']}]")

        category = detect_category(article["title"], article.get("summary", ""))
        print(f"  Category: {category}")

        print("  ✍  Rewriting with Groq AI...")
        rewritten = rewrite_with_groq(
            title    = article["title"],
            summary  = article.get("summary", ""),
            category = category,
            source   = article["source"],
        )

        if rewritten is None:
            print("  ✗ Skipping — Groq rewrite failed")
            fail_count += 1
            time.sleep(3)
            continue

        print(f"  New title: {rewritten['title'][:70]}")
        print("  📤 Posting to WordPress as DRAFT (XML-RPC)...")

        result = post_to_wordpress_xmlrpc(
            title    = rewritten["title"],
            content  = rewritten["content"],
            excerpt  = rewritten["excerpt"],
            category = category,
            tags     = rewritten.get("tags", []),
        )

        if result:
            save_posted_url(article["url"])
            success_count += 1
        else:
            fail_count += 1

        if i < len(to_process):
            print("  ⏳ Waiting 3s...")
            time.sleep(3)

    print("\n" + "=" * 60)
    print(f"  ✅ Run complete!")
    print(f"  Published as draft : {success_count}")
    print(f"  Failed / skipped   : {fail_count}")
    print(f"  Check WordPress    : {WP_URL}/wp-admin/edit.php?post_status=draft")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
