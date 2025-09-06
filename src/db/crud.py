import os
import requests
from sqlalchemy.orm import Session
from src.db.models import Tweet

IMAGES_DIR = 'images'  # local folder to save images
os.makedirs(IMAGES_DIR, exist_ok=True)

def save_image_locally(image_url: str, tweet_id: str) -> str:
    """
    Downloads the image from image_url and saves it locally.
    Returns the local file path.
    """
    ext = image_url.split('.')[-1].split('?')[0]
    # Create a filename using tweet_id + hash of URL to avoid duplicates
    filename = f"{tweet_id}_{abs(hash(image_url))}.{ext}"
    local_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(local_path):
        try:
            resp = requests.get(image_url)
            resp.raise_for_status()
            with open(local_path, 'wb') as f:
                f.write(resp.content)
        except Exception as e:
            print(f"Failed to download image {image_url}: {e}")
            return None
    return local_path

def store_tweet(tweet_data: dict, session: Session, scraper_fn) -> Tweet:
    """
    Stores a tweet and related quoted tweets into the DB.
    
    Args:
        tweet_data (dict): Parsed tweet info, expected keys:
            - tweet_id (str)
            - user_id (str)
            - username (str)
            - text (str)
            - created_at (datetime)
            - in_reply_to_tweet_id (str or None)
            - quoted_tweet_id (str or None)
            - image_urls (list of str)
            - has_video (bool)
        session (Session): SQLAlchemy session
        scraper_fn (function): Function(tweet_id) -> tweet_data dict for fetching missing quoted tweets
        
    Returns:
        Tweet object stored in DB
    """
    # 1. Recursively store quoted tweet if missing
    quoted_id = tweet_data.get('quoted_tweet_id')
    if quoted_id:
        existing_quoted = session.query(Tweet).get(quoted_id)
        if not existing_quoted:
            print(f"Quoted tweet {quoted_id} not found in DB, scraping now...")
            quoted_data = scraper_fn(quoted_id)
            if quoted_data:
                store_tweet(quoted_data, session, scraper_fn)
            else:
                print(f"Warning: Could not fetch quoted tweet {quoted_id}")

    # 2. Download images locally
    local_image_paths = []
    for img_url in tweet_data.get('image_urls', []):
        local_path = save_image_locally(img_url, tweet_data['tweet_id'])
        if local_path:
            local_image_paths.append(local_path)

    # 3. Check if tweet exists to avoid duplicates
    existing_tweet = session.query(Tweet).get(tweet_data['tweet_id'])
    if existing_tweet:
        # Optionally update existing tweet here
        return existing_tweet

    # 4. Create Tweet object
    tweet = Tweet(
        tweet_id = tweet_data['tweet_id'],
        user_id = tweet_data['user_id'],
        username = tweet_data['username'],
        text = tweet_data.get('text', ''),
        created_at = tweet_data['created_at'],
        in_reply_to_tweet_id = tweet_data.get('in_reply_to_tweet_id'),
        quoted_tweet_id = quoted_id,
        image_paths = tweet_data.get('image_paths', ''),
        video_username = tweet_data['username'] if tweet_data.get('has_video') else None,
    )

    # 5. Add and commit to DB
    session.add(tweet)
    session.commit()

    print(f"Stored tweet {tweet.tweet_id} by @{tweet.username} into DB.")
    return tweet