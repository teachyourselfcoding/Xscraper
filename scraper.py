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
            f.write("\n\t> 🧵 Quoted Tweet")
            if tweet_data["quoted"].get("datetime"):
                qdt = tweet_data["quoted"]["datetime"]
                f.write(f" — {qdt}")
            f.write(":\n")
            f.write(f"\t> {tweet_data['quoted']['text']}\n")
            for qimg in tweet_data['quoted']['images']:
                qfilename = f"{uuid.uuid4().hex[:8]}.jpg"
                qimg_path = DAILY_DIR / qfilename
                try:
                    qresponse = requests.get(qimg, timeout=10)
                    with qimg_path.open("wb") as qf:
                        qf.write(qresponse.content)
                    f.write(f"\n    ![img]({qimg_path.name})\n")
                except Exception as e:
                    f.write(f"\n    ![img]({qimg})  <!-- failed to download -->\n")
                    print(f"⚠️ Failed to download quoted image: {e}")
        f.write("\n---\n")

def scrape_tweets(page, target_date=None):
    context = page.context
    tweets = []
    tweet_blocks = page.locator("article")

    for el in tweet_blocks.all():
        try:
            time_el = el.locator("time").first
            time_str = time_el.get_attribute("datetime")
            if not time_str:
                continue
            dt = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).astimezone()

            if target_date is not None and dt.date() != target_date:
                continue

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
                        # Accept only permalinks of the form /status/{id} (allow query params, disallow /photo etc.)
                        match = re.search(r'/status/(\d+)(?:[/?]|$)', href)
                        if match:
                            tid = match.group(1)
                            if (
                                (main_tweet_id is None or tid != main_tweet_id)
                                and (
                                    href.rstrip('/').endswith(f"/status/{tid}")
                                    or re.search(rf'/status/{tid}\?(?=\w)', href)
                                )
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
                        # Click 'Show more' if present
                        show_more_buttons = new_page.locator("div[role=button]:has-text('Show more')")
                        if show_more_buttons.count() > 0:
                            try:
                                show_more_buttons.first.click(timeout=2000)
                                print("📝 Clicked 'Show more' on quoted tweet.")
                                time.sleep(1)
                            except Exception as e:
                                print(f"⚠️ Could not click 'Show more': {e}")
                        qarticle = new_page.locator("article").first
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
        except Exception as e:
            print(f"⚠️ Error reading tweet: {e}")
    return tweets

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
            save_tweet(tweet, tweet["date"])
        print(f"✅ Saved {len(all_tweets)} tweets from {TARGET_DATE}.")
        if hasattr(page, "context") and page.context:
            page.context.close()
        if hasattr(page, "browser") and page.browser:
            page.browser.close()

if __name__ == "__main__":
    main()