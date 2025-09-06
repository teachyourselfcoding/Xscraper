# test_scraper_minimal.py

import os
import sys
import time
import re
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

def expand_show_more(article):
    # Expand all "Show more"/"显示更多" buttons inside the article
    while True:
        buttons = article.locator("div[role=button]:has-text('Show more'), div[role=button]:has-text('显示更多')")
        if buttons.count() > 0:
            try:
                buttons.first.click(timeout=2000)
                time.sleep(1)
            except Exception:
                break
        else:
            break

def extract_tweet_data(article, tweet_url):
    my_id = tweet_url.split("/status/")[-1].split("?")[0]

    # Username (screen name)
    user_link = article.locator("a[href^='/']").first
    username = user_link.get_attribute("href").strip("/") if user_link else "unknown"

    # Created at
    time_el = article.locator("time").first
    created_at = time_el.get_attribute("datetime") if time_el else None

    # Main text
    main_text_nodes = article.locator("div[data-testid='tweetText']")
    text = main_text_nodes.nth(0).inner_text().strip() if main_text_nodes.count() > 0 else ""

    # Images
    imgs = article.locator("img").all()
    image_paths = [img.get_attribute("src") for img in imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]

    # --- Robustly extract ALL quoted tweet IDs ---
    anchors = article.locator("a[href*='/status/']")
    quoted_tweet_ids = set()
    for a in anchors.all():
        href = a.get_attribute("href")
        match = re.search(r'/status/(\d+)', href) if href else None
        if match:
            tid = match.group(1)
            if tid != my_id:
                quoted_tweet_ids.add(tid)

    # --- Reply detection (unchanged) ---
    in_reply_to_tweet_id = None
    reply_block = article.locator(":text('Replying to')").first
    if reply_block and reply_block.count() > 0:
        reply_anchors = reply_block.locator("a[href*='/status/']")
        for a in reply_anchors.all():
            href = a.get_attribute("href")
            match = re.search(r'/status/(\d+)', href)
            if match:
                reply_id = match.group(1)
                if reply_id != my_id:
                    in_reply_to_tweet_id = reply_id
                    break

    user_id = username

    return {
        "tweet_id": my_id,
        "user_id": user_id or "unknown",
        "username": username,
        "text": text,
        "created_at": created_at,
        "in_reply_to_tweet_id": in_reply_to_tweet_id,
        "quoted_tweet_ids": list(quoted_tweet_ids),
        "image_paths": image_paths,
    }

def print_tweet_data(tweet_data):
    print("=" * 50)
    print(f"TWEET_ID: {tweet_data.get('tweet_id')}")
    print(f"USER_ID: {tweet_data.get('user_id')}")
    print(f"USERNAME: {tweet_data.get('username')}")
    print(f"IN_REPLY_TO_TWEET_ID: {tweet_data.get('in_reply_to_tweet_id')}")
    print(f"QUOTED_TWEET_IDS: {tweet_data.get('quoted_tweet_ids')}")
    print(f"CREATED_AT: {tweet_data.get('created_at')}")
    print(f"IMAGE_PATHS: {tweet_data.get('image_paths')}")
    print(f"TEXT:\n{tweet_data.get('text')}")
    if tweet_data.get('quoted_tweet_ids'):
        print("----- QUOTED TWEET(S) -----")
        for qid in tweet_data.get('quoted_tweet_ids', []):
            print(f"QUOTED_TWEET_ID: {qid}")
    print("=" * 50)

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_scraper_minimal.py https://twitter.com/username/status/123456789")
        sys.exit(1)
    tweet_url = sys.argv[1]
    # Accept x.com or twitter.com
    if tweet_url.startswith("https://x.com/"):
        tweet_url = tweet_url.replace("https://x.com/", "https://twitter.com/")

    TWITTER_USERNAME = os.environ.get("TWITTER_USERNAME")
    TWITTER_PASSWORD = os.environ.get("TWITTER_PASSWORD")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Login if credentials set
        if TWITTER_USERNAME and TWITTER_PASSWORD:
            page.goto("https://twitter.com/login")
            page.wait_for_selector("input[name='text']", timeout=15000)
            page.fill("input[name='text']", TWITTER_USERNAME)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
            page.wait_for_selector("input[name='password']", timeout=15000)
            page.fill("input[name='password']", TWITTER_PASSWORD)
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)

        # Go to the tweet page
        page.goto(tweet_url)
        page.wait_for_selector("article", timeout=10000)
        articles = page.locator("article")
        print(f"Found {articles.count()} <article> nodes on the page.")
        for i in range(articles.count()):
            print(f"\n==== ARTICLE #{i} ====")
            try:
                print(articles.nth(i).inner_text())
            except Exception as e:
                print(f"(Could not read article {i}): {e}")
        print("=" * 60)
        main_article = articles.first
        expand_show_more(main_article)
        tweet_data = extract_tweet_data(main_article, tweet_url)
        print_tweet_data(tweet_data)

        # Canonically open ALL quoted tweets by ID (not just one)
        for qid in tweet_data.get("quoted_tweet_ids", []):
            quoted_url = f"https://twitter.com/i/web/status/{qid}"
            print(f"\n--- Now scraping quoted tweet canonically: {quoted_url} ---\n")
            qpage = context.new_page()
            qpage.goto(quoted_url)
            qpage.wait_for_selector("article", timeout=10000)
            quoted_article = qpage.locator("article").first
            expand_show_more(quoted_article)
            quoted_data = extract_tweet_data(quoted_article, quoted_url)
            print_tweet_data(quoted_data)
            qpage.close()

        # If reply, extract one level deeper (keep old logic for in_reply_to_tweet_id)
        in_reply_to_id = tweet_data.get("in_reply_to_tweet_id")
        if in_reply_to_id:
            reply_url = f"https://twitter.com/i/web/status/{in_reply_to_id}"
            print(f"\n--- Now scraping referenced tweet: IN_REPLY_TO_TWEET_ID ({in_reply_to_id}) ---\n")
            page.goto(reply_url)
            page.wait_for_selector("article", timeout=10000)
            reply_article = page.locator("article").first
            expand_show_more(reply_article)
            reply_data = extract_tweet_data(reply_article, reply_url)
            print_tweet_data(reply_data)
            time.sleep(2)

        browser.close()

if __name__ == "__main__":
    main()