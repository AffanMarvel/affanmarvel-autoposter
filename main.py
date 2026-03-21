"""
AffanMarvel Auto-Poster — FIXED VERSION
========================================
Flow 1 : RSS Feeds       — 5 articles per site
Flow 2 : Google News RSS — 5 articles per topic
Flow 3 : Web Scraping    — 5 articles per scrape target
After  : Deduplicate → Gemini rewrite → WordPress DRAFT
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
# 1. CONFIG
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
WP_URL          = os.environ.get("WP_URL", "").rstrip("/")
WP_USERNAME     = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

POSTED_FILE          = "posted_urls.txt"
ARTICLES_PER_SOURCE  = 5
MAX_TO_REWRITE       = 5

# ─────────────────────────────────────────────────────────────────────────────
# 2. FLOW 1 — RSS FEEDS
# ─────────────────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "https://www.cbr.com/feed/",                          "source": "CBR"},
    {"url": "https://comicbook.com/feed/",                        "source": "ComicBook"},
    {"url": "https://screenrant.com/feed/",                       "source": "ScreenRant"},
    {"url": "https://www.animenewsnetwork.com/all/rss.xml",       "source": "AnimeNewsNetwork"},
    {"url": "https://www.ign.com/articles.rss",                   "source": "IGN"},
    {"url": "https://heroichollywood.com/feed/",                  "source": "HeroicHollywood"},
    {"url": "https://www.superherohype.com/feed",                 "source": "SuperheroHype"},
    {"url": "https://www.themarysue.com/feed/",                   "source": "TheMARySue"},
    {"url": "https://deadline.com/category/film/feed/",           "source": "Deadline"},
    {"url": "https://variety.com/v/film/feed/",                   "source": "Variety"},
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. FLOW 2 — GOOGLE NEWS RSS
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_NEWS_TOPICS = [
    "Marvel MCU latest news",
    "DC Comics movies news",
    "Anime new season 2025",
    "Superhero movie trailer",
    "Comic book news today",
]

# ─────────────────────────────────────────────────────────────────────────────
# 4. FLOW 3 — SCRAPE TARGETS
# ─────────────────────────────────────────────────────────────────────────────

SCRAPE_TARGETS = [
    {
        "url":      "https://www.cbr.com/tag/marvel/",
        "source":   "CBR-Marvel-Scrape",
        "item_sel": "article h2 a",
    },
    {
        "url":      "https://www.cbr.com/tag/anime/",
        "source":   "CBR-Anime-Scrape",
        "item_sel": "article h2 a",
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
# 5. CATEGORY DETECTION
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Marvel":  ["marvel", "avengers", "iron man", "captain america", "thor",
                 "spider-man", "wolverine", "x-men", "mcu", "deadpool",
                 "black panther", "guardians", "loki", "wanda", "hawkeye"],
    "DC":      ["dc comics", "dc universe", "batman", "superman", "wonder woman",
                 "flash", "aquaman", "joker", "justice league", "green lantern",
                 "black adam", "shazam", "dcu", "james gunn"],
    "Anime":   ["anime", "manga", "demon slayer", "jujutsu", "naruto", "one piece",
                 "attack on titan", "dragon ball", "bleach", "my hero academia",
                 "chainsaw man", "isekai", "shonen", "seinen", "crunchyroll"],
    "Movies":  ["movie", "film", "trailer", "box office", "cinema", "release date",
                 "director", "cast", "sequel", "prequel", "reboot"],
    "Comics":  ["comic", "issue", "graphic novel", "variant", "run", "arc",
                 "storyline", "writer", "artist", "publisher"],
}

def detect_category(title, summary=""):
    text = (title + " " + summary).lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"

# ─────────────────────────────────────────────────────────────────────────────
# 6. DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def load_posted_urls():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def save_posted_url(url):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")

def titles_are_similar(t1, t2, threshold=0.72):
    ratio = difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio()
    return ratio >= threshold

def deduplicate_articles(articles, posted_urls):
    seen_titles = []
    unique = []
    for art in articles:
        url   = art.get("url", "").strip()
        title = art.get("title", "").strip()
        if url in posted_urls:
            continue
        is_dup = any(titles_are_similar(title, t) for t in seen_titles)
        if not is_dup:
            unique.append(art)
            seen_titles.append(title)
    return unique

# ─────────────────────────────────────────────────────────────────────────────
# 7. FLOW 1 — FETCH RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_rss_articles():
    articles = []
    for feed_info in RSS_FEEDS:
        source = feed_info["source"]
        try:
            print(f"  [RSS] {source} ...")
            feed  = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= ARTICLES_PER_SOURCE:
                    break
                link    = entry.get("link", "").strip()
                title   = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()
                if link and title:
                    articles.append({
                        "url": link, "title": title,
                        "summary": summary[:600], "source": source, "flow": "RSS",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error fetching {source}: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 8. FLOW 2 — GOOGLE NEWS
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
                if link and title:
                    articles.append({
                        "url": link, "title": title,
                        "summary": entry.get("summary", "").strip()[:600],
                        "source": f"GoogleNews", "flow": "GoogleNews",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error fetching Google News for '{topic}': {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 9. FLOW 3 — SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_scraped_articles():
    articles = []
    for target in SCRAPE_TARGETS:
        source = target["source"]
        try:
            print(f"  [Scrape] {source} ...")
            resp  = requests.get(target["url"], headers=SCRAPE_HEADERS, timeout=15)
            resp.raise_for_status()
            soup  = BeautifulSoup(resp.text, "html.parser")
            links = soup.select(target["item_sel"])
            count = 0
            for tag in links:
                if count >= ARTICLES_PER_SOURCE:
                    break
                href  = tag.get("href", "").strip()
                title = tag.get_text(strip=True)
                if not href or not title:
                    continue
                if href.startswith("/"):
                    base = "/".join(target["url"].split("/")[:3])
                    href = base + href
                if href.startswith("http") and len(title) > 10:
                    articles.append({
                        "url": href, "title": title,
                        "summary": "", "source": source, "flow": "Scrape",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error scraping {source}: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 10. GEMINI REWRITE — WITH RETRY ON 429
# ─────────────────────────────────────────────────────────────────────────────

def rewrite_with_gemini(title, summary, category, source):
    if not GEMINI_API_KEY:
        print("  ⚠ GEMINI_API_KEY not set")
        return None

    prompt = f"""You are a pop culture news writer for AffanMarvel — a site covering Marvel, DC, Anime, and Movies.

Write a NEWS BLOG POST based on this article info:

Original Title : {title}
Category       : {category}
Source Summary : {summary if summary else "Write from the title alone."}

STRICT RULES:
1. Write a new catchy title — do NOT copy the original.
2. Write EXACTLY 3 short paragraphs:
   - Paragraph 1: What happened / the main news.
   - Paragraph 2: Why it matters / fan reaction / background.
   - Paragraph 3: What to expect next / closing thought + one question for readers.
3. Total: 200-280 words only.
4. Do NOT mention the source website name.
5. Wrap each paragraph in <p> HTML tags.

Return ONLY valid JSON (no markdown, no backticks):
{{
  "title": "Your new catchy title here",
  "content": "<p>Para 1</p><p>Para 2</p><p>Para 3</p>",
  "excerpt": "One sentence summary (max 25 words).",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 1024,
            "topP": 0.9,
        },
    }

    # Retry up to 3 times on rate limit
    for attempt in range(3):
        try:
            resp = requests.post(api_url, json=payload, timeout=40)

            if resp.status_code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"  ⏳ Rate limited (429) — waiting {wait_time}s then retrying... (attempt {attempt+1}/3)")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            raw  = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw  = re.sub(r"```json\s*|```", "", raw).strip()
            data = json.loads(raw)

            for key in ("title", "content", "excerpt", "tags"):
                if key not in data:
                    raise ValueError(f"Missing key '{key}' in Gemini response")

            return data

        except json.JSONDecodeError as e:
            print(f"  ⚠ Gemini JSON parse error: {e}")
            return None
        except requests.exceptions.RequestException as e:
            if attempt < 2:
                print(f"  ⚠ Request error (attempt {attempt+1}): {e} — retrying in 30s...")
                time.sleep(30)
                continue
            print(f"  ⚠ Gemini request failed after 3 attempts: {e}")
            return None
        except Exception as e:
            print(f"  ⚠ Unexpected error: {e}")
            return None

    return None

# ─────────────────────────────────────────────────────────────────────────────
# 11. WORDPRESS — GET CATEGORY ID
# ─────────────────────────────────────────────────────────────────────────────

_category_id_cache = {}

def get_wp_category_id(category_name):
    if category_name in _category_id_cache:
        return _category_id_cache[category_name]
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            params={"search": category_name, "per_page": 5},
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            for cat in data:
                if cat.get("name", "").lower() == category_name.lower():
                    _category_id_cache[category_name] = cat["id"]
                    return cat["id"]
            _category_id_cache[category_name] = data[0]["id"]
            return data[0]["id"]
    except Exception as e:
        print(f"  ⚠ Could not get category ID for '{category_name}': {e}")
    _category_id_cache[category_name] = 1
    return 1

# ─────────────────────────────────────────────────────────────────────────────
# 12. WORDPRESS — GET OR CREATE TAGS
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_tag_ids(tag_names):
    tag_ids = []
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        try:
            r = requests.get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                params={"search": name, "per_page": 5},
                auth=(WP_USERNAME, WP_APP_PASSWORD),
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            matched = None
            for tag in data:
                if tag.get("name", "").lower() == name.lower():
                    matched = tag["id"]
                    break
            if matched:
                tag_ids.append(matched)
            else:
                c = requests.post(
                    f"{WP_URL}/wp-json/wp/v2/tags",
                    json={"name": name},
                    auth=(WP_USERNAME, WP_APP_PASSWORD),
                    timeout=10,
                )
                if c.status_code == 201:
                    tag_ids.append(c.json()["id"])
        except Exception as e:
            print(f"  ⚠ Tag error for '{name}': {e}")
    return tag_ids

# ─────────────────────────────────────────────────────────────────────────────
# 13. WORDPRESS — POST AS DRAFT
# ─────────────────────────────────────────────────────────────────────────────

def post_to_wordpress_draft(title, content, excerpt, category, tags, source_url):
    cat_id  = get_wp_category_id(category)
    tag_ids = get_or_create_tag_ids(tags)

    post_body = {
        "title":      title,
        "content":    content,
        "excerpt":    excerpt,
        "status":     "draft",
        "categories": [cat_id],
        "tags":       tag_ids,
    }

    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            json=post_body,
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=20,
        )
        if resp.status_code == 201:
            post = resp.json()
            print(f"  ✓ Draft created → ID {post.get('id')} | {post.get('link','')}")
            return post.get("link", "success")
        else:
            print(f"  ✗ WordPress error {resp.status_code}: {resp.text[:300]}")
            return None
    except Exception as e:
        print(f"  ✗ WordPress request error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 14. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def validate_config():
    missing = []
    if not GEMINI_API_KEY:  missing.append("GEMINI_API_KEY")
    if not WP_URL:          missing.append("WP_URL")
    if not WP_USERNAME:     missing.append("WP_USERNAME")
    if not WP_APP_PASSWORD: missing.append("WP_APP_PASSWORD")
    if missing:
        raise EnvironmentError(f"Missing environment variables: {', '.join(missing)}")

def main():
    print("\n" + "=" * 60)
    print(f"  AffanMarvel Auto-Poster — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    validate_config()
    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)} URLs tracked\n")

    # Collect
    all_raw = []

    print("━━━ FLOW 1: RSS FEEDS ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    rss = fetch_rss_articles()
    print(f"  Subtotal: {len(rss)} articles from RSS\n")
    all_raw.extend(rss)

    print("━━━ FLOW 2: GOOGLE NEWS ━━━━━━━━━━━━━━━━━━━━━━━━━")
    gn = fetch_google_news_articles()
    print(f"  Subtotal: {len(gn)} articles from Google News\n")
    all_raw.extend(gn)

    print("━━━ FLOW 3: WEB SCRAPING ━━━━━━━━━━━━━━━━━━━━━━━━")
    sc = fetch_scraped_articles()
    print(f"  Subtotal: {len(sc)} articles from Scraping\n")
    all_raw.extend(sc)

    print(f"📦 Total raw collected : {len(all_raw)}")

    unique = deduplicate_articles(all_raw, posted_urls)
    print(f"✅ After deduplication : {len(unique)} unique articles")

    if not unique:
        print("\n😴 No new articles found. Exiting.\n")
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

        print("  ✍  Rewriting with Gemini...")
        rewritten = rewrite_with_gemini(
            title    = article["title"],
            summary  = article.get("summary", ""),
            category = category,
            source   = article["source"],
        )

        if rewritten is None:
            print("  ✗ Skipping — Gemini failed")
            fail_count += 1
            time.sleep(15)
            continue

        print(f"  New title: {rewritten['title'][:70]}")
        print("  📤 Posting to WordPress as DRAFT...")

        result = post_to_wordpress_draft(
            title      = rewritten["title"],
            content    = rewritten["content"],
            excerpt    = rewritten["excerpt"],
            category   = category,
            tags       = rewritten.get("tags", []),
            source_url = article["url"],
        )

        if result:
            save_posted_url(article["url"])
            success_count += 1
        else:
            fail_count += 1

        if i < len(to_process):
            print("  ⏳ Waiting 20s before next article...")
            time.sleep(20)

    print("\n" + "=" * 60)
    print(f"  ✅ Run complete!")
    print(f"  Published as draft : {success_count}")
    print(f"  Failed / skipped   : {fail_count}")
    print(f"  Check WordPress    : {WP_URL}/wp-admin/edit.php?post_status=draft")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
