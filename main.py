def resolve_final_url(url):
    # Function to resolve Google News RSS redirect and strip tracking parameters
    import requests
    from urllib.parse import urlparse, parse_qs
    session = requests.Session()
    response = session.get(url)
    final_url = response.url

    # Strip tracking parameters
    parsed_url = urlparse(final_url)
    query_params = parse_qs(parsed_url.query)
    stripped_query = {key: value for key, value in query_params.items() if key not in ['utm_source', 'utm_medium', 'utm_campaign']}
    final_url = parsed_url._replace(query='').geturl() + '?' + '&'.join([f'{key}={value[0]}' for key, value in stripped_query.items()]) if stripped_query else final_url

    return final_url


def fetch_google_news():
    # Your existing implementation, modified to use resolve_final_url
    ...   # Previous code
    for entry in entries:
        url = entry['link']
        final_url = resolve_final_url(url)
        article['url'] = final_url
        article['raw_url'] = url
        if should_filter_article(article):
            continue
    


def scrape_article(article):
    # Updated to use requests.Session and headers
    session = requests.Session()
    headers = { 'Accept-Language': 'en-US,en;q=0.9', 'Referer': 'http://example.com' }
    response = session.get(article['url'], headers=headers)

    # Fallback extraction logic
    content = ''
    if 'application/ld+json' in response.headers.get('Content-Type', ''):
        # Parse JSON-LD
        ... # Existing JSON-LD extraction logic
    elif not content:
        # Fallback to meta description
        content = extract_meta_description(response.text)
        
    # Capture og:image/twitter:image
    og_image = extract_og_image(response.text)
    article['og_image'] = og_image


# Main processing loop
posted_urls = set()
for art in articles:
    resolved_url = art['url']
    raw_url = art['raw_url']
    save_posted_url(resolved_url)
    if raw_url:
        posted_urls.add(raw_url)

    # Deduplicate check
    if resolved_url in posted_urls or raw_url in posted_urls:
        continue