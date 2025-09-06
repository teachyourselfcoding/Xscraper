
from src.db.models import Tweet

import re

import argparse
from playwright.sync_api import sync_playwright
import datetime
from pathlib import Path
import os
import time
import requests
from sqlalchemy.orm import Session
import json
from pathlib import Path
import uuid
from src.db.session import SessionLocal
from src.db.crud import store_tweet
from dotenv import load_dotenv
load_dotenv()

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

# --- Config from environment or hardcoded ---
TWITTER_USER = os.environ.get("TWITTER_TARGET_HANDLE", "TARGET_USERNAME")
TWITTER_USERNAME = os.environ["TWITTER_USERNAME"]
TWITTER_PASSWORD = os.environ["TWITTER_PASSWORD"]

start_date_str = os.environ.get("SCRAPE_START_DATE")
end_date_str = os.environ.get("SCRAPE_END_DATE")

# --- Date setup ---
if start_date_str and end_date_str:
    START_DATE = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    END_DATE = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
else:
    END_DATE = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date()
    START_DATE = END_DATE

# --- URL & ID helpers ---
def canonical_tweet_url(tweet_id: str) -> str:
    """Always return the canonical tweet URL (no /history, /photo, etc.)."""
    return f"https://twitter.com/i/web/status/{tweet_id}"

def extract_status_id(href: str):
    """Return pure numeric status id from any tweet href or None."""
    if not href or "/status/" not in href:
        return None
    tail = href.split("/status/", 1)[-1]
    # strip query
    tail = tail.split("?", 1)[0]
    # strip any extra path segment like /photo/N, /video/N, /history, etc.
    tail = tail.split("/", 1)[0]
    return tail if re.fullmatch(r"\d+", tail) else None
 # Helper to download image with Playwright context if requests fails
def download_image_with_playwright(context, img_url, img_path):
     try:
         new_page = context.new_page()
         response = new_page.goto(img_url, wait_until='networkidle', timeout=10000)
         if response and response.ok:
             content = response.body()
             with open(img_path, "wb") as f:
                 f.write(content)
             new_page.close()
             return True
         else:
             new_page.close()
             return False
     except Exception as e:
         print(f"Playwright backup image download failed: {e}")
         return False
         
def parse_args():
    parser = argparse.ArgumentParser(description="Twitter Scraper")
    parser.add_argument("--user", type=str, required=True, help="Twitter username to scrape (without @)")
    parser.add_argument("--start-date", type=str, required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="End date YYYY-MM-DD")
    return parser.parse_args()

def expand_show_more(el):
    while True:
        buttons = el.locator("div[role=button]:has-text('Show more'), div[role=button]:has-text('显示更多')")
        if buttons.count() > 0:
            try:
                buttons.first.click(timeout=2000)
                time.sleep(1.5)
            except Exception as e:
                print(f"⚠️ Could not click 'Show more': {e}")
                break
        else:
            break

def parse_quoted_tweet_id(article) -> str:
    try:
        quoted_link = article.locator("a[href*='/status/']").first
        href = quoted_link.get_attribute("href")
        if href and "/status/" in href:
            return href.split("/status/")[-1].split("?")[0]
    except Exception:
        pass
    return None

def scrape_single_tweet(page, tweet_url, session):
    """Scrape detailed tweet data by opening tweet page."""
    page.goto(tweet_url)
    try:
        page.wait_for_selector("article", timeout=10000)
        # Identify the article that actually corresponds to this tweet_id (my_id)
        my_id = extract_status_id(tweet_url) or tweet_url.split("/status/")[-1].split("?")[0]
        articles = page.locator("article")
        target_article = None
        for idx in range(articles.count()):
            cand = articles.nth(idx)
            anchors = cand.locator("a[href*='/status/']")
            matched = False
            for a in anchors.all():
                href = a.get_attribute("href")
                sid = extract_status_id(href)
                if sid and sid == my_id:
                    matched = True
                    break
            if matched:
                target_article = cand
                break
        # Fallback: if not found, use the first article to avoid crashing, but log it
        if target_article is None:
            print(f"⚠️ Could not match article by id {my_id}; using first article as fallback.")
            target_article = articles.first

        # Work only within the matched article
        article = target_article
        expand_show_more(article)

        # --- PATCH: Robust main text extraction ---
        main_text_nodes = article.locator("div[data-testid='tweetText']")
        main_text = main_text_nodes.nth(0).inner_text().strip() if main_text_nodes.count() > 0 else ""

        # --- Extract created_at (tweet timestamp) early ---
        created_at = None
        time_el = article.locator(f"a[href*='/status/{my_id}'] time").first
        if time_el.count() == 0:
            time_el = article.locator("time").first
        if time_el.count() > 0:
            time_str = time_el.get_attribute("datetime")
            created_at = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).astimezone()

        # --- Extract user_id early ---
        username = TWITTER_USER
        user_link = article.locator("a[href^='/']").first
        if user_link:
            user_href = user_link.get_attribute("href")
            if user_href:
                username = user_href.strip("/")

        user_id = None
        user_id_elements = article.locator("[data-user-id]")
        for idx in range(user_id_elements.count()):
            candidate = user_id_elements.nth(idx)
            value = candidate.get_attribute("data-user-id")
            if value and value.isdigit():
                user_id = value
                break
        if not user_id:
            user_id = None if username.isdigit() else username

        # --- Quoted Tweet Detection ---
        quoted_tweet_id = None
        quoted_text = ""
        quoted_article = article.locator("div[aria-label='Quoted Tweet'] article, div[aria-label='引用的推文'] article")
        if quoted_article.count() > 0:
            qa = quoted_article.first
            expand_show_more(qa)
            # Quoted text & images
            q_text_nodes = qa.locator("div[data-testid='tweetText']")
            quoted_text = q_text_nodes.nth(0).inner_text().strip() if q_text_nodes.count() > 0 else ""
            q_imgs = qa.locator("img").all()
            quoted_image_srcs = [img.get_attribute("src") for img in q_imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
            # Quoted id
            q_anchors = qa.locator("a[href*='/status/']")
            for a in q_anchors.all():
                href = a.get_attribute("href")
                cid = extract_status_id(href)
                if cid and cid != my_id:
                    quoted_tweet_id = cid
                    print(f"Found QUOTED_TWEET_ID: {quoted_tweet_id}")
                    break
        else:
            # Fallback: X sometimes merges the quoted block into the main article without labeled container
            # 1) Try to split visible text by markers
            main_text_nodes = article.locator("div[data-testid='tweetText']")
            raw_text = main_text_nodes.nth(0).inner_text().strip() if main_text_nodes.count() > 0 else ""
            split_mark = None
            for m in ["\nQuote\n", "Quote", "引用"]:
                if m in raw_text:
                    split_mark = m
                    break
            if split_mark:
                parts = raw_text.split(split_mark, 1)
                main_text = parts[0].strip()
                quoted_text = parts[1].strip()
            # 2) From anchors inside the article, pick any other status id as the quote candidate
            alt_ids = set()
            all_anchors = article.locator("a[href*='/status/']")
            for a in all_anchors.all():
                href = a.get_attribute("href")
                cid = extract_status_id(href)
                if cid and cid != my_id:
                    alt_ids.add(cid)
            if alt_ids and not quoted_tweet_id:
                # Prefer an ID that has its own <time> scoped under its anchor
                picked = None
                for cid in alt_ids:
                    t_candidate = article.locator(f"a[href*='/status/{cid}'] time").first
                    if t_candidate and t_candidate.count() > 0:
                        picked = cid
                        break
                quoted_tweet_id = picked or next(iter(alt_ids))
                print(f"Found QUOTED_TWEET_ID via fallback: {quoted_tweet_id}")

        # --- Robust Reply Detection: Only if "Replying to" block exists ---
        in_reply_to_tweet_id = None
        reply_block = article.locator(":text('Replying to')").first
        if reply_block and reply_block.count() > 0:
            reply_anchors = reply_block.locator("a[href*='/status/']")
            for a in reply_anchors.all():
                href = a.get_attribute("href")
                rid = extract_status_id(href)
                if rid and rid != my_id:
                    in_reply_to_tweet_id = rid
                    print(f"Found REPLY via Replying to block: {in_reply_to_tweet_id}")
                    break
        # --- Fallback Reply Detection: nearest previous article on the page ---
        if in_reply_to_tweet_id is None:
            try:
                all_articles = page.locator("article")
                target_idx = None
                # Find index of current article
                for idx2 in range(all_articles.count()):
                    cand = all_articles.nth(idx2)
                    anchors2 = cand.locator("a[href*='/status/']")
                    if any(extract_status_id(a.get_attribute("href")) == my_id for a in anchors2.all()):
                        target_idx = idx2
                        break
                if target_idx is not None:
                    for j in range(target_idx - 1, -1, -1):
                        prev_art = all_articles.nth(j)
                        prev_time_el = prev_art.locator("time").first
                        if prev_time_el.count() == 0:
                            continue
                        prev_anchors = prev_art.locator("a[href*='/status/']")
                        parent_id = None
                        for a in prev_anchors.all():
                            pid = extract_status_id(a.get_attribute("href"))
                            if pid and pid != my_id:
                                parent_id = pid
                                break
                        if parent_id:
                            in_reply_to_tweet_id = parent_id
                            print(f"Fallback REPLY via preceding article: {in_reply_to_tweet_id}")
                            break
            except Exception:
                pass

        # --- LOG what is detected ---
        print(f"Main tweet: {my_id}")
        if quoted_tweet_id:
            print(f"Detected QUOTE: {quoted_tweet_id}")
        if in_reply_to_tweet_id:
            print(f"Detected REPLY: {in_reply_to_tweet_id}")

        # Calculate tweet date string and per-date image subdirectory
        tweet_date_str = created_at.strftime("%Y-%m-%d") if created_at else "unknown_date"
        date_dir = IMAGES_DIR / tweet_date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # Collect all image srcs in the article
        all_imgs = article.locator("img").all()
        all_image_srcs = [img.get_attribute("src") for img in all_imgs if img.get_attribute("src") and "media" in img.get_attribute("src")]
        # Quoted image srcs (from earlier, if any)
        quoted_image_srcs = quoted_image_srcs if 'quoted_image_srcs' in locals() else []
        # Main image srcs exclude quoted ones
        main_image_srcs = [u for u in all_image_srcs if u not in quoted_image_srcs]

        tweet_data = {
            "tweet_id": my_id,
            "user_id": user_id or "unknown",
            "username": username,
            "text": main_text if 'main_text' in locals() and main_text else (article.locator("div[data-testid='tweetText']").nth(0).inner_text().strip() if article.locator("div[data-testid='tweetText']").count() > 0 else ""),
            "created_at": created_at,
            "in_reply_to_tweet_id": in_reply_to_tweet_id,
            "quoted_tweet_id": quoted_tweet_id,
            "image_urls": [],
            "has_video": False,
        }

        # Save ONLY main images to local paths
        local_image_urls = []
        for img_url in main_image_srcs:
            if not isinstance(img_url, str):
                continue
            if not (img_url.startswith("http://") or img_url.startswith("https://")):
                print(f"Skipping non-URL image path: {img_url}")
                continue
            filename = f"{tweet_data['tweet_id']}_{uuid.uuid4().hex[:8]}.jpg"
            img_path = date_dir / filename
            # Try requests first
            success = False
            try:
                response = requests.get(img_url, timeout=10)
                if response.status_code == 200 and response.content:
                    with img_path.open("wb") as img_file:
                        img_file.write(response.content)
                    local_image_urls.append(str(img_path))
                    success = True
                else:
                    print(f"requests.get failed with status {response.status_code if response else 'N/A'}")
            except Exception as e:
                print(f"⚠️ requests image download failed: {e}")

            # Fallback to Playwright context if not successful
            if not success:
                context = page.context
                backup_success = download_image_with_playwright(context, img_url, img_path)
                if backup_success:
                    local_image_urls.append(str(img_path))
                else:
                    print(f"⚠️ Failed to download image by any means: {img_url}")
                    # Do NOT append img_url or any invalid path
        tweet_data["image_urls"] = local_image_urls
        tweet_data["image_paths"] = ",".join(local_image_urls)

        # --- Download quoted images, if any ---
        quoted_local_image_urls = []
        for qimg_url in quoted_image_srcs:
            if not isinstance(qimg_url, str):
                continue
            if not (qimg_url.startswith("http://") or qimg_url.startswith("https://")):
                print(f"Skipping non-URL quoted image path: {qimg_url}")
                continue
            qfilename = f"{tweet_data['tweet_id']}_quoted_{uuid.uuid4().hex[:8]}.jpg"
            qimg_path = date_dir / qfilename
            qsuccess = False
            try:
                qresponse = requests.get(qimg_url, timeout=10)
                if qresponse.status_code == 200 and qresponse.content:
                    with qimg_path.open("wb") as qimg_file:
                        qimg_file.write(qresponse.content)
                    quoted_local_image_urls.append(str(qimg_path))
                    qsuccess = True
                else:
                    print(f"requests.get failed for quoted image with status {qresponse.status_code if qresponse else 'N/A'}")
            except Exception as e:
                print(f"⚠️ requests quoted image download failed: {e}")
            if not qsuccess:
                context = page.context
                backup_qsuccess = download_image_with_playwright(context, qimg_url, qimg_path)
                if backup_qsuccess:
                    quoted_local_image_urls.append(str(qimg_path))
                else:
                    print(f"⚠️ Failed to download quoted image by any means: {qimg_url}")
        tweet_data["quoted_image_urls"] = quoted_local_image_urls
        tweet_data["quoted_text"] = quoted_text

        print("=" * 50)
        print(f"TWEET_ID: {tweet_data.get('tweet_id')}")
        print(f"USER_ID: {tweet_data.get('user_id')}")
        print(f"USERNAME: {tweet_data.get('username')}")
        print(f"IN_REPLY_TO_TWEET_ID: {tweet_data.get('in_reply_to_tweet_id')}")
        print(f"QUOTED_TWEET_ID: {tweet_data.get('quoted_tweet_id')}")
        print(f"CREATED_AT: {tweet_data.get('created_at')}")
        print(f"IMAGE_PATHS: {tweet_data.get('image_paths')}")
        print(f"TEXT:\n{tweet_data.get('text')}")
        print("=" * 50)

        # --- PATCH: Recursively scrape quoted/replied tweet if not in DB ---
        for related_id in [quoted_tweet_id, in_reply_to_tweet_id]:
            if related_id and not session.query(Tweet).filter_by(tweet_id=related_id).first():
                url = canonical_tweet_url(related_id)
                reply_page = page.context.new_page()
                reply_data = scrape_single_tweet(reply_page, url, session)
                reply_page.close()
                time.sleep(2)
                if reply_data:
                    from src.db.crud import store_tweet
                    store_tweet(reply_data, session, scraper_fn=None)
                    print(f"Saved quoted/replied tweet {related_id}")

        return tweet_data

    except Exception as e:
        print(f"Failed to scrape tweet {tweet_url}: {e}")
        return None

def single_pass_scrape(page, session):
    processed_tweet_ids = set()
    while True:
        tweet_articles = page.locator("article[role='article']")
        count = tweet_articles.count()
        print(f"Scrolling: Found {count} tweets on page.")

        scroll_has_new_tweet = False

        for i in range(count):
            article = tweet_articles.nth(i)
            try:
                # Get timestamp for the article
                time_el = article.locator("time").first
                if time_el.count() == 0:
                    continue
                time_str = time_el.get_attribute("datetime")
                dt = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).astimezone()
                tweet_date = dt.date()
                article_time_hm = dt.strftime("%H:%M")

                # Extract tweet ID and URL first (avoid logging None)
                anchors = article.locator("a")
                tweet_url = None
                tweet_id = None
                for a in anchors.all():
                    href = a.get_attribute("href")
                    tid = extract_status_id(href)
                    if tid:
                        tweet_id = tid
                        tweet_url = canonical_tweet_url(tweet_id)
                        break
                if not tweet_url or not tweet_id:
                    continue

                # Print debug info for troubleshooting with actual values
                print(f"Detected tweet {tweet_id} from {tweet_date} at {article_time_hm} with URL {tweet_url}")

                # Only process tweets within date range
                if tweet_date < START_DATE:
                    print(f"Tweet {tweet_id} is older than START_DATE. Skipping.")
                    continue
                elif tweet_date > END_DATE:
                    print(f"Tweet {tweet_id} is newer than END_DATE. Skipping.")
                    continue

                # If already seen in session or database, skip
                if tweet_id in processed_tweet_ids:
                    continue
                existing = session.query(Tweet).filter_by(tweet_id=tweet_id).first()
                if existing:
                    processed_tweet_ids.add(tweet_id)
                    continue

                # Scrape main tweet in detail
                new_page = page.context.new_page()
                tweet_data = scrape_single_tweet(new_page, tweet_url, session)
                new_page.close()
                time.sleep(2)
                if tweet_data:
                    try:
                        store_tweet(tweet_data, session, scraper_fn=None)
                        processed_tweet_ids.add(tweet_id)
                        scroll_has_new_tweet = True
                        print(f"Processed tweet {tweet_id} from {tweet_date}")
                    except Exception as e:
                        print(f"DB error: {e}")
                        session.rollback()

                    # Now, if quoted_tweet_id or in_reply_to_tweet_id exists and not in DB, process ONE level deep
                    for field in ["quoted_tweet_id", "in_reply_to_tweet_id"]:
                        qid = tweet_data.get(field)
                        if qid and not session.query(Tweet).filter_by(tweet_id=qid).first():
                            qurl = canonical_tweet_url(qid)
                            qpage = page.context.new_page()
                            qdata = scrape_single_tweet(qpage, qurl, session)
                            qpage.close()
                            time.sleep(2)
                            if qdata:
                                try:
                                    store_tweet(qdata, session, scraper_fn=None)
                                    processed_tweet_ids.add(qid)
                                    print(f"Processed quoted/replied tweet {qid}")
                                except Exception as e:
                                    print(f"DB error on quote/reply {qid}: {e}")
                                    session.rollback()

            except Exception as e:
                print(f"Error processing tweet at index {i}: {e}")

        # Stop if every tweet visible in this batch is older than START_DATE
        all_before_start = True
        for j in range(tweet_articles.count()):
            t_el = tweet_articles.nth(j).locator("time").first
            if t_el.count() == 0:
                continue
            t_str = t_el.get_attribute("datetime")
            if not t_str:
                continue
            t_dt = datetime.datetime.fromisoformat(t_str.replace("Z", "+00:00")).astimezone()
            if t_dt.date() >= START_DATE:
                all_before_start = False
                break
        if all_before_start:
            print(f"🛑 All tweets on this page are before {START_DATE}. Stopping.")
            break
        if not scroll_has_new_tweet:
            print("No new tweets found in this scroll. Scrolling down...")
        page.keyboard.press("PageDown")
        time.sleep(2)

def run_scraper(user, start_date, end_date, login_username, login_password):
    session = SessionLocal()
    cookie_path = Path("twitter_cookies.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = None

        if cookie_path.exists():
            print("Loading cookies from file...")
            storage = json.loads(cookie_path.read_text())
            context = browser.new_context(storage_state=storage)
        else:
            context = browser.new_context()

        page = context.new_page()

        # If cookies not loaded, perform login and save cookies
        if not cookie_path.exists():
            page.goto("https://twitter.com/login")
            page.wait_for_selector("input[name='text']", timeout=15000)
            page.fill("input[name='text']", login_username)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
            page.wait_for_selector("input[name='password']", timeout=15000)
            page.fill("input[name='password']", login_password)
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)

            # Save cookies after login
            storage = context.storage_state()
            cookie_path.write_text(json.dumps(storage))
            print("Saved cookies to file.")

        # Go to user timeline
        page.goto(f"https://twitter.com/{user}")
        page.wait_for_timeout(5000)

        global START_DATE, END_DATE, TWITTER_USER
        START_DATE = start_date
        END_DATE = end_date
        TWITTER_USER = user

        single_pass_scrape(page, session)

    session.close()

if __name__ == "__main__":
    args = parse_args()

    user = args.user
    start_date_str = args.start_date
    end_date_str = args.end_date

    login_username = os.environ.get("TWITTER_USERNAME")
    login_password = os.environ.get("TWITTER_PASSWORD")

    if not login_username or not login_password:
        print("Error: Missing Twitter login credentials in environment variables.")
        exit(1)

    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    run_scraper(user, start_date, end_date, login_username, login_password)