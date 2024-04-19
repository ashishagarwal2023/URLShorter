import logging
import os
import random
import sqlite3
import string
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

import schedule
from dotenv import load_dotenv
from flask import (
	Flask,
	render_template,
	redirect,
	request,
	g,
	jsonify,
	)

import valid
from delete_expired import delete_expired_urls
from qr import qr

load_dotenv()

# Variables, should be modified to your needs!
black_shorts = [
    "new",
    "home",
    "website",
    "site",
    "about",
    "elepha",
    "details",
    "contact",
]
LOGIN_DB = os.getenv("LOGIN_DB")
dir_name = os.getenv("dir_name")
DATABASE = os.getenv("DATABASE")
log_file_path = os.getenv("log_file_path")
SCHEMA_FILE = os.getenv("SCHEMA_FILE")
# captchaSiteKey = os.getenv("captchaSiteKey")
spoofDomain = os.getenv("spoofDomain")
secretKey = os.getenv("secretKey")

app = Flask(__name__)


def job():
    delete_expired_urls()


schedule.every(1).days.do(job)


def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)


scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
scheduler_thread.start()


def recents(length=6):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        f"SELECT short_url, original_url, views, inserted_at FROM short_urls WHERE public = 1 ORDER BY "
        f"datetime("
        f"inserted_at) DESC LIMIT {length}"
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def getTime(add):
    now = datetime.now()
    return now + timedelta(days=add)


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        try:
            db = g._database = sqlite3.connect(DATABASE)
        except sqlite3.OperationalError:
            print("Restoring Database")
            os.execl(sys.executable, sys.executable, *sys.argv)
        db.execute("PRAGMA foreign_keys = ON")
    return db


def close_db(exception=None):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with app.open_resource("schema.sql", mode="r") as f:
        db.cursor().executescript(f.read())
    db.commit()


def cutText(text, length):
    if len(text) <= length:
        return text
    else:
        return text[: (length - 3)] + "..."


log_dir = os.path.dirname(log_file_path)
os.makedirs(log_dir, exist_ok=True)

if not os.path.exists(log_file_path):
    open(log_file_path, "a").close()

log_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s: %(message)s", datefmt="%d %b %Y at %H:%M:%S"
)
log_handler = TimedRotatingFileHandler(
    log_file_path, when="midnight", interval=1, backupCount=30
)
log_handler.setFormatter(log_formatter)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.DEBUG)


def gen_short(length=6):
    chars = string.ascii_letters + string.digits
    short_id = "".join(random.choice(chars) for _ in range(length))
    while short_id in black_shorts:
        short_id = "".join(random.choice(chars) for _ in range(length))
    return short_id


def shortUrl(url, length, visb, expiryDate):
    db = get_db()
    expiryClicks = int(request.form.get("expiryClicks"))
    if not float(expiryDate) == 0:
        expiryDate = getTime(float(expiryDate))
    else:
        expiryDate = 0
    visb = 1 if visb == "on" else 0
    cursor = db.cursor()
    cursor.execute("SELECT short_url FROM short_urls WHERE original_url=?", (url,))
    existing_short_url = cursor.fetchone()

    if existing_short_url:
        cursor.close()
        return f"{dir_name}/{existing_short_url[0]}"

    customSlug = request.form.get("slugInput")
    for _ in range(customSlug.count("X")):
        customSlug = customSlug.replace("X", gen_short(1), 1)

    if customSlug and not customSlug.isspace():
        cursor.execute("SELECT * FROM short_urls WHERE short_url=?", (customSlug,))
        existing_short_url = cursor.fetchone()
        if not existing_short_url:
            short_url = customSlug
        else:
            short_url = gen_short(length)
    else:
        short_url = gen_short(length)

    short_url = customSlug
    if not customSlug or existing_short_url:
        while True:
            cursor.execute("SELECT * FROM short_urls WHERE short_url=?", (short_url,))
            existing_short_url = cursor.fetchone()
            if not existing_short_url:
                break
            short_url = gen_short(length)
    cursor.execute(
        "INSERT INTO short_urls (short_url, original_url, public, expiryClicks, expiryDate) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (short_url, url, visb, expiryClicks, expiryDate),
    )
    db.commit()
    cursor.close()
    return f"{dir_name}/{short_url}"


@app.route("/", methods=["GET", "POST"])
def index():
    return redirect("https://github.com/ashishagarwal2023/cutyoururl")


@app.route("/recents", methods=["GET", "POST"])
def recentsRoute():
    data = recents(5)
    transformed_data = []

    for entry in data:
        transformed_data.append(
            {"id": entry[0], "dest": entry[1], "views": entry[2], "created": entry[3]}
        )

    return jsonify(transformed_data)


@app.route("/short", methods=["POST", "GET"])
def short():
    try:
        url = request.form.get("url")
        expiryDate = float(request.form.get("expiryDate"))
        isPublic = request.form.get("public")

        if valid.verify(url):
            pass
        else:
            return render_template(
                "generated.jinja",
                data=["err", ""],
            )
        db = get_db()
        Vcursor = db.cursor()
        Vcursor.execute("SELECT views FROM short_urls WHERE original_url=?", (url,))
        views = Vcursor.fetchone()

        app.logger.info(f"POST request received for URL: {url}")

        short_url = shortUrl(url, 6, visb=isPublic, expiryDate=expiryDate)
        if views == None:
            app.logger.info(f"Generated new short URL: /{short_url}\n")
        else:
            app.logger.info(f"Returning already-generated URL: /{short_url}\n")
        full = f"{spoofDomain}{short_url}"
        views = views[0] if views else 0
        qrURI = qr(full)
        app.logger.info(f"Generated QR Code URI from: {full}\n")
        croppedURL = cutText(url, 30)
        return jsonify(
            {
                "full": full,
                "url": url,
                "views": views,
                "qrURI": qrURI,
                "cropped": croppedURL,
                "path": short_url,
            }
        )

    except Exception as e:
        app.logger.error(f"Server exception during shorting: {e}\n")
        print(e)
        return jsonify({"error": f"{e}"}), 500


@app.route(f"/{dir_name}/<short_url>")
def redr_url(short_url):
    app.logger.info(f"Recieved to redirect for short with ID: {short_url}\n")
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT original_url, views, expiryClicks FROM short_urls WHERE short_url=?",
        (short_url,),
    )
    url_info = cursor.fetchone()

    if url_info:
        original_url, views, expiryClicks = url_info
        cursor.execute(
            "UPDATE short_urls SET views=? WHERE short_url=?",
            (
                views,
                short_url,
            ),
        )
        db.commit()
        cursor.close()
        app.logger.info(f"Redirecting to original URL: {original_url}")
        return jsonify({"dest": original_url}), 200
    else:
        app.logger.error("Short URL not found")
        return jsonify({"error": 404}), 404


@app.errorhandler(404)
def page_not_found(e):
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
