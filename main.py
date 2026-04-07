def resolve_url(url):
    import requests
    response = requests.head(url, allow_redirects=True)
    return response.url


def fetch_google_news(query):
    import requests
    import urllib.parse
    search_url = f'https://news.google.com/search?q={urllib.parse.quote(query)}'
    response = requests.get(search_url)
    # Following the news.google.com links
    return response.text


HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com'
}


def scrape_article(url):
    import requests
    from bs4 import BeautifulSoup
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Trying to find JSON-LD articleBody
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        data = json_ld.string
        # Parse the JSON-LD to get articleBody
        return data
    else:
        # Fallback to og:description
        og_description = soup.find('meta', property='og:description')
        return og_description['content'] if og_description else None


# Main loop saving posted URL using resolved URL
posted_urls = []
urls_to_scrape = ['https://thedirect.com']
for url in urls_to_scrape:
    resolved_url = resolve_url(url)
    article = scrape_article(resolved_url)
    posted_urls.append(resolved_url)
