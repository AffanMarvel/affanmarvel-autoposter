"""
AffanMarvel Auto-Poster — RSS MEDIA IMAGE VERSION
==================================================
Gets REAL article images from RSS feed media tags
No fallback logos — only real article images!
"""
import os, re, json, time, difflib, requests, feedparser
from datetime import datetime
from bs4 import BeautifulSoup

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
POSTED_FILE  = "posted_urls.txt"
OUTPUT_FILE  = "articles.json"
ARTICLES_PER_SOURCE = 10
MAX_TO_REWRITE = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# ─── RSS FEEDS ────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "https://thedirect.com/feed",       "source": "TheDirect"},
    {"url": "https://www.cbr.com/feed/",         "source": "CBR"},
    {"url": "https://comicbook.com/feed/",       "source": "ComicBook"},
    {"url": "https://screenrant.com/feed/",      "source": "ScreenRant"},
    {"url": "https://heroichollywood.com/feed/", "source": "HeroicHollywood"},
    {"url": "https://www.themarysue.com/feed/",  "source": "TheMARySue"},
]

# ─── CATEGORY DETECTION ───────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Marvel": ["marvel","avengers","iron man","captain america","thor","spider-man","wolverine","x-men","mcu","deadpool","black panther","guardians","loki","wanda","fantastic four"],
    "DC":     ["dc comics","dc universe","batman","superman","wonder woman","flash","aquaman","joker","justice league","supergirl","black adam","shazam","dcu","james gunn"],
    "Anime":  ["anime","manga","demon slayer","jujutsu","naruto","one piece","attack on titan","dragon ball","bleach","my hero academia","chainsaw man","isekai","crunchyroll"],
    "Movies": ["movie","film","trailer","box office","cinema","release date","director","cast","sequel","prequel","reboot"],
    "Comics": ["comic","issue","graphic novel","variant","writer","artist","publisher"],
}

def detect_category(title, summary=""):
    text = (title + " " + summary).lower()
    scores = {cat: sum(1 for kw in kws if kw in text) for cat, kws in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"

# ─── GET IMAGE FROM RSS ENTRY ─────────────────────────────────────────────────

def get_image_from_rss_entry(entry):
    """Extract real article image from RSS entry media tags."""

    # Method 1: media:content (most common in news RSS feeds)
    media_content = entry.get("media_content", [])
    for mc in media_content:
        url = mc.get("url", "")
        if url and is_valid_image(url):
            return url

    # Method 2: media:thumbnail
    media_thumb = entry.get("media_thumbnail", [])
    for mt in media_thumb:
        url = mt.get("url", "")
        if url and is_valid_image(url):
            return url

    # Method 3: enclosures (podcasts/image RSS format)
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", ""):
            url = enc.get("href", enc.get("url", ""))
            if url and is_valid_image(url):
                return url

    # Method 4: parse HTML content/summary for img tags
    content = ""
    if entry.get("content"):
        content = entry["content"][0].get("value", "")
    if not content:
        content = entry.get("summary", "")

    if content:
        soup = BeautifulSoup(content, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and is_valid_image(src) and src.startswith("http"):
                return src

    return ""

def is_valid_image(url):
    """Check if URL looks like a real content image (not logo/icon)."""
    url_lower = url.lower()
    # Must be an image file
    if not any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
        # Some URLs don't have extensions but are still images
        if "image" not in url_lower and "photo" not in url_lower and "img" not in url_lower:
            return False
    # Skip logos, icons, avatars
    skip_words = ["logo", "icon", "favicon", "avatar", "1x1", "pixel",
                  "placeholder", "spinner", "loading", "blank", "spacer"]
    if any(word in url_lower for word in skip_words):
        return False
    return True

def scrape_og_image(url):
    """Fetch article page and get og:image as fallback."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # og:image
        og = soup.find("meta", property="og:image")
        if og:
            img = og.get("content", "").strip()
            if img.startswith("http") and is_valid_image(img):
                return img

        # twitter:image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw:
            img = tw.get("content", "").strip()
            if img.startswith("http") and is_valid_image(img):
                return img

    except Exception as e:
        print(f"  ⚠ og:image error: {e}")
    return ""

# ─── DEDUPLICATION ────────────────────────────────────────────────────────────

def load_posted_urls():
    if not os.path.exists(POSTED_FILE): return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(l.strip() for l in f if l.strip() and not l.startswith("#"))

def save_posted_url(url):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")

def titles_are_similar(t1, t2, threshold=0.72):
    return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio() >= threshold

def deduplicate(articles, posted_urls):
    seen, unique = [], []
    for art in articles:
        url, title = art.get("url","").strip(), art.get("title","").strip()
        if not url or not title or url in posted_urls: continue
        if any(titles_are_similar(title, t) for t in seen): continue
        unique.append(art); seen.append(title)
    return unique

# ─── FETCH RSS + IMAGES ───────────────────────────────────────────────────────

def fetch_rss():
    articles = []
    for fi in RSS_FEEDS:
        try:
            print(f"  [RSS] {fi['source']} ...")
            feed  = feedparser.parse(fi["url"])
            count = 0
            for e in feed.entries:
                if count >= ARTICLES_PER_SOURCE: break
                link    = e.get("link", "").strip()
                title   = e.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()
                if not link or not title: continue

                # Get image from RSS entry first (fastest + most accurate)
                image_url = get_image_from_rss_entry(e)

                articles.append({
                    "url":       link,
                    "title":     title,
                    "summary":   summary[:500],
                    "source":    fi["source"],
                    "image_url": image_url,  # Store immediately from RSS
                })
                count += 1
            print(f"     → {count} articles, images from RSS: {sum(1 for a in articles[-count:] if a['image_url'])}/{count}")
        except Exception as e:
            print(f"     ⚠ {e}")
    return articles

# ─── GROQ REWRITE ─────────────────────────────────────────────────────────────

def rewrite_with_groq(title, summary, category):
    prompt = f"""Pop culture news writer for AffanMarvel.
Title: {title}
Category: {category}
Summary: {summary or "Write from title only."}
Return ONLY valid JSON no markdown:
{{"title":"catchy title","content":"<p>para1</p><p>para2</p><p>para3 ending with question?</p>","excerpt":"one sentence under 25 words","tags":["t1","t2","t3","t4","t5"],"seo_keyword":"3-5 word phrase","seo_description":"140-155 char meta"}}"""

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 700},
                timeout=30
            )
            if resp.status_code == 429:
                print("  ⏳ Rate limit — waiting 30s")
                time.sleep(30); continue
            resp.raise_for_status()
            raw  = resp.json()["choices"][0]["message"]["content"]
            raw  = re.sub(r"```json\s*|```", "", raw).strip()
            m    = re.search(r"\{.*\}", raw, re.DOTALL)
            if m: raw = m.group(0)
            raw  = re.sub(r'[\x00-\x1f\x7f]', ' ', raw)
            data = json.loads(raw)
            for k in ("title", "content", "excerpt", "tags"):
                if k not in data: raise ValueError(f"Missing {k}")
            data.setdefault("seo_keyword", data["tags"][0] if data.get("tags") else title[:40])
            data.setdefault("seo_description", data.get("excerpt", "")[:155])
            return data
        except Exception as e:
            print(f"  ⚠ Groq attempt {attempt+1}: {e}")
            if attempt < 2: time.sleep(5)
    return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print(f"  AffanMarvel — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    if not GROQ_API_KEY:
        raise EnvironmentError("Missing GROQ_API_KEY!")

    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)}\n")

    print("━━━ FETCHING RSS FEEDS ━━━━━━━━━━━━━━━━━━━━━━━━━━")
    all_raw = fetch_rss()
    unique     = deduplicate(all_raw, posted_urls)
    to_process = unique[:MAX_TO_REWRITE]
    print(f"\n📦 Total: {len(all_raw)} | Unique: {len(unique)} | Processing: {len(to_process)}\n")

    if not to_process:
        print("😴 No new articles.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({"generated_at": str(datetime.now()), "count": 0, "articles": []}, f)
        return

    results = []
    for i, art in enumerate(to_process, 1):
        print(f"─── {i}/{len(to_process)}: {art['title'][:70]}")
        category = detect_category(art["title"], art.get("summary", ""))
        print(f"  Category : {category}")

        # Use image from RSS if found, else try scraping og:image
        image_url = art.get("image_url", "")
        if image_url:
            print(f"  ✓ Image from RSS: {image_url[:60]}")
        else:
            print(f"  🔍 No RSS image — scraping og:image...")
            image_url = scrape_og_image(art["url"])
            if image_url:
                print(f"  ✓ og:image found: {image_url[:60]}")
            else:
                print(f"  ⚠ No image found for this article")

        print(f"  ✍ Rewriting...")
        rewritten = rewrite_with_groq(art["title"], art.get("summary", ""), category)
        if not rewritten:
            print("  ✗ Skipped")
            time.sleep(3)
            continue

        print(f"  ✓ {rewritten['title'][:60]}")

        results.append({
            "title":           rewritten["title"],
            "content":         rewritten["content"],
            "excerpt":         rewritten["excerpt"],
            "tags":            rewritten.get("tags", []),
            "category":        category,
            "source_url":      art["url"],
            "image_url":       image_url,
            "seo_keyword":     rewritten.get("seo_keyword", ""),
            "seo_description": rewritten.get("seo_description", ""),
        })
        save_posted_url(art["url"])
        if i < len(to_process): time.sleep(3)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": str(datetime.now()),
            "count":        len(results),
            "articles":     results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved {len(results)} articles with REAL images!")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
