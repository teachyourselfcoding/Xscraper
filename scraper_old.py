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

def expand_show_more(el):
    # Click all visible "Show more" or "显示更多" in this article element, until none are left
    """Click all visible 'Show more' or '显示更多' in this article element, until none are left.
    Returns True if NO more show more buttons remain after expansion, False if any remain."""
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
    # After expansion, check if any show more buttons remain
    show_more_buttons = el.locator("div[role=button]:has-text('Show more'), div[role=button]:has-text('显示更多')")
    return show_more_buttons.count() == 0

def save_tweet(tweet_data, date):
    date_str = date.strftime("%Y-%m-%d")
    notebook = DAILY_DIR / f"{date_str}.md"
    with notebook.open("a", encoding="utf-8") as f:
        f.write(f"\n### 🧾 {tweet_data['time']}\n")
        lines = tweet_data["text"].splitlines()
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
        else:
            f.write(tweet_data["text"] + "\n")

        # Write main images
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

def collect_tweet_ids_from_timeline(page, target_date):
    tweet_blocks = page.locator("article[role='article']")
    tweet_id_to_url = dict()
    tweet_id_to_time = dict()
    tweet_id_to_date = dict()
    for el in tweet_blocks.all():
        try:
            time_el = el.locator("time").first
            time_str = time_el.get_attribute("datetime")
            if not time_str:
                continue
            dt = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).astimezone()
            if target_date is not None and dt.date() != target_date:
                continue
            tweet_id = None
            tweet_url = None
            for a in el.locator('a').all():
                href = a.get_attribute('href')
                if href and '/status/' in href:
                    tweet_id = href.split('/status/')[-1].split('?')[0]
                    tweet_url = "https://twitter.com" + href if not href.startswith("http") else href
                    break
            if tweet_id and tweet_url:
                tweet_id_to_url[tweet_id] = tweet_url
                tweet_id_to_time[tweet_id] = dt.strftime("%H:%M")
                tweet_id_to_date[tweet_id] = dt.date()
        except Exception as e:
            print(f"⚠️ Error collecting tweet id: {e}")
    return tweet_id_to_url, tweet_id_to_time, tweet_id_to_date

def scrape_tweets(page, tweet_id_to_url, tweet_id_to_time, tweet_id_to_date):
    # Second pass: for each unique tweet_id, open canonical tweet page and extract all data
    context = page.context
    browser = context.browser
    storage = context.storage_state()
    deep_context = browser.new_context(storage_state=storage)
    canonical_tweets = []
    for tweet_id, tweet_url in tweet_id_to_url.items():
        try:
            print(f"🔎 Canonical-scraping: {tweet_url}")
            new_page = deep_context.new_page()
            new_page.goto(tweet_url)
            try:
                new_page.wait_for_selector("article", timeout=10000)
                articles = new_page.locator("article")
                # Find the main article whose time matches the timeline time
                timeline_time = tweet_id_to_time.get(tweet_id)
                main_article = None
                main_time_str = None
                main_dt = None
                for art in articles.all():
                    art_time_el = art.locator("time")
                    if art_time_el.count() > 0:
                        candidate_time_str = art_time_el.first.get_attribute("datetime")
                        if candidate_time_str:
                            candidate_dt = datetime.datetime.fromisoformat(candidate_time_str.replace("Z", "+00:00")).astimezone()
                            candidate_hm = candidate_dt.strftime("%H:%M")
                            if candidate_hm == timeline_time:
                                main_article = art
                                main_time_str = candidate_time_str
                                main_dt = candidate_dt
                                break
                quoted = None
                quoted_article = None
                # If failed to match main_article, fallback
                if main_article is None:
                    main_article = articles.first
                    main_time_el = main_article.locator("time")
                    main_time_str = main_time_el.first.get_attribute("datetime") if main_time_el.count() > 0 else None
                    if main_time_str:
                        main_dt = datetime.datetime.fromisoformat(main_time_str.replace("Z", "+00:00")).astimezone()
                expand_show_more(main_article)
                main_text = main_article.inner_text().strip()
                main_imgs = main_article.locator("img").all()
                main_img_urls = [img.get_attribute("src") for img in main_imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
                quoted_locator = main_article.locator("div[aria-label='Quoted Tweet'] article")
                if quoted_locator.count() > 0:
                    quoted_article = quoted_locator.first
                else:
                    # Alternative: sometimes a nested article inside main_article might be the quoted tweet
                    nested_articles = main_article.locator("article")
                    if nested_articles.count() > 1:
                        quoted_article = nested_articles.nth(1)
                if quoted_article:
                    expand_show_more(quoted_article)
                    sub_text = quoted_article.inner_text().strip()
                    sub_imgs = quoted_article.locator("img").all()
                    sub_img_urls = [img.get_attribute("src") for img in sub_imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
                    sub_time_el = quoted_article.locator("time")
                    sub_time_str = sub_time_el.first.get_attribute("datetime") if sub_time_el.count() > 0 else None
                    sub_dt = None
                    if sub_time_str:
                        sub_dt = datetime.datetime.fromisoformat(sub_time_str.replace("Z", "+00:00")).astimezone()
                    quoted = {
                        "text": sub_text,
                        "images": sub_img_urls,
                        "datetime": sub_dt.strftime("%Y-%m-%d %H:%M") if sub_dt else None
                    }
                # --- PATCH: naked quote fallback ---
                # Always use timeline date for naked quote fallback, not canonical date
                if (main_dt is None or main_dt.date() != tweet_id_to_date.get(tweet_id)) and quoted_article is not None:
                    print(f"⚠️ Naked quote fallback: {tweet_id} | using timeline date/time for synthetic tweet.")
                    canonical_tweets.append({
                        "tweet_id": tweet_id,
                        "text": "",  # No parent text, naked quote
                        "images": [],
                        "time": tweet_id_to_time.get(tweet_id, ""),
                        "date": tweet_id_to_date.get(tweet_id, TARGET_DATE),
                        "quoted": quoted
                    })
                else:
                    canonical_tweets.append({
                        "tweet_id": tweet_id,
                        "text": main_text,
                        "images": main_img_urls,
                        "time": main_dt.strftime("%H:%M") if main_dt else tweet_id_to_time.get(tweet_id, ""),
                        "date": main_dt.date() if main_dt else tweet_id_to_date.get(tweet_id, TARGET_DATE),
                        "quoted": quoted
                    })
                print(f"✅ Canonical: {tweet_id} {main_dt.strftime('%H:%M') if main_dt else tweet_id_to_time.get(tweet_id,'')} {main_text[:40]}...")
            except Exception as e:
                print(f"⚠️ Error canonical-scraping tweet: {tweet_url} — {e}")
            finally:
                new_page.close()
            time.sleep(1.5)
        except Exception as e:
            print(f"⚠️ Could not open context for canonical-scrape: {e}")
    deep_context.close()
    # Deduplicate strictly by tweet_id
    deduped = {}
    for t in canonical_tweets:
        tid = t.get("tweet_id")
        if tid:
            deduped[tid] = t
    return list(deduped.values())

def collect_all_tweet_ids_for_day(page, target_date, max_page_downs=200, patience=5, global_patience=10):
    tweet_id_to_url = {}
    tweet_id_to_time = {}
    tweet_id_to_date = {}
    consecutive_no_new = 0
    global_no_new = 0
    before_target_seen = False
    started_scraping = False  # Flag for when we've seen at least 1 tweet for the target date

    for n in range(max_page_downs):
        # Collect IDs after each small scroll
        new_ids, new_times, new_dates = collect_tweet_ids_from_timeline(page, target_date)
        new_found = 0
        for tid in new_ids:
            if tid not in tweet_id_to_url:
                tweet_id_to_url[tid] = new_ids[tid]
                tweet_id_to_time[tid] = new_times.get(tid, "")
                tweet_id_to_date[tid] = new_dates.get(tid, target_date)
                new_found += 1
        print(f"🔄 PageDown {n+1} — {len(new_ids)} tweet ids collected, {len(tweet_id_to_url)} unique for target date.")

        # If we've started scraping the target date, activate global patience
        if not started_scraping and new_found > 0:
            started_scraping = True

        if started_scraping:
            # Global patience: stop after 10 consecutive 0-new-tweet PageDowns
            if new_found == 0:
                global_no_new += 1
                if global_no_new >= global_patience:
                    print(f"🛑 No new tweets after {global_patience} consecutive PageDowns. Stopping.")
                    break
            else:
                global_no_new = 0

        # Check if any tweet BEFORE the target date is visible
        batch_before_target = any(date_val < target_date for date_val in new_dates.values())
        if batch_before_target:
            before_target_seen = True

        if before_target_seen:
            if new_found == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= patience:
                    print(f"🛑 No new tweets after seeing before-target-date tweets for {patience} PageDowns. Stopping.")
                    break
            else:
                consecutive_no_new = 0  # Reset if new tweets found
        else:
            consecutive_no_new = 0  # Reset if before_target_seen is not True

        # Do one slow PageDown
        page.keyboard.press("PageDown")
        time.sleep(1)
    return tweet_id_to_url, tweet_id_to_time, tweet_id_to_date

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

        tweet_id_to_url, tweet_id_to_time, tweet_id_to_date = collect_all_tweet_ids_for_day(page, TARGET_DATE)

        all_tweets = scrape_tweets(page, tweet_id_to_url, tweet_id_to_time, tweet_id_to_date)
        for t in all_tweets:
            tid = t.get('tweet_id')
            canon_date = t.get('date')
            timeline_date = tweet_id_to_date.get(tid)
            if canon_date != TARGET_DATE:
                print(f"❗Canonical date mismatch: {tid} | canonical={canon_date} | timeline={timeline_date}")
        # PATCH: Only keep tweets whose tweet_id_to_date matches the target date
        all_tweets = [tweet for tweet in all_tweets if tweet_id_to_date.get(tweet.get('tweet_id')) == TARGET_DATE]

        for tweet in sorted(all_tweets, key=lambda t: (t.get('date'), t.get('time'))):
            print(f"FinalList: {tweet.get('tweet_id')} {tweet.get('time')} {tweet['text'][:40]}...")
            # Always use the main tweet's date for saving, even if quoted tweet exists
            save_tweet(tweet, tweet_id_to_date.get(tweet.get('tweet_id'), TARGET_DATE))
        print(f"✅ Saved {len(all_tweets)} tweets from {TARGET_DATE}.")
        if hasattr(page, "context") and page.context:
            page.context.close()
        if hasattr(page, "browser") and page.browser:
            page.browser.close()

if __name__ == "__main__":
    main()