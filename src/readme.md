

# Xscraper

## Overview

Xscraper is a Twitter/X timeline archiving tool that lets you:
- Scrape tweets (including quoted tweets, with images) for any user and date range.
- Save tweet data and images to a local database and organized folders.
- Browse your collected tweets in a modern web interface with search and filtering.

---

## 1. Setup

1. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** in the project root with your Twitter/X credentials:
   ```
   TWITTER_USERNAME=your_x_username
   TWITTER_PASSWORD=your_x_password
   ```

---

## 2. Scraping Tweets

Scrape tweets for any public or private account you have access to.

**Command syntax:**
```
python src/scraper/scraper.py --user TARGET_USERNAME --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```
- `--user` is the Twitter/X handle (without the `@`).
- `--start-date` and `--end-date` are in `YYYY-MM-DD` format.

**Example:**
```
python src/scraper/scraper.py --user Mistery5387057 --start-date 2025-08-01 --end-date 2025-08-01
```

- Tweets and images are saved to your local database and into `images/YYYY-MM-DD/` subfolders.

**Notes:**
- Login is automatic; cookies are saved for future sessions.
- Quoted tweets are saved as independent records, with their own images and metadata.

---

## 3. Browsing Tweets in Your Web Browser

Xscraper includes a web frontend to browse, search, and filter all archived tweets.

### **To start the web app:**
1. Go to your project root.
2. Run:
   ```
   uvicorn app:app --reload
   ```
   *(Or use `python src/app.py` if your app is set up that way.)*

3. Open your browser to:
   ```
   http://127.0.0.1:8000/
   ```

### **Web Features:**
- Search by user, date range, or keyword.
- View tweet text, quoted tweets, and images.
- Images are shown from `images/YYYY-MM-DD/`.
- Click a tweet for full details, including quotes and all associated images.

---

## 4. Folder Structure

```
src/
  scraper/
    scraper.py
  db/
    models.py
    crud.py
    session.py
  static/
    (frontend CSS, JS, images)
  templates/
    (HTML for the frontend)
images/
  YYYY-MM-DD/
    tweetid_xxx.jpg
twitter_cookies.json
.env
app.py
requirements.txt
```

---

## 5. FAQ

- **Q: I see `Invalid URL ... No scheme supplied`?**
  - A: The scraper skips local file paths and only downloads new images.
- **Q: Will it scrape quoted tweets?**
  - A: Yes! Quoted tweets are archived as full, independent entries (one level deep).
- **Q: Can I rerun the scraper on the same day or user?**
  - A: Yes—already archived tweets are automatically skipped.

---

For more information, see code comments or contact the project maintainer.