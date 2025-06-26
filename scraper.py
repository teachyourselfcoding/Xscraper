def expand_show_more(el):
    # Click all visible "Show more" or "显示更多" in this article element, until none are left
    while True:
        show_more_buttons = el.locator("div[role=button]:has-text('Show more'), div[role=button]:has-text('显示更多')")
        if show_more_buttons.count() > 0:
            try:
                show_more_buttons.first.click(timeout=2000)
                time.sleep(1.5)
            except Exception as e:
                print(f"⚠️ Could not click 'Show more': {e}")
                break
        else:
            break
# scraper.py
from playwright.sync_api import sync_playwright
import datetime
from pathlib import Path
import os
from dotenv import load_dotenv
import requests
import uuid
import time
import re
load_dotenv()

# ---- CONFIGURATION ----
TWITTER_USER = os.environ.get("TWITTER_TARGET_HANDLE", "TARGET_USERNAME")
TWITTER_USERNAME = os.environ["TWITTER_USERNAME"]
TWITTER_PASSWORD = os.environ["TWITTER_PASSWORD"]
OUTPUT_DIR = Path("notebooks")
# Number of times to scroll down to load more tweets (increase for longer threads or more tweets)
SCROLL_TIMES = 10  # Number of times to scroll down
# Set the date to scrape in YYYY-MM-DD format (default: today in SGT)
date_str = os.environ.get("SCRAPE_DATE")
if date_str:
    TARGET_DATE = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
else:
    TARGET_DATE = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date()
SUBFOLDER_NAME = TARGET_DATE.strftime("%d-%b-%Y").lower()
DAILY_DIR = OUTPUT_DIR / SUBFOLDER_NAME
DAILY_DIR.mkdir(parents=True, exist_ok=True)
# ------------------------

OUTPUT_DIR.mkdir(exist_ok=True)

def save_tweet(tweet_data, date):
    date_str = date.strftime("%Y-%m-%d")
    notebook = DAILY_DIR / f"{date_str}.md"
    with notebook.open("a", encoding="utf-8") as f:
        f.write(f"\n### 🧾 {tweet_data['time']}\n")
        f.write(tweet_data["text"] + "\n")
        # Enhanced fallback for quoting:
        if not tweet_data.get("quoted"):
            text = tweet_data["text"]
            # Handle Quote marker
            if "Quote " in text:
                main_body, quote = text.split("Quote ", 1)
                f.write(main_body.strip() + "\n")
                # Blockquote the rest
                for line in quote.splitlines():
                    if line.strip():
                        f.write(f"> {line}\n")
                    else:
                        f.write(">\n")
                f.write("\n---\n")
                return
            # Handle "Replying to ..." marker
            lines = text.splitlines()
            reply_idx = None
            for i, line in enumerate(lines):
                if line.strip().startswith("Replying to @"):
                    reply_idx = i
                    break
            if reply_idx is not None:
                # Write lines before "Replying to"
                for l in lines[:reply_idx]:
                    if l.strip():
                        f.write(l.strip() + "\n")
                # Blockquote lines after (including the reply marker)
                for l in lines[reply_idx:]:
                    if l.strip():
                        f.write(f"> {l}\n")
                    else:
                        f.write(">\n")
                f.write("\n---\n")
                return
        for img in tweet_data["images"]:
            filename = f"{uuid.uuid4().hex[:8]}.jpg"
            img_path = DAILY_DIR / filename
            try:
                response = requests.get(img, timeout=10)
                with img_path.open("wb") as img_file:
                    img_file.write(response.content)
                f.write(f"\n![img]({img_path.name})\n")
            except Exception as e:
                f.write(f"\n![img]({img})  <!-- failed to download -->\n")
                print(f"⚠️ Failed to download image: {e}")
        if tweet_data.get("quoted"):
            f.write("\n> 🧵 Quoted Tweet")
            if tweet_data["quoted"].get("datetime"):
                qdt = tweet_data["quoted"]["datetime"]
                f.write(f" — {qdt}")
            f.write(":\n")
            # Write each line of quoted text as a markdown blockquote
            quoted_text = tweet_data['quoted']['text']
            if quoted_text:
                for line in quoted_text.splitlines():
                    if line.strip():
                        f.write(f"> {line}\n")
                    else:
                        f.write(">\n")
                # Extra blockquote line for spacing before image
                f.write(">\n")
            # Add quoted images (no >)
            for qimg in tweet_data['quoted']['images']:
                qfilename = f"{uuid.uuid4().hex[:8]}.jpg"
                qimg_path = DAILY_DIR / qfilename
                try:
                    qresponse = requests.get(qimg, timeout=10)
                    with qimg_path.open("wb") as qf:
                        qf.write(qresponse.content)
                    f.write(f"![img]({qimg_path.name})\n")
                except Exception as e:
                    f.write(f"![img]({qimg})  <!-- failed to download -->\n")
                    print(f"⚠️ Failed to download quoted image: {e}")
        f.write("\n---\n")

def scrape_tweets(page, target_date=None):
    context = page.context
    tweets = []
    tweet_blocks = page.locator("article[role='article']")

    # Collect all status links on the page for later deep extraction
    all_status_links = set()
    for a in page.locator("a").all():
        href = a.get_attribute('href')
        if href and '/status/' in href:
            # Accept only pure permalinks of the form /status/{id} or /status/{id}?query (not /photo/1 or /analytics)
            match = re.search(r'/status/(\d+)(?P<after>/[a-zA-Z0-9_/-]+|\?|$)', href)
            if match:
                tid = match.group(1)
                after = match.group("after")
                if after == "" or after == "?" or after.startswith("?"):
                    all_status_links.add((tid, href))

    scraped_ids = set()
    for el in tweet_blocks.all():
        try:
            time_el = el.locator("time").first
            time_str = time_el.get_attribute("datetime")
            if not time_str:
                continue
            dt = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).astimezone()

            if target_date is not None and dt.date() != target_date:
                continue

            expand_show_more(el)
            text = el.inner_text().strip()
            imgs = el.locator("img").all()
            img_urls = [img.get_attribute("src") for img in imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]

            # Extract tweet ID from the first <a> with /status/
            tweet_id = None
            try:
                for a in el.locator('a').all():
                    href = a.get_attribute('href')
                    if href and '/status/' in href:
                        tweet_id = href.split('/status/')[-1].split('?')[0]
                        break
            except Exception:
                pass

            print(f"ScrapeCheck: {tweet_id} {dt.strftime('%H:%M')} {text[:40]}...")

            # Check for quoted tweet
            quoted_data = None
            try:
                quoted_url = None
                # Find all links to status pages in the tweet
                anchors = el.locator("a")
                main_tweet_id = tweet_id if 'tweet_id' in locals() else None
                status_links = []
                for i in range(anchors.count()):
                    href = anchors.nth(i).get_attribute("href")
                    if href and "/status/" in href:
                        # Accept only pure permalinks of the form /status/{id} or /status/{id}?query (not /photo/1 or /analytics)
                        match = re.search(r'/status/(\d+)(?P<after>/[a-zA-Z0-9_/-]+|\?|$)', href)
                        if match:
                            tid = match.group(1)
                            after = match.group("after")
                            if (
                                (main_tweet_id is None or tid != main_tweet_id)
                                and (after == "" or after == "?" or after.startswith("?"))
                            ):
                                status_links.append(href)
                if status_links:
                    quoted_url = "https://twitter.com" + status_links[0]
                if quoted_url:
                    print(f"🔗 Opening quoted tweet: {quoted_url}")
                    browser = context.browser
                    storage = context.storage_state()
                    quote_context = browser.new_context(storage_state=storage)
                    new_page = quote_context.new_page()
                    new_page.goto(quoted_url)
                    try:
                        new_page.wait_for_selector("article", timeout=7000)
                        qarticle = new_page.locator("article").first
                        expand_show_more(qarticle)
                        qtext = qarticle.inner_text().strip()
                        qimgs = qarticle.locator("img").all()
                        qimg_urls = [img.get_attribute("src") for img in qimgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
                        qtime_el = qarticle.locator("time")
                        qtime_str = qtime_el.first.get_attribute("datetime") if qtime_el.count() > 0 else None
                        quoted_data = {
                            "text": qtext,
                            "images": qimg_urls,
                            "datetime": qtime_str
                        }
                    except Exception as e:
                        print(f"⚠️ Error scraping quoted tweet page: {e}")
                    finally:
                        new_page.close()
                        quote_context.close()
                else:
                    # Try to log HTML of the quote block for diagnosis
                    try:
                        quoted_el = el.locator('[data-testid="tweet"] [tabindex="0"] article[role="article"]').nth(1)
                        html = quoted_el.inner_html() if quoted_el.count() > 0 else '(no quoted_el)'
                        print(f"⚠️ Quoted tweet block HTML:\n{html}")
                    except Exception as log_e:
                        print(f"⚠️ Could not log quoted tweet HTML: {log_e}")
                    print(f"⚠️ No quoted tweet link found; using timeline fragment if available.")
            except Exception as e:
                print(f"⚠️ Failed to fetch quoted tweet: {e}")

            tweets.append({
                "text": text,
                "images": img_urls,
                "time": dt.strftime("%H:%M"),
                "date": dt.date(),
                "quoted": quoted_data,
                "tweet_id": tweet_id
            })
            if tweet_id:
                scraped_ids.add(tweet_id)
        except Exception as e:
            print(f"⚠️ Error reading tweet: {e}")
    # Deep scrape for unseen tweets by ID
    # Deep scrape: open every unique /status/{id} (not just unseen ones)
    if all_status_links:
        browser = context.browser
        storage = context.storage_state()
        for tid, href in all_status_links:
            full_url = "https://twitter.com" + href if not href.startswith("http") else href
            try:
                quote_context = browser.new_context(storage_state=storage)
                new_page = quote_context.new_page()
                new_page.goto(full_url)
                try:
                    new_page.wait_for_selector("article", timeout=7000)
                    qarticle = new_page.locator("article").first
                    expand_show_more(qarticle)
                    qtext = qarticle.inner_text().strip()
                    qimgs = qarticle.locator("img").all()
                    qimg_urls = [img.get_attribute("src") for img in qimgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
                    qtime_el = qarticle.locator("time")
                    qtime_str = qtime_el.first.get_attribute("datetime") if qtime_el.count() > 0 else None
                    qdt = None
                    if qtime_str:
                        qdt = datetime.datetime.fromisoformat(qtime_str.replace("Z", "+00:00")).astimezone()
                    # Only add if matches target_date
                    if target_date is None or (qdt and qdt.date() == target_date):
                        tweets.append({
                            "text": qtext,
                            "images": qimg_urls,
                            "time": qdt.strftime("%H:%M") if qdt else "",
                            "date": qdt.date() if qdt else None,
                            "quoted": None,
                            "tweet_id": tid
                        })
                except Exception as e:
                    print(f"⚠️ Error scraping tweet {tid} via permalink: {e}")
                finally:
                    new_page.close()
                    quote_context.close()
            except Exception as e:
                print(f"⚠️ Could not open context for tweet {tid}: {e}")
    # Deduplicate: only by tweet_id (never by (text, time)), except when tweet_id is missing.
    deduped = {}
    for t in tweets:
        tid = t.get("tweet_id")
        if tid:
            deduped[tid] = t
        else:
            # If no tweet_id, always include (use unique key)
            deduped[(t["text"], t["time"], id(t))] = t
    return list(deduped.values())

def main():
    with sync_playwright() as p:
        page = p.chromium.launch(headless=False).new_page()
        page.goto("https://twitter.com/login")
        page.wait_for_selector("input[name='text']", timeout=15000)
        page.fill("input[name='text']", TWITTER_USERNAME)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)
        page.wait_for_selector("input[name='password']", timeout=15000)
        page.fill("input[name='password']", TWITTER_PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)

        page.goto(f"https://twitter.com/{TWITTER_USER}")
        page.wait_for_timeout(5000)

        all_tweets = []
        seen_tweet_ids = set()

        # Capture initial batch before any scrolling
        new_tweets = scrape_tweets(page, target_date=None)
        print(f"🔄 Initial page — scraped {len(new_tweets)} tweets")
        new_found = 0
        for tweet in new_tweets:
            if tweet["date"] == TARGET_DATE:
                tweet_id = tweet.get("tweet_id")
                key = tweet_id if tweet_id else (tweet["text"], tweet["time"])
                if key not in seen_tweet_ids:
                    seen_tweet_ids.add(key)
                    all_tweets.append(tweet)
                    new_found += 1
        print(f"✅ Found {new_found} new tweets for {TARGET_DATE} on initial load.")

        max_scrolls = 50  # safety net
        scroll_attempt = 0
        last_seen_count = -1  # for stopping condition

        while scroll_attempt < max_scrolls:
            page.mouse.wheel(0, 5000)
            prev_count = page.locator("article").count()
            for _ in range(14):  # wait up to 7 seconds
                time.sleep(0.5)
                curr_count = page.locator("article").count()
                if curr_count > prev_count:
                    break
            page.wait_for_timeout(2000)

            new_tweets = scrape_tweets(page, target_date=None)
            print(f"🔄 Scroll {scroll_attempt + 1} — scraped {len(new_tweets)} tweets")
            new_found = 0
            for tweet in new_tweets:
                if tweet["date"] == TARGET_DATE:
                    tweet_id = tweet.get("tweet_id")
                    key = tweet_id if tweet_id else (tweet["text"], tweet["time"])
                    if key not in seen_tweet_ids:
                        seen_tweet_ids.add(key)
                        all_tweets.append(tweet)
                        new_found += 1

            print(f"✅ Found {new_found} new tweets for {TARGET_DATE} this scroll.")

            # If we found 0 new tweets for the target date in this scroll, assume we're done
            if new_found == 0 and last_seen_count == 0:
                print("🛑 No new tweets for target date after two consecutive scrolls. Stopping.")
                break
            last_seen_count = new_found
            scroll_attempt += 1

        for tweet in sorted(all_tweets, key=lambda t: (t["date"], t["time"])):
            print(f"FinalList: {tweet.get('tweet_id')} {tweet['time']} {tweet['text'][:40]}...")
            save_tweet(tweet, tweet["date"])
        print(f"✅ Saved {len(all_tweets)} tweets from {TARGET_DATE}.")
        if hasattr(page, "context") and page.context:
            page.context.close()
        if hasattr(page, "browser") and page.browser:
            page.browser.close()

if __name__ == "__main__":
    main()