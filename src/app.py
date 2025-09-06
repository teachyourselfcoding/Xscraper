from flask import Flask, render_template, request, send_from_directory
from src.db.session import SessionLocal
from src.db.models import Tweet
import datetime
from pathlib import Path
from sqlalchemy.orm import joinedload

app = Flask(__name__)
IMAGES_DIR = Path(__file__).parent.parent / "images"

from markupsafe import Markup, escape

@app.template_filter('nl2br')
def nl2br_filter(s):
    if s is None:
        return ''
    return Markup(escape(s).replace('\n', '<br>'))

# Add basename filter
@app.template_filter('basename')
def basename_filter(s):
    import os
    if not s:
        return ''
    return os.path.basename(s)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")

        try:
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        except Exception:
            start_date = None
            end_date = None

        return search_results(username, start_date, end_date)
    return render_template("index.html")

def search_results(username, start_date, end_date):
    session = SessionLocal()
    query = session.query(Tweet)

    if username:
        query = query.filter(Tweet.username.ilike(f"%{username}%"))
    if start_date:
        query = query.filter(Tweet.created_at >= datetime.datetime.combine(start_date, datetime.time.min))
    if end_date:
        query = query.filter(Tweet.created_at <= datetime.datetime.combine(end_date, datetime.time.max))

    tweets = query.options(joinedload(Tweet.quoted_tweet)).order_by(Tweet.created_at.desc()).all()
    session.close()

    return render_template("results.html", tweets=tweets, images_dir=str(IMAGES_DIR))

@app.route("/images/<path:filename>")
def images(filename):
    return send_from_directory(IMAGES_DIR, filename)

if __name__ == "__main__":
    app.run(debug=True)