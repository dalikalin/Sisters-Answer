# scrape.py
# This program visits sistersofcode.org, follows the links to the other pages
# on the same website, and saves the text it finds into a file.

import json                                     # lets us save data to a file
import requests                                 # downloads web pages
from bs4 import BeautifulSoup                   # reads the text inside web pages
from urllib.parse import urljoin, urlparse      # helpers for working with links

START_URL = "https://www.sistersofcode.org/"    # the page we start from
DOMAIN = urlparse(START_URL).netloc             # the website name, so we stay on this site
MAX_PAGES = 100                                 # safety limit so it never runs forever
SKIP_WORDS = ["/hashtags/", "/tags/"]           # skip these repeated tag pages

to_visit = [START_URL]   # pages waiting to be visited
visited = set()          # pages we have already visited
pages = []               # the text we collect from each page

while to_visit and len(visited) < MAX_PAGES:
    url = to_visit.pop(0)              # take the next page from the waiting list 
    if url in visited:                 # skip it if we already did it
        continue
    visited.add(url)
    print("Reading:", url)

    # Download the page (if it fails, skip it instead of crashing)
    try:
        response = requests.get(url, timeout=15)
    except requests.RequestException as error:
        print("  Could not load:", error)
        continue

    # Only keep normal web pages (not images or PDFs)
    if response.status_code != 200:
        continue
    if "text/html" not in response.headers.get("Content-Type", ""):
        continue

    soup = BeautifulSoup(response.text, "html.parser")

    # Find every link on the page and add new pages from the same website
    for link in soup.find_all("a", href=True):
        full_link = urljoin(url, link["href"]).split("#")[0]
        # Skip any link that contains one of the SKIP_WORDS
        if any(word in full_link for word in SKIP_WORDS):
            continue
        if urlparse(full_link).netloc == DOMAIN and full_link not in visited:
            to_visit.append(full_link)

    # Remove parts that are not useful text (code, styles, menus, footers)
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Get the clean text and store it with its web address
    text = soup.get_text(separator="\n", strip=True)
    pages.append({"url": url, "text": text})

# Save everything into a file called site_data.json
with open("site_data.json", "w", encoding="utf-8") as file:
    json.dump(pages, file, ensure_ascii=False, indent=2)

print("Done! Saved", len(pages), "pages.")