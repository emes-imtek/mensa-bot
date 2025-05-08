import json
import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import schedule
from dotenv import load_dotenv
from mattermostdriver import Driver
from PIL import Image
from playwright.sync_api import sync_playwright

# === GLOBAL CONSTANTS ===
MENU_URL = "https://www.swfr.de/essen/mensen-cafes-speiseplaene/freiburg/mensa-flugplatz-cafe-flugplatz"
MORNING_TIME = "09:00"
REMINDER_TIME = "11:11"
TIMEZONE = "Europe/Berlin"

# CSS selector for the visible tab in the menu
VISIBLE_TAB_SELECTOR = "#tabsWeekdaysMenu .menu-tagesplan:not([style*='display: none'])"

# File paths
LOG_PATH = "mensa.log"
POST_ID_PATH = "mensa_post.json"
SCREENSHOT_FULL = "full_page.png"
SCREENSHOT_CROPPED = "mensa_screenshot.png"

# Logging rotation config
LOG_MAX_SIZE = 1_000_000  # 1 MB
LOG_BACKUP_COUNT = 3

# Margin for cropping the screenshot
MARGIN_TOP = 18
MARGIN_LEFT = 25

# === LOGGING SETUP ===


def setup_logging():
    LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
    LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

    rotating_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_SIZE,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
        handlers=[
            logging.StreamHandler(),
            rotating_handler
        ]
    )

# === MATTERMOST UTILITIES ===


class Mattermost:
    def __init__(self):
        load_dotenv(dotenv_path=Path(__file__).parent / "config.env")

        self.url = os.getenv("MATTERMOST_URL")
        self.token = os.getenv("MATTERMOST_TOKEN")
        self.channel = os.getenv("MATTERMOST_CHANNEL")
        self.team = os.getenv("MATTERMOST_TEAM")

        missing = [k for k, v in {
            "MATTERMOST_URL": self.url,
            "MATTERMOST_TOKEN": self.token,
            "MATTERMOST_CHANNEL": self.channel,
            "MATTERMOST_TEAM": self.team
        }.items() if not v]

        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}")

        self.driver = Driver({
            'url': self.url,
            'token': self.token,
            'scheme': 'https',
            'port': 443
        })
        self.driver.login()
        self.channel_id = self.driver.channels.get_channel_by_name_and_team_name(
            self.team, self.channel)["id"]

    def post(self, message, file_ids=None, root_id=None):
        try:
            return self.driver.posts.create_post(options={
                'channel_id': self.channel_id,
                'message': message,
                'file_ids': file_ids or [],
                'root_id': root_id
            })
        except Exception:
            logging.exception("❌ Failed to post message to Mattermost.")
            return None

    def upload_file(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                resp = self.driver.files.upload_file(
                    channel_id=self.channel_id,
                    files={'files': (os.path.basename(
                        file_path), f, 'image/png')}
                )
            return resp['file_infos'][0]['id']
        except Exception:
            logging.exception(f"❌ Failed to upload file: {file_path}")
            return None

# === FILE HANDLING ===


def save_post_id(post_id):
    """Saves the Mattermost post ID with the current date."""
    with open(POST_ID_PATH, "w") as f:
        json.dump({
            "post_id": post_id,
            "date": datetime.now().date().isoformat()
        }, f)


def load_post_id():
    """Returns today's post ID if it exists and is fresh."""
    try:
        with open(POST_ID_PATH) as f:
            data = json.load(f)
            if data.get("date") == datetime.today().strftime("%Y-%m-%d"):
                return data.get("post_id")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def delete_post_id():
    """Removes the post ID file."""
    if os.path.exists(POST_ID_PATH):
        os.remove(POST_ID_PATH)
        logging.info("🧹 Deleted post ID after reminder.")


def load_js_script(filename: str) -> str:
    """Reads and returns JavaScript code from a file."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"⚠️ JavaScript file not found: {filename}")
        return ""

# === PAGE PARSING LOGIC ===


def is_menu_available(page):
    """Checks if a menu is available today."""
    visible_tab = page.query_selector(VISIBLE_TAB_SELECTOR)
    if visible_tab and "heute keine essensausgabe" not in visible_tab.inner_text().lower():
        return visible_tab
    return None

# === SCREENSHOT AND UPLOAD ===


def capture_and_send_screenshot():
    """Captures and uploads the menu screenshot. Returns Mattermost file ID."""
    logging.info("📸 Starting screenshot and upload...")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1279, "height": 2000})
                page.goto(MENU_URL)
                page.wait_for_timeout(3000)

                visible_tab = is_menu_available(page)
                if not visible_tab:
                    logging.warning("⚠️  No menu available today.")
                    return None

                # Prepare page DOM
                if not JS_SCRIPT:
                    logging.warning(
                        "⚠️ JavaScript script is empty. Skipping evaluation.")
                else:
                    page.evaluate(JS_SCRIPT)

                # Full screenshot
                page.screenshot(path=SCREENSHOT_FULL, full_page=True)

                box = visible_tab.bounding_box()
                if not box:
                    logging.error("❌ Failed to get bounding box.")
                    return None

                x = max(int(box["x"]) - MARGIN_LEFT, 0)
                y = max(int(box["y"]) - MARGIN_TOP, 0)
                width = int(box["width"]) + MARGIN_LEFT * 2
                height = int(box["height"]) + MARGIN_TOP * 2

                image = Image.open(SCREENSHOT_FULL)
                cropped = image.crop((x, y, x + width, y + height))
                cropped.save(SCREENSHOT_CROPPED)
            finally:
                browser.close()

        file_id = mm.upload_file(SCREENSHOT_CROPPED)
        logging.info("✅ Screenshot uploaded.")
        return file_id

    except Exception:
        logging.exception("❌ Unexpected error during screenshot process.")
        mm.post(
            "⚠️ Heute konnte leider kein Screenshot des Speiseplans erstellt werden.")
        return None

# === DAILY POSTING TASKS ===


def is_weekend():
    return datetime.today().weekday() >= 5  # Saturday = 5, Sunday = 6


def post_morning_message():
    if is_weekend():
        logging.info("🚫 Skipping morning post on weekend.")
        return

    logging.info("🌅 Posting morning menu preview...")
    file_id = capture_and_send_screenshot()
    if not file_id:
        return

    post = mm.post(
        "🍽️ Guten Morgen! Hier ist der Speiseplan für heute:", file_ids=[file_id])
    if post:
        save_post_id(post["id"])
        logging.info("✅ Morning menu post successful.")


def post_reminder_message():
    if is_weekend():
        logging.info("🚫 Skipping reminder post on weekend.")
        return

    logging.info("🔁 Checking if reminder is needed...")

    post_id = load_post_id()
    if post_id:
        post = mm.post(
            "@all 🍽️ Auf geht's – schnell zur Mensa, bevor alles weg ist!",
            root_id=post_id
        )
        if post:
            logging.info("✅ Reminder posted.")
            delete_post_id()
        else:
            logging.warning("⚠️ Reminder could not be posted.")
    else:
        logging.info("ℹ️ No valid post ID for today — skipping reminder.")


# === SCHEDULER ===
if __name__ == "__main__":
    # === Initialize Logging ===
    setup_logging()

    # === Load Mattermost configuration ===
    mm = Mattermost()

    # === Load JavaScript once ===
    JS_SCRIPT = load_js_script("javascript.js")
    if not JS_SCRIPT:
        logging.critical(
            "❌ Required JavaScript file is missing or empty. Exiting.")
        exit(1)

    # === Scheduler Setup ===
    logging.info("📅 Starting Mensa bot scheduler...")

    schedule.every().day.at(MORNING_TIME, TIMEZONE).do(post_morning_message)
    schedule.every().day.at(REMINDER_TIME, TIMEZONE).do(post_reminder_message)

    for job in schedule.jobs:
        logging.info(
            f"⏰ Scheduled: {job.job_func.__name__} at {job.at_time.strftime('%H:%M')} {TIMEZONE}")

    logging.info(f"📝 Logging to: {os.path.abspath(LOG_PATH)}")
    logging.info("🚀 Scheduler is now running. Press Ctrl+C to stop.")

    try:
        last_logged_next_time = None  # <-- track last time we logged sleep time

        while True:
            schedule.run_pending()

            next_run = schedule.next_run()
            if next_run and last_logged_next_time != next_run:
                formatted = next_run.astimezone().strftime('%d.%m.%Y %H:%M:%S %z')
                logging.info(f"💤 Sleeping until next task at {formatted}")
                last_logged_next_time = next_run

            time.sleep(60)

    except KeyboardInterrupt:
        logging.info("🛑 Scheduler stopped by user.")
