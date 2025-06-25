# scraper.py
from playwright.sync_api import sync_playwright
import datetime
from pathlib import Path
import os
from dotenv import load_dotenv
import requests
import uuid
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
            f.write("\n> 🧵 Quoted Tweet:\n")
            f.write(f"> {tweet_data['quoted']['text']}\n")
            for qimg in tweet_data['quoted']['images']:
                qfilename = f"{uuid.uuid4().hex[:8]}.jpg"
                qimg_path = DAILY_DIR / qfilename
                try:
                    qresponse = requests.get(qimg, timeout=10)
                    with qimg_path.open("wb") as qf:
                        qf.write(qresponse.content)
                    f.write(f"\n> ![img]({qimg_path.name})\n")
                except Exception as e:
                    f.write(f"\n> ![img]({qimg})  <!-- failed to download -->\n")
                    print(f"⚠️ Failed to download quoted image: {e}")
        f.write("\n---\n")

def scrape_tweets(page, target_date=None):
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

            # Check for quoted tweet
            quoted_data = None
            try:
                quoted_el = el.locator("article").nth(1)
                if quoted_el.count() > 0:
                    quoted_text = quoted_el.inner_text().strip()
                    quoted_imgs = quoted_el.locator("img").all()
                    quoted_img_urls = [img.get_attribute("src") for img in quoted_imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
                    quoted_data = {
                        "text": quoted_text,
                        "images": quoted_img_urls
                    }
            except Exception:
                pass

            tweets.append({
                "text": text,
                "images": img_urls,
                "time": dt.strftime("%H:%M"),
                "date": dt.date(),
                "quoted": quoted_data
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
        started_collecting = False
        scroll_attempt = 0
        max_scrolls = 50  # safety net

        while scroll_attempt < max_scrolls:
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(2000)
            new_tweets = scrape_tweets(page, target_date=None)
            print(f"🔄 Scroll {scroll_attempt + 1} — scraped {len(new_tweets)} tweets")

            stop_now = False
            for tweet in new_tweets:
                print(f"📅 Found tweet dated {tweet['date']} — target: {TARGET_DATE}")
                if tweet["date"] > TARGET_DATE:
                    continue  # not yet at target
                elif tweet["date"] == TARGET_DATE:
                    if tweet not in all_tweets:
                        all_tweets.append(tweet)
                        started_collecting = True
                elif tweet["date"] < TARGET_DATE and started_collecting:
                    print(f"🛑 Reached older date ({tweet['date']}) after collecting — stopping.")
                    stop_now = True
                    break

            if stop_now:
                break

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