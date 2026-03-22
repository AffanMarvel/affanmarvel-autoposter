"""
AffanMarvel Auto-Poster — FULL CONTENT VERSION
===============================================
Scrapes full article content + writes detailed professional posts
"""
import os, re, json, time, difflib, requests, feedparser
from datetime import datetime
from bs4 import BeautifulSoup

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
POSTED_FILE  = "posted_urls.txt"
OUTPUT_FILE  = "articles.json"
ARTICLES_PER_SOURCE = 5
MAX_TO_REWRITE = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

RSS_FEEDS = [
    {"url": "https://thedirect.com/feed",                       "source": "TheDirect"},
    {"url": "https://www.cbr.com/feed/",                        "source": "CBR"},
    {"url": "https://heroichollywood.com/feed/",                "source": "HeroicHollywood"},
    {"url": "https://www.superherohype.com/feed",               "source": "SuperheroHype"},
    {"url": "https://wegotthiscovered.com/feed/",               "source": "WeGotThisCovered"},
    {"url": "https://discussingfilm.net/feed/",                 "source": "DiscussingFilm"},
    {"url": "https://comicbook.com/feed/",                      "source": "ComicBook"},
    {"url": "https://screenrant.com/feed/",                     "source": "ScreenRant"},
    {"url": "https://collider.com/feed/",                       "source": "Collider"},
    {"url": "https://movieweb.com/feed/",                       "source": "MovieWeb"},
    {"url": "https://deadline.com/feed/",                       "source": "Deadline"},
    {"url": "https://www.themarysue.com/feed/",                 "source": "TheMARySue"},
    {"url": "https://www.polygon.com/rss/index.xml",            "source": "Polygon"},
    {"url": "https://www.animenewsnetwork.com/all/rss.xml",     "source": "AnimeNewsNetwork"},
    {"url": "https://animeuknews.net/feed/",                    "source": "AnimeUKNews"},
]

CATEGORY_KEYWORDS = {
    "Marvel":  ["marvel","avengers","iron man","captain america","thor","spider-man","wolverine","x-men","mcu","deadpool","black panther","guardians","loki","wanda","fantastic four","visionquest"],
    "DC":      ["dc comics","dc universe","batman","superman","wonder woman","flash","aquaman","joker","justice league","supergirl","black adam","shazam","dcu","james gunn","penguin"],
    "Anime":   ["anime","manga","demon slayer","jujutsu","naruto","one piece","attack on titan","dragon ball","bleach","my hero academia","chainsaw man","isekai","crunchyroll"],
    "Movies":  ["movie","film","trailer","box office","cinema","release date","director","cast","sequel","prequel","reboot","streaming"],
    "Comics":  ["comic","issue","graphic novel","variant","writer","artist","publisher"],
}

def detect_category(title, summary=""):
    text = (title + " " + summary).lower()
    scores = {cat: sum(1 for kw in kws if kw in text) for cat, kws in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Pop Culture"

# ─── SCRAPE FULL ARTICLE CONTENT ─────────────────────────────────────────────

def scrape_full_article(url):
    """Scrape the full article text and og:image from source URL."""
    result = {"content": "", "image_url": ""}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code != 200:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # Get og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content","").startswith("http"):
            img = og["content"].strip()
            skip = ["logo","icon","favicon","1x1","pixel","banner","ad-"]
            if not any(s in img.lower() for s in skip):
                result["image_url"] = img

        # Try twitter:image if no og:image
        if not result["image_url"]:
            tw = soup.find("meta", attrs={"name":"twitter:image"})
            if tw and tw.get("content","").startswith("http"):
                result["image_url"] = tw["content"].strip()

        # Remove unwanted elements
        for tag in soup(["script","style","nav","header","footer",
                         "aside","iframe","noscript","form",
                         "button","ads","advertisement"]):
            tag.decompose()

        # Find main article body
        article_text = ""
        selectors = [
            "article .entry-content",
            "article .post-content",
            "article .content",
            ".article-body",
            ".post-body",
            ".entry-content",
            ".article__body",
            ".story-body",
            "article",
            "main",
        ]

        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                # Get all paragraphs
                paras = el.find_all(["p","h2","h3","h4","li"])
                text  = " ".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 30)
                if len(text) > 200:
                    article_text = text[:3000]
                    break

        result["content"] = article_text

    except Exception as e:
        print(f"  ⚠ Scrape error: {e}")

    return result

# ─── IMAGE FROM RSS ENTRY ─────────────────────────────────────────────────────

SKIP_WORDS = ["logo","icon","favicon","avatar","1x1","pixel","placeholder","banner","ad-"]

def get_image_from_entry(entry):
    for mc in entry.get("media_content", []):
        url = mc.get("url","")
        if url and not any(w in url.lower() for w in SKIP_WORDS):
            return url
    for mt in entry.get("media_thumbnail", []):
        url = mt.get("url","")
        if url and not any(w in url.lower() for w in SKIP_WORDS):
            return url
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type",""):
            return enc.get("href", enc.get("url",""))
    html = ""
    if entry.get("content"):
        html = entry["content"][0].get("value","")
    if not html:
        html = entry.get("summary","")
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src","") or img.get("data-src","")
            if src and src.startswith("http") and not any(w in src.lower() for w in SKIP_WORDS):
                if any(ext in src.lower() for ext in [".jpg",".jpeg",".png",".webp"]):
                    return src
    return ""

# ─── DEDUPLICATION ────────────────────────────────────────────────────────────

def load_posted_urls():
    if not os.path.exists(POSTED_FILE): return set()
    with open(POSTED_FILE,"r",encoding="utf-8") as f:
        return set(l.strip() for l in f if l.strip() and not l.startswith("#"))

def save_posted_url(url):
    with open(POSTED_FILE,"a",encoding="utf-8") as f:
        f.write(url.strip()+"\n")

def titles_are_similar(t1,t2,threshold=0.72):
    return difflib.SequenceMatcher(None,t1.lower(),t2.lower()).ratio()>=threshold

def deduplicate(articles, posted_urls):
    seen, unique = [], []
    for art in articles:
        url,title = art.get("url","").strip(), art.get("title","").strip()
        if not url or not title or url in posted_urls: continue
        if any(titles_are_similar(title,t) for t in seen): continue
        unique.append(art); seen.append(title)
    return unique

# ─── FETCH RSS ────────────────────────────────────────────────────────────────

def fetch_all_rss():
    articles = []
    for fi in RSS_FEEDS:
        try:
            print(f"  [RSS] {fi['source']} ...")
            feed  = feedparser.parse(fi["url"])
            count = 0
            for e in feed.entries:
                if count >= ARTICLES_PER_SOURCE: break
                link    = e.get("link","").strip()
                title   = e.get("title","").strip()
                summary = re.sub(r"<[^>]+>","",e.get("summary","")).strip()
                if not link or not title: continue
                image_url = get_image_from_entry(e)
                articles.append({
                    "url":       link,
                    "title":     title,
                    "summary":   summary[:800],
                    "source":    fi["source"],
                    "image_url": image_url,
                })
                count += 1
            print(f"     → {count} articles")
        except Exception as e:
            print(f"     ⚠ {e}")
    return articles

# ─── GROQ REWRITE — DETAILED PROFESSIONAL CONTENT ────────────────────────────

def rewrite_with_groq(title, summary, full_content, category, source):
    # Combine summary and scraped content for richer input
    source_text = ""
    if full_content:
        source_text = full_content[:1500]
    elif summary:
        source_text = summary

    prompt = f"""You are a senior pop culture journalist writing for AffanMarvel — a professional entertainment news website covering Marvel, DC, Anime, and Movies.

Write a DETAILED, PROFESSIONAL news article based on this source information:

Original Title: {title}
Category: {category}
Source Content: {source_text if source_text else "Write a detailed article based on the title only."}

STRICT REQUIREMENTS:
1. Write a NEW compelling headline — do NOT copy the original title
2. Write 5-6 detailed paragraphs with proper HTML tags:
   - <h2> for section headings
   - <p> for paragraphs
3. Each paragraph must be 100-150 words minimum
4. Total article: 1000-2000 words — this is MANDATORY
5. Structure with these sections:
   - Opening paragraph (hook the reader)
   - Background & Context (history/details)
   - Main News (what happened in detail)
   - Why It Matters (impact on franchise/fans)
   - Fan Reactions & Community Response
   - Expert Analysis & Deeper Look
   - What To Expect Next
   - Conclusion with reader question
6. Write like a professional entertainment journalist at IGN or Screen Rant
7. Do NOT mention the source website ({source})
8. Use specific details, character names, actor names, dates when available
9. Make it feel like original in-depth reporting

Return ONLY this valid JSON (no markdown, no backticks):
{{"title":"Professional headline here","content":"<p>Hook opening paragraph...</p><h2>Background &#38; Context</h2><p>Detailed background...</p><p>More context...</p><h2>Breaking It Down</h2><p>Main news details...</p><p>More details...</p><h2>Why This Matters</h2><p>Impact analysis...</p><p>More analysis...</p><h2>Fan Reactions</h2><p>Community response...</p><h2>A Deeper Look</h2><p>Expert analysis...</p><p>More insights...</p><h2>What Comes Next</h2><p>Future expectations...</p><p>Final thoughts with question for readers?</p>","excerpt":"One compelling sentence summary under 30 words.","tags":["tag1","tag2","tag3","tag4","tag5"],"seo_keyword":"3-5 word keyword phrase","seo_description":"Compelling meta description exactly 140-155 characters"}}"""

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},
                json={
                    "model":       "llama-3.3-70b-versatile",
                    "messages":    [{"role":"user","content":prompt}],
                    "temperature": 0.75,
                    "max_tokens":  4000,,
                },
                timeout=45
            )
            if resp.status_code == 429:
                print("  ⏳ Rate limit — waiting 30s")
                time.sleep(30); continue
            resp.raise_for_status()
            raw  = resp.json()["choices"][0]["message"]["content"]
            raw  = re.sub(r"```json\s*|```","",raw).strip()
            m    = re.search(r"\{.*\}",raw,re.DOTALL)
            if m: raw = m.group(0)
            raw  = re.sub(r'[\x00-\x1f\x7f]',' ',raw)
            data = json.loads(raw)
            for k in ("title","content","excerpt","tags"):
                if k not in data: raise ValueError(f"Missing {k}")
            data.setdefault("seo_keyword", data["tags"][0] if data.get("tags") else title[:40])
            data.setdefault("seo_description", data.get("excerpt","")[:155])
            return data
        except Exception as e:
            print(f"  ⚠ Groq attempt {attempt+1}: {e}")
            if attempt < 2: time.sleep(5)
    return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("\n"+"="*60)
    print(f"  AffanMarvel Full Content Poster — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    if not GROQ_API_KEY:
        raise EnvironmentError("Missing GROQ_API_KEY!")

    posted_urls = load_posted_urls()
    print(f"\n📋 Already posted: {len(posted_urls)}\n")

    print("━━━ FETCHING RSS FEEDS ━━━━━━━━━━━━━━━━━━━━━━━━━━")
    all_raw    = fetch_all_rss()
    unique     = deduplicate(all_raw, posted_urls)
    to_process = unique[:MAX_TO_REWRITE]
    print(f"\n📦 Total: {len(all_raw)} | Unique: {len(unique)} | Processing: {len(to_process)}\n")

    if not to_process:
        print("😴 No new articles.")
        with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
            json.dump({"generated_at":str(datetime.now()),"count":0,"articles":[]},f)
        return

    results = []
    for i, art in enumerate(to_process, 1):
        print(f"─── {i}/{len(to_process)}: {art['title'][:70]}")
        category = detect_category(art["title"], art.get("summary",""))
        print(f"  Category : {category}")

        # Scrape full article content + image from source
        print(f"  🔍 Scraping full article...")
        scraped = scrape_full_article(art["url"])

        # Use scraped image if RSS had none
        image_url = art.get("image_url","") or scraped.get("image_url","")
        full_content = scraped.get("content","")

        if image_url:
            print(f"  ✓ Image  : {image_url[:60]}")
        else:
            print(f"  ⚠ No image found")

        if full_content:
            print(f"  ✓ Content: {len(full_content)} chars scraped")
        else:
            print(f"  ⚠ No full content — using summary only")

        print(f"  ✍ Writing detailed article with Groq...")
        rewritten = rewrite_with_groq(
            title        = art["title"],
            summary      = art.get("summary",""),
            full_content = full_content,
            category     = category,
            source       = art["source"],
        )

        if not rewritten:
            print("  ✗ Skipped")
            time.sleep(3)
            continue

        word_count = len(rewritten["content"].split())
        print(f"  ✓ Done: {rewritten['title'][:55]} ({word_count} words)")

        results.append({
            "title":           rewritten["title"],
            "content":         rewritten["content"],
            "excerpt":         rewritten["excerpt"],
            "tags":            rewritten.get("tags",[]),
            "category":        category,
            "source_url":      art["url"],
            "image_url":       image_url,
            "seo_keyword":     rewritten.get("seo_keyword",""),
            "seo_description": rewritten.get("seo_description",""),
        })
        save_posted_url(art["url"])
        if i < len(to_process): time.sleep(4)

    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        json.dump({
            "generated_at": str(datetime.now()),
            "count":        len(results),
            "articles":     results,
        }, f, ensure_ascii=False, indent=2)

    with_img = sum(1 for r in results if r.get("image_url"))
    print(f"\n✅ Saved {len(results)} detailed articles!")
    print(f"   With images : {with_img}/{len(results)}")
    print(f"   Using model : llama-3.3-70b-versatile (best quality)")
    print("="*60+"\n")

if __name__ == "__main__":
    main()
