"""Latest public Blue Knight upload, fetched without an API key."""
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

CHANNEL_URL = "https://www.youtube.com/@BlueKnight-Net/videos"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UCOUsLDQyNHhp_g7-jeZAJyg"
NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_video(xml):
    root = ET.fromstring(xml)
    for entry in root.findall("atom:entry", NS):
        video_id = entry.findtext("yt:videoId", "", NS)
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return {"ok": True, "videoId": video_id,
                    "title": entry.findtext("atom:title", "Blue Knight video", NS),
                    "url": "https://www.youtube.com/watch?v=" + video_id,
                    "thumbnail": "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg",
                    "published": entry.findtext("atom:published", "", NS), "stale": False}
    raise ValueError("No valid video in feed")


class LatestVideo:
    def __init__(self):
        self.cached = {"ok": False, "url": CHANNEL_URL, "stale": True}
        self.retry_at = 0
        self.lock = threading.Lock()
        self.thumbnail_lock = threading.Lock()
        self.thumbnail_id = None
        self.thumbnail_bytes = None
        self.thumbnail_retry_at = 0

    def thumbnail(self):
        video = self.get()
        video_id = video.get("videoId")
        if not video_id:
            return None
        with self.thumbnail_lock:
            if self.thumbnail_id == video_id:
                if self.thumbnail_bytes or time.monotonic() < self.thumbnail_retry_at:
                    return self.thumbnail_bytes
            self.thumbnail_id = video_id
            self.thumbnail_bytes = None
            try:
                # Only the feed's validated ID can select an image; never proxy a supplied URL.
                url = "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg"
                with urllib.request.urlopen(url, timeout=8) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024 or not data.startswith(b"\xff\xd8\xff"):
                    raise ValueError("Invalid thumbnail")
                self.thumbnail_bytes = data
            except (OSError, ValueError):
                pass
            self.thumbnail_retry_at = time.monotonic() + 300
            return self.thumbnail_bytes

    def get(self):
        with self.lock:
            if time.monotonic() < self.retry_at:
                return dict(self.cached)
            try:
                request = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    xml = response.read(1024 * 1024 + 1)
                if len(xml) > 1024 * 1024:
                    raise ValueError("Feed too large")
                self.cached = parse_video(xml)
            except (OSError, ValueError, ET.ParseError):
                self.cached = {**self.cached, "stale": True}
            # Failed fetches are cached too, so a YouTube outage never causes a request storm.
            self.retry_at = time.monotonic() + 300
            return dict(self.cached)
