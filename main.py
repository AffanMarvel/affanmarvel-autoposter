"""
AffanMarvel Auto-Poster
=======================
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
# 1. CONFIG  (values come from GitHub Secrets — never hardcode here)
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
WP_URL          = os.environ.get("WP_URL", "").rstrip("/")
WP_USERNAME     = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

POSTED_FILE          = "posted_urls.txt"
ARTICLES_PER_SOURCE  = 5    # How many articles to pull from each source
MAX_TO_REWRITE       = 15   # Max articles sent to Gemini per run (free limit safe)

# ─────────────────────────────────────────────────────────────────────────────
# 2. FLOW 1 — RSS FEEDS  (10 sites × 5 = 50 raw articles)
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
# 3. FLOW 2 — GOOGLE NEWS RSS  (5 topics × 5 = 25 raw articles)
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_NEWS_TOPICS = [
    "Marvel MCU latest news",
    "DC Comics movies news",
    "Anime new season 2025",
    "Superhero movie trailer",
    "Comic book news today",
]

# ─────────────────────────────────────────────────────────────────────────────
# 4. FLOW 3 — SCRAPE TARGETS  (2 sites × 5 = 10 raw articles)
# ─────────────────────────────────────────────────────────────────────────────

SCRAPE_TARGETS = [
    {
        "url":         "https://www.cbr.com/category/marvel/",
        "source":      "CBR-Scrape",
        "item_sel":    "article h2 a",   # CSS selector for article links
        "title_sel":   "h2",
    },
    {
        "url":         "https://www.cbr.com/category/anime/",
        "source":      "CBR-Anime-Scrape",
        "item_sel":    "article h2 a",
        "title_sel":   "h2",
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
# 5. KEYWORD → CATEGORY DETECTION
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
    """Detect the best WordPress category from title + summary keywords."""
    text = (title + " " + summary).lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"

# ─────────────────────────────────────────────────────────────────────────────
# 6. DEDUPLICATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_posted_urls():
    """Load already-posted URLs from file. Returns a set."""
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip() and not line.startswith("#"))

def save_posted_url(url):
    """Append a URL to the posted-tracker file."""
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")
    # Keep file trim — keep only last 1000 entries
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip() and not l.startswith("#")]
        if len(lines) > 1000:
            with open(POSTED_FILE, "w", encoding="utf-8") as f:
                f.write("# AffanMarvel posted URL tracker\n")
                f.writelines(lines[-1000:])
    except Exception:
        pass

def titles_are_similar(t1, t2, threshold=0.72):
    """Return True if two titles are too similar (likely the same story)."""
    ratio = difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio()
    return ratio >= threshold

def deduplicate_articles(articles, posted_urls):
    """
    Remove:
      1. Articles whose URL was already posted.
      2. Articles with titles very similar to another article in THIS batch.
    """
    seen_titles = []
    unique = []

    for art in articles:
        url   = art.get("url", "").strip()
        title = art.get("title", "").strip()

        # Skip if URL already posted before
        if url in posted_urls:
            continue

        # Skip if title is too similar to one already in this batch
        is_dup = False
        for seen_t in seen_titles:
            if titles_are_similar(title, seen_t):
                is_dup = True
                break

        if not is_dup:
            unique.append(art)
            seen_titles.append(title)

    return unique

# ─────────────────────────────────────────────────────────────────────────────
# 7. FLOW 1 — FETCH RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_rss_articles():
    """Fetch up to ARTICLES_PER_SOURCE articles from each RSS feed."""
    articles = []
    for feed_info in RSS_FEEDS:
        source = feed_info["source"]
        url    = feed_info["url"]
        try:
            print(f"  [RSS] {source} ...")
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= ARTICLES_PER_SOURCE:
                    break
                link    = entry.get("link", "").strip()
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                # Strip HTML tags from summary
                summary = re.sub(r"<[^>]+>", "", summary).strip()
                if link and title:
                    articles.append({
                        "url":      link,
                        "title":    title,
                        "summary":  summary[:600],
                        "source":   source,
                        "flow":     "RSS",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error fetching {source}: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 8. FLOW 2 — GOOGLE NEWS RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_google_news_articles():
    """Fetch top articles from Google News RSS for each topic."""
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
                title = entry.get("title", "").strip()
                # Google News titles sometimes include source at end " - Source"
                title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
                if link and title:
                    articles.append({
                        "url":      link,
                        "title":    title,
                        "summary":  entry.get("summary", "").strip()[:600],
                        "source":   f"GoogleNews-{topic[:20]}",
                        "flow":     "GoogleNews",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error fetching Google News for '{topic}': {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 9. FLOW 3 — WEB SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_scraped_articles():
    """Scrape article links from target pages."""
    articles = []
    for target in SCRAPE_TARGETS:
        source = target["source"]
        try:
            print(f"  [Scrape] {source} ...")
            resp = requests.get(target["url"], headers=SCRAPE_HEADERS, timeout=15)
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
                # Make absolute URL
                if href.startswith("/"):
                    base = "/".join(target["url"].split("/")[:3])
                    href = base + href
                if href.startswith("http") and len(title) > 10:
                    articles.append({
                        "url":      href,
                        "title":    title,
                        "summary":  "",
                        "source":   source,
                        "flow":     "Scrape",
                    })
                    count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ Error scraping {source}: {e}")
    return articles

# ─────────────────────────────────────────────────────────────────────────────
# 10. GEMINI REWRITE
# ─────────────────────────────────────────────────────────────────────────────

def rewrite_with_gemini(title, summary, category, source):
    """
    Send article info to Gemini 1.5 Flash (free) for rewriting.
    Returns a dict with title, content, tags, excerpt  — or None on failure.
    """
    if not GEMINI_API_KEY:
        print("  ⚠ GEMINI_API_KEY not set — skipping rewrite")
        return None

    prompt = f"""You are a pop culture news writer for AffanMarvel — a site covering Marvel, DC, Anime, and Movies.

Write a NEWS BLOG POST based on this article info:

Original Title : {title}
Category       : {category}
Source Summary : {summary if summary else "No summary available — write from the title alone."}

STRICT RULES:
1. Write a new, catchy title — do NOT copy the original.
2. Write EXACTLY 3 short paragraphs:
   - Paragraph 1: What happened / the main news.
   - Paragraph 2: Why it matters / fan reaction / background context.
   - Paragraph 3: What to expect next / closing thought.
3. Total content: 200–280 words only. No padding.
4. Do NOT mention the source website name ({source}).
5. End paragraph 3 with one engaging question for readers.
6. Wrap each paragraph in <p> HTML tags.

Return ONLY valid JSON (no markdown, no backticks, no extra text):
{{
  "title": "Your new catchy title here",
  "content": "<p>Paragraph 1 here.</p><p>Paragraph 2 here.</p><p>Paragraph 3 here.</p>",
  "excerpt": "One sentence summary of the post (max 25 words).",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.75,
            "maxOutputTokens": 1024,
            "topP":            0.9,
        },
    }

    try:
        resp = requests.post(api_url, json=payload, timeout=40)
        resp.raise_for_status()
        raw  = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown fences if Gemini adds them
        raw  = re.sub(r"```json\s*|```", "", raw).strip()
        data = json.loads(raw)

        # Validate required keys
        for key in ("title", "content", "excerpt", "tags"):
            if key not in data:
                raise ValueError(f"Missing key '{key}' in Gemini response")

        return data

    except json.JSONDecodeError as e:
        print(f"  ⚠ Gemini JSON parse error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Gemini API request error: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ Gemini unexpected error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 11. WORDPRESS — GET CATEGORY ID BY NAME
# ─────────────────────────────────────────────────────────────────────────────

_category_id_cache = {}   # Avoid repeated API calls for same category name

def get_wp_category_id(category_name):
    """Query WordPress REST API to get a category ID by name. Returns 1 (uncategorized) on failure."""
    if category_name in _category_id_cache:
        return _category_id_cache[category_name]

    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            params={"search": category_name, "per_page": 5},
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            # Find exact name match first, else take first result
            for cat in data:
                if cat.get("name", "").lower() == category_name.lower():
                    _category_id_cache[category_name] = cat["id"]
                    return cat["id"]
            _category_id_cache[category_name] = data[0]["id"]
            return data[0]["id"]
    except Exception as e:
        print(f"  ⚠ Could not get category ID for '{category_name}': {e}")

    _category_id_cache[category_name] = 1  # fallback = uncategorized
    return 1

# ─────────────────────────────────────────────────────────────────────────────
# 12. WORDPRESS — GET OR CREATE TAGS
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_tag_ids(tag_names):
    """Return a list of WordPress tag IDs, creating tags that don't exist."""
    tag_ids = []
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        try:
            # Search first
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
                # Create new tag
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
    """
    Create a DRAFT post in WordPress.
    Returns the WordPress post URL on success, None on failure.
    """
    cat_id  = get_wp_category_id(category)
    tag_ids = get_or_create_tag_ids(tags)

    post_body = {
        "title":      title,
        "content":    content,
        "excerpt":    excerpt,
        "status":     "draft",          # ← DRAFT, not published
        "categories": [cat_id],
        "tags":       tag_ids,
        "meta": {
            "source_url": source_url,   # Store original URL for reference
        },
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
            link = post.get("link", "")
            print(f"  ✓ Draft created → ID {post.get('id')} | {link}")
            return link
        else:
            print(f"  ✗ WordPress error {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  ✗ WordPress request error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 14. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def validate_config():
    """Check that all required environment variables are set."""
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not WP_URL:
        missing.append("WP_URL")
    if not WP_USERNAME:
        missing.append("WP_USERNAME")
    if not WP_APP_PASSWORD:
        missing.append("WP_APP_PASSWORD")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Add them as GitHub Secrets in your repository settings."
        )

def main():
    print("\n" + "=" * 60)
    print(f"  AffanMarvel Auto-Poster — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 0: Validate config
    validate_config()
    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)} URLs tracked\n")

    # ── COLLECT from all 3 flows ──────────────────────────────────────────
    all_raw = []

    print("━━━ FLOW 1: RSS FEEDS ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    rss_articles = fetch_rss_articles()
    print(f"  Subtotal: {len(rss_articles)} articles from RSS\n")
    all_raw.extend(rss_articles)

    print("━━━ FLOW 2: GOOGLE NEWS ━━━━━━━━━━━━━━━━━━━━━━━━━")
    gn_articles = fetch_google_news_articles()
    print(f"  Subtotal: {len(gn_articles)} articles from Google News\n")
    all_raw.extend(gn_articles)

    print("━━━ FLOW 3: WEB SCRAPING ━━━━━━━━━━━━━━━━━━━━━━━━")
    sc_articles = fetch_scraped_articles()
    print(f"  Subtotal: {len(sc_articles)} articles from Scraping\n")
    all_raw.extend(sc_articles)

    print(f"📦 Total raw collected : {len(all_raw)}")

    # ── DEDUPLICATE ───────────────────────────────────────────────────────
    unique = deduplicate_articles(all_raw, posted_urls)
    print(f"✅ After deduplication : {len(unique)} unique articles")

    if not unique:
        print("\n😴 No new articles found. All caught up! Exiting.\n")
        return

    # Limit to MAX_TO_REWRITE to stay within Gemini free tier
    to_process = unique[:MAX_TO_REWRITE]
    print(f"🚀 Processing         : {len(to_process)} articles this run\n")

    # ── REWRITE + DRAFT ───────────────────────────────────────────────────
    success_count = 0
    fail_count    = 0

    for i, article in enumerate(to_process, 1):
        print(f"─── Article {i}/{len(to_process)} ─────────────────────────────")
        print(f"  Title  : {article['title'][:80]}")
        print(f"  Source : {article['source']} [{article['flow']}]")
        print(f"  URL    : {article['url'][:80]}")

        # Detect category
        category = detect_category(article["title"], article.get("summary", ""))
        print(f"  Category detected: {category}")

        # Rewrite with Gemini
        print("  ✍  Rewriting with Gemini...")
        rewritten = rewrite_with_gemini(
            title    = article["title"],
            summary  = article.get("summary", ""),
            category = category,
            source   = article["source"],
        )

        if rewritten is None:
            print("  ✗ Gemini rewrite failed — skipping this article")
            fail_count += 1
            time.sleep(3)
            continue

        print(f"  New title: {rewritten['title'][:70]}")

        # Post as WordPress DRAFT
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

        # Delay between Gemini calls to respect free tier rate limits
        if i < len(to_process):
            print("  ⏳ Waiting 5s before next article...")
            time.sleep(5)

    # ── SUMMARY ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  ✅ Run complete!")
    print(f"  Published as draft : {success_count}")
    print(f"  Failed / skipped   : {fail_count}")
    print(f"  Check WordPress    : {WP_URL}/wp-admin/edit.php?post_status=draft")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
