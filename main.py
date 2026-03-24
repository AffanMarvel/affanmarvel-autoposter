import os
import re
import json
import time
import difflib
import requests
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
POSTED_FILE  = "posted_urls.txt"
OUTPUT_FILE  = "articles.json"
MAX_TO_REWRITE = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
}

# ─── RSS FEEDS (5 articles each) ─────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "https://www.cbr.com/feed/",                    "source": "CBR",              "count": 5},
    {"url": "https://heroichollywood.com/feed/",            "source": "HeroicHollywood",  "count": 5},
    {"url": "https://www.superherohype.com/feed",           "source": "SuperheroHype",    "count": 5},
    {"url": "https://wegotthiscovered.com/feed/",           "source": "WeGotThisCovered", "count": 5},
    {"url": "https://discussingfilm.net/feed/",             "source": "DiscussingFilm",   "count": 5},
    {"url": "https://comicbook.com/feed/",                  "source": "ComicBook",        "count": 5},
    {"url": "https://screenrant.com/feed/",                 "source": "ScreenRant",       "count": 5},
    {"url": "https://collider.com/feed/",                   "source": "Collider",         "count": 5},
    {"url": "https://movieweb.com/feed/",                   "source": "MovieWeb",         "count": 5},
    {"url": "https://deadline.com/feed/",                   "source": "Deadline",         "count": 5},
    {"url": "https://www.themarysue.com/feed/",             "source": "TheMARySue",       "count": 5},
    {"url": "https://www.polygon.com/rss/index.xml",        "source": "Polygon",          "count": 5},
    {"url": "https://www.animenewsnetwork.com/all/rss.xml", "source": "AnimeNewsNetwork", "count": 5},
    {"url": "https://animeuknews.net/feed/",                "source": "AnimeUKNews",      "count": 5},
]

# ─── GOOGLE NEWS SEARCHES (gets TheDirect + more) ────────────────────────────
# TheDirect blocks RSS but Google News indexes it — this gets their articles!

GOOGLE_NEWS_SEARCHES = [
    # TheDirect specific — gets 10 articles from TheDirect
    {"query": "site:thedirect.com marvel dc anime",          "count": 5, "source": "TheDirect"},
    {"query": "site:thedirect.com movies superhero trailer", "count": 5, "source": "TheDirect"},
    # General pop culture
    {"query": "MCU Marvel latest news 2026",                 "count": 5, "source": "GoogleNews"},
    {"query": "DC Comics Superman Batman 2026",              "count": 5, "source": "GoogleNews"},
    {"query": "Anime new season spring 2026",                "count": 5, "source": "GoogleNews"},
]

CATEGORY_KEYWORDS = {
    "Marvel": ["marvel", "avengers", "iron man", "captain america", "thor",
               "spider-man", "wolverine", "x-men", "mcu", "deadpool",
               "black panther", "guardians", "loki", "wanda", "fantastic four"],
    "DC":     ["dc comics", "dc universe", "batman", "superman", "wonder woman",
               "flash", "aquaman", "joker", "justice league", "supergirl",
               "black adam", "shazam", "dcu", "james gunn"],
    "Anime":  ["anime", "manga", "demon slayer", "jujutsu", "naruto", "one piece",
               "attack on titan", "dragon ball", "bleach", "my hero academia",
               "chainsaw man", "isekai", "crunchyroll"],
    "Movies": ["movie", "film", "trailer", "box office", "cinema", "release date",
               "director", "cast", "sequel", "prequel", "reboot", "streaming"],
    "Comics": ["comic", "issue", "graphic novel", "variant", "writer", "artist", "publisher"],
}

SKIP_WORDS = ["logo", "icon", "favicon", "avatar", "1x1", "pixel", "placeholder", "banner", "ad-"]


def detect_category(title, summary=""):
    text = (title + " " + summary).lower()
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"


def is_good_image(url):
    if not url:
        return False
    url_lower = url.lower()
    if any(w in url_lower for w in SKIP_WORDS):
        return False
    has_ext = any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"])
    is_cdn  = any(cdn in url_lower for cdn in ["images", "media", "cdn", "img", "photo", "wp-content", "upload"])
    return has_ext or is_cdn


def get_image_from_entry(entry):
    for mc in entry.get("media_content", []):
        url = mc.get("url", "")
        if url and is_good_image(url):
            return url
    for mt in entry.get("media_thumbnail", []):
        url = mt.get("url", "")
        if url and is_good_image(url):
            return url
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", ""):
            url = enc.get("href", enc.get("url", ""))
            if url:
                return url
    html = ""
    if entry.get("content"):
        html = entry["content"][0].get("value", "")
    if not html:
        html = entry.get("summary", "")
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and src.startswith("http") and is_good_image(src):
                return src
    return ""


def scrape_article(url):
    result = {"content": "", "image_url": ""}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code != 200:
            return result
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content", "").startswith("http"):
            img = og["content"].strip()
            if is_good_image(img):
                result["image_url"] = img
        if not result["image_url"]:
            tw = soup.find("meta", attrs={"name": "twitter:image"})
            if tw and tw.get("content", "").startswith("http"):
                result["image_url"] = tw["content"].strip()
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "iframe", "noscript", "form"]):
            tag.decompose()
        selectors = [".entry-content", ".post-content", ".article-body",
                     ".story-body", ".article__body", "article", "main"]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                paras = el.find_all(["p", "h2", "h3", "li"])
                text  = " ".join(
                    p.get_text(strip=True) for p in paras
                    if len(p.get_text(strip=True)) > 30
                )
                if len(text) > 200:
                    result["content"] = text[:4000]
                    break
    except Exception as e:
        print("  Scrape error: " + str(e))
    return result


def load_posted_urls():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(l.strip() for l in f if l.strip() and not l.startswith("#"))


def save_posted_url(url):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")


def titles_are_similar(t1, t2, threshold=0.72):
    return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio() >= threshold


def deduplicate(articles, posted_urls):
    seen   = []
    unique = []
    for art in articles:
        url   = art.get("url", "").strip()
        title = art.get("title", "").strip()
        if not url or not title:
            continue
        if url in posted_urls:
            continue
        if any(titles_are_similar(title, t) for t in seen):
            continue
        unique.append(art)
        seen.append(title)
    return unique


def fetch_rss():
    articles = []
    for fi in RSS_FEEDS:
        try:
            print("  [RSS] " + fi["source"] + " ...")
            feed  = feedparser.parse(fi["url"])
            count = 0
            for e in feed.entries:
                if count >= fi["count"]:
                    break
                link    = e.get("link", "").strip()
                title   = e.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()
                if not link or not title:
                    continue
                image_url = get_image_from_entry(e)
                articles.append({
                    "url":       link,
                    "title":     title,
                    "summary":   summary[:800],
                    "source":    fi["source"],
                    "image_url": image_url,
                })
                count += 1
            print("     -> " + str(count) + " articles")
        except Exception as e:
            print("     error: " + str(e))
    return articles


def fetch_google_news():
    articles = []
    for search in GOOGLE_NEWS_SEARCHES:
        try:
            query   = requests.utils.quote(search["query"])
            url     = "https://news.google.com/rss/search?q=" + query + "&hl=en-US&gl=US&ceid=US:en"
            source  = search["source"]
            count_limit = search["count"]
            print("  [GNews] " + search["query"][:50] + " ...")
            feed  = feedparser.parse(url)
            count = 0
            for e in feed.entries:
                if count >= count_limit:
                    break
                link  = e.get("link", "").strip()
                title = re.sub(r"\s*-\s*[^-]+$", "", e.get("title", "")).strip()
                if not link or not title or len(title) < 10:
                    continue
                # For TheDirect searches, only keep TheDirect articles
                if "thedirect.com" in search["query"]:
                    if "thedirect.com" not in link:
                        continue
                articles.append({
                    "url":       link,
                    "title":     title,
                    "summary":   e.get("summary", "")[:800],
                    "source":    source,
                    "image_url": "",
                })
                count += 1
            print("     -> " + str(count) + " articles")
        except Exception as e:
            print("     error: " + str(e))
    return articles


def rewrite_with_groq(title, summary, full_content, category, source):
    if full_content:
        source_text = full_content[:2500]
    elif summary:
        source_text = summary
    else:
        source_text = ""

    prompt = (
        "You are a senior entertainment journalist writing for AffanMarvel, "
        "a professional pop culture website covering Marvel, DC, Anime, and Movies.\n\n"
        "Original Title: " + title + "\n"
        "Category: " + category + "\n"
        "Source Material: " + (source_text if source_text else "Write a detailed article based on the title only.") + "\n\n"
        "WRITING REQUIREMENTS:\n"
        "1. Write between 1500 and 2000 words\n"
        "2. Write like a professional journalist at IGN or Screen Rant\n"
        "3. Structure with these HTML sections:\n"
        "   - Opening hook paragraph with no heading\n"
        "   - <h2>Background and Context</h2> with 2 to 3 paragraphs\n"
        "   - <h2>Breaking Down the News</h2> with 2 to 3 paragraphs\n"
        "   - <h2>Why This Matters</h2> with 2 paragraphs\n"
        "   - <h2>Fan Reactions</h2> with 2 paragraphs\n"
        "   - <h2>A Deeper Look</h2> with 2 paragraphs\n"
        "   - <h2>What to Expect Next</h2> with 2 paragraphs and ending question\n"
        "4. Each paragraph must be 80 to 150 words\n"
        "5. Use specific character names, actor names, dates where possible\n"
        "6. Do NOT mention the source website " + source + "\n"
        "7. Make it feel like original professional reporting\n\n"
        "Return ONLY this JSON with no markdown and no backticks:\n"
        "{\"title\": \"Your compelling headline\", "
        "\"content\": \"<p>Hook...</p><h2>Background and Context</h2><p>...</p><p>...</p>"
        "<h2>Breaking Down the News</h2><p>...</p><p>...</p>"
        "<h2>Why This Matters</h2><p>...</p><p>...</p>"
        "<h2>Fan Reactions</h2><p>...</p><p>...</p>"
        "<h2>A Deeper Look</h2><p>...</p><p>...</p>"
        "<h2>What to Expect Next</h2><p>...</p><p>...question?</p>\", "
        "\"excerpt\": \"One sentence summary under 30 words.\", "
        "\"tags\": [\"tag1\", \"tag2\", \"tag3\", \"tag4\", \"tag5\"], "
        "\"seo_keyword\": \"3 to 5 word keyword phrase\", "
        "\"seo_description\": \"Meta description between 140 and 155 characters.\"}"
    )

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + GROQ_API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.75,
                    "max_tokens": 4096
                },
                timeout=90
            )
            if resp.status_code == 429:
                print("  Rate limit - waiting 40s")
                time.sleep(40)
                continue
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            raw = re.sub(r"```json\s*", "", raw)
            raw = re.sub(r"```", "", raw)
            raw = raw.strip()
            m   = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
            raw  = re.sub(r"[\x00-\x1f\x7f]", " ", raw)
            data = json.loads(raw)
            for k in ("title", "content", "excerpt", "tags"):
                if k not in data:
                    raise ValueError("Missing key: " + k)
            if "seo_keyword" not in data:
                data["seo_keyword"] = data["tags"][0] if data.get("tags") else title[:40]
            if "seo_description" not in data:
                data["seo_description"] = data.get("excerpt", "")[:155]
            return data
        except Exception as e:
            print("  Groq attempt " + str(attempt + 1) + " error: " + str(e))
            if attempt < 2:
                time.sleep(5)
    return None


def main():
    print("=" * 60)
    print("  AffanMarvel Auto-Poster")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if not GROQ_API_KEY:
        raise EnvironmentError("Missing GROQ_API_KEY secret!")

    posted_urls = load_posted_urls()
    print("Already posted: " + str(len(posted_urls)))

    print("\n--- Fetching RSS Feeds ---")
    rss_articles = fetch_rss()
    print("RSS total: " + str(len(rss_articles)))

    print("\n--- Fetching Google News (includes TheDirect) ---")
    gn_articles = fetch_google_news()
    print("Google News total: " + str(len(gn_articles)))

    # Count TheDirect articles specifically
    thedirect_count = sum(1 for a in gn_articles if a.get("source") == "TheDirect")
    print("TheDirect articles: " + str(thedirect_count))

    all_raw    = rss_articles + gn_articles
    unique     = deduplicate(all_raw, posted_urls)
    to_process = unique[:MAX_TO_REWRITE]

    print("\nTotal raw: " + str(len(all_raw)))
    print("Unique: " + str(len(unique)))
    print("Processing: " + str(len(to_process)))

    if not to_process:
        print("No new articles found.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": str(datetime.now()),
                "count": 0,
                "articles": []
            }, f)
        return

    results = []

    for i, art in enumerate(to_process, 1):
        print("\n--- Article " + str(i) + "/" + str(len(to_process)) + " [" + art.get("source","") + "]")
        print("  Title: " + art["title"][:70])

        category = detect_category(art["title"], art.get("summary", ""))
        print("  Category: " + category)

        print("  Scraping article page...")
        scraped      = scrape_article(art["url"])
        image_url    = art.get("image_url", "") or scraped.get("image_url", "")
        full_content = scraped.get("content", "")

        print("  Image: " + ("found" if image_url else "none"))
        print("  Content: " + str(len(full_content)) + " chars")
        print("  Writing article...")

        rewritten = rewrite_with_groq(
            art["title"],
            art.get("summary", ""),
            full_content,
            category,
            art.get("source", "")
        )

        if not rewritten:
            print("  Skipped")
            time.sleep(3)
            continue

        word_count = len(re.sub(r"<[^>]+>", "", rewritten["content"]).split())
        print("  Done: " + str(word_count) + " words")

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

        if i < len(to_process):
            time.sleep(4)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": str(datetime.now()),
            "count":        len(results),
            "articles":     results,
        }, f, ensure_ascii=False, indent=2)

    with_img = sum(1 for r in results if r.get("image_url"))
    thedirect_saved = sum(1 for r in results if "thedirect" in r.get("source_url",""))
    print("\n" + "=" * 60)
    print("  Saved: " + str(len(results)) + " articles")
    print("  TheDirect articles: " + str(thedirect_saved))
    print("  With images: " + str(with_img) + "/" + str(len(results)))
    print("=" * 60)


if __name__ == "__main__":
    main()
