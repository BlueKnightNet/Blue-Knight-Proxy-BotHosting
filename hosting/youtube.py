"""Automatic public-feed updates, optional API statistics, and video-bound thumbnails."""
import copy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit

LOG = logging.getLogger(__name__)
DEFAULT_CHANNEL = 'UCOUsLDQyNHhp_g7-jeZAJyg'


def parse_feed(raw, channel):
    ns = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
          'media': 'http://search.yahoo.com/mrss/'}
    root = ET.fromstring(raw)
    videos = []
    for entry in root.findall('a:entry', ns):
        vid = entry.findtext('yt:videoId', '', ns)
        published = entry.findtext('a:published', '', ns)
        stamp = timestamp(published)
        if (not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid)
                or entry.findtext('yt:channelId', '', ns) != channel
                or stamp is None or stamp > time.time()):
            continue
        title = entry.findtext('a:title', None, ns)
        if title is None:
            continue
        urls = [node.get('url') for node in entry.findall('media:group/media:thumbnail', ns)
                if image_url(node.get('url'))]
        videos.append({'videoId': vid, 'title': title, 'publishedAt': published,
                       'thumbnail': urls[0] if urls else None, 'thumbnails': urls,
                       'views': None, 'likes': None, 'duration': None,
                       'videoUrl': 'https://www.youtube.com/watch?v=' + vid})
    return max(videos, key=lambda v: timestamp(v['publishedAt']), default=None)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.timestamp() if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def image_url(value):
    if not isinstance(value, str):
        return False
    u = urlsplit(value)
    return u.scheme == 'https' and (bool(re.fullmatch(r'i[0-9]?\.ytimg\.com', u.hostname or '')) or u.hostname == 'img.youtube.com') and not u.username and not u.password and not u.port


def normalize(video, channel, now):
    snippet, status = video.get('snippet', {}), video.get('status', {})
    live = video.get('liveStreamingDetails', {})
    published = timestamp(snippet.get('publishedAt'))
    if (not re.fullmatch(r'[A-Za-z0-9_-]{11}', video.get('id', ''))
            or snippet.get('channelId') != channel or status.get('privacyStatus') != 'public'
            or status.get('uploadStatus') not in ('processed', 'uploaded')
            or published is None or published > now
            or snippet.get('liveBroadcastContent') == 'upcoming'
            or (live.get('scheduledStartTime') and not live.get('actualStartTime'))
            or not isinstance(snippet.get('title'), str)):
        return None
    thumbnails = snippet.get('thumbnails', {})
    urls = [thumbnails[k]['url'] for k in ('maxres', 'standard', 'high', 'medium', 'default')
            if isinstance(thumbnails.get(k), dict) and image_url(thumbnails[k].get('url'))]
    stats = video.get('statistics', {})
    def count(key):
        value = stats.get(key)
        return str(value) if isinstance(value, (int, str)) and re.fullmatch(r'\d+', str(value)) else None
    return {'videoId': video['id'], 'title': snippet['title'], 'publishedAt': snippet['publishedAt'],
            'thumbnail': urls[0] if urls else None, 'thumbnails': urls,
            'views': count('viewCount'), 'likes': count('likeCount'),
            'duration': video.get('contentDetails', {}).get('duration'),
            'videoUrl': 'https://www.youtube.com/watch?v=' + video['id']}


class LatestVideo:
    def __init__(self, directory=None):
        self.key = os.environ.get('YOUTUBE_API_KEY', '').strip()
        self.channel = os.environ.get('YOUTUBE_CHANNEL_ID', DEFAULT_CHANNEL).strip()
        try:
            self.interval = max(300, min(86400, int(os.environ.get('YOUTUBE_CACHE_SECONDS', '600'))))
        except ValueError:
            self.interval = 600
        self.lock = threading.Lock()
        self.image_lock = threading.Lock()
        self.cached = None
        self.fetched_at = 0
        self.retry_at = 0
        self.refreshing = False
        self.failed = False
        self.images = {}
        self.image_sources = {}
        self.path = Path(directory) / 'youtube-cache.json' if directory else None
        if self.path and self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                if saved['channel'] == self.channel:
                    self.cached, self.fetched_at = saved['video'], saved['fetchedAt']
                    if self.cached:
                        self.image_sources[self.cached['videoId']] = self.cached['thumbnails']
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def request(self, endpoint, **params):
        url = 'https://www.googleapis.com/youtube/v3/' + endpoint + '?' + urlencode(params)
        req = urllib.request.Request(url, headers={'X-Goog-Api-Key': self.key, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Oversized API response')
        result = json.loads(raw)
        if 'error' in result:
            raise ValueError('API error')
        return result

    def fetch_latest(self):
        if not self.key:
            return self.fetch_feed()
        channels = self.request('channels', part='contentDetails', id=self.channel)
        items = channels.get('items', [])
        if not items:
            return None
        playlist = items[0]['contentDetails']['relatedPlaylists']['uploads']
        best, token, seen = None, '', set()
        now = time.time()
        # Scan all uploads: playlist order is not a publication-date guarantee.
        while True:
            params = {'part': 'contentDetails', 'playlistId': playlist, 'maxResults': 50}
            if token:
                params['pageToken'] = token
            page = self.request('playlistItems', **params)
            ids = [v.get('contentDetails', {}).get('videoId', '') for v in page.get('items', [])]
            ids = [v for v in ids if re.fullmatch(r'[A-Za-z0-9_-]{11}', v)]
            if ids:
                videos = self.request('videos', part='snippet,statistics,contentDetails,status,liveStreamingDetails', id=','.join(ids))
                for raw in videos.get('items', []):
                    video = normalize(raw, self.channel, now)
                    if video and (best is None or timestamp(video['publishedAt']) > timestamp(best['publishedAt'])):
                        best = video
            token = page.get('nextPageToken')
            if not token:
                return best
            if token in seen:
                raise ValueError('Repeated playlist page')
            seen.add(token)

    def fetch_feed(self):
        url = 'https://www.youtube.com/feeds/videos.xml?' + urlencode({'channel_id': self.channel})
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Oversized feed')
        return parse_feed(raw, self.channel)

    def refresh(self):
        try:
            video = self.fetch_latest()
            fetched = time.time()
            with self.lock:
                self.cached, self.fetched_at, self.failed = video, fetched, False
                if video:
                    self.image_sources[video['videoId']] = video['thumbnails']
                    while len(self.image_sources) > 4:
                        del self.image_sources[next(iter(self.image_sources))]
                else:
                    self.image_sources.clear()
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temp = self.path.with_suffix('.tmp')
                    temp.write_text(json.dumps({'channel': self.channel, 'video': video, 'fetchedAt': fetched}), encoding='utf-8')
                    temp.replace(self.path)
                except OSError:
                    LOG.warning('YouTube cache could not be saved')
        except Exception as error:
            # Never log request URLs, response bodies, or credentials.
            LOG.warning('YouTube refresh failed: %s (HTTP %s)', type(error).__name__, getattr(error, 'code', 'n/a'))
            with self.lock:
                self.failed = True
        finally:
            with self.lock:
                self.retry_at = time.monotonic() + self.interval
                self.refreshing = False

    def get(self):
        with self.lock:
            configured = bool(re.fullmatch(r'UC[A-Za-z0-9_-]{22}', self.channel))
            if not configured:
                return {'ok': False, 'state': 'unconfigured', 'refreshAfter': self.interval}
            if not self.refreshing and time.monotonic() >= self.retry_at:
                self.refreshing = True
                threading.Thread(target=self.refresh, daemon=True).start()
            state = 'ready' if self.cached else ('loading' if self.refreshing else 'error' if self.failed else 'empty')
            return {'ok': bool(self.cached), 'state': state, 'video': copy.deepcopy(self.cached),
                    'stale': bool(self.cached and (self.failed or self.refreshing)), 'fetchedAt': self.fetched_at,
                    'refreshAfter': 3 if self.refreshing else max(1, int(self.retry_at - time.monotonic()))}

    def thumbnail(self, video_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            return None
        with self.lock:
            urls = list(self.image_sources.get(video_id, []))
        if not urls:
            return None
        with self.image_lock:
            cached = self.images.get(video_id)
            if cached and cached[1] > time.monotonic():
                return cached[0]
            data = None
            for url in urls:
                if not image_url(url):
                    continue
                try:
                    with urllib.request.urlopen(url, timeout=8) as response:
                        candidate = response.read(2 * 1024 * 1024 + 1)
                    if len(candidate) > 2 * 1024 * 1024 or not candidate.startswith(b'\xff\xd8\xff'):
                        continue
                    data = candidate
                    break
                except (OSError, ValueError):
                    continue
            self.images[video_id] = (data, time.monotonic() + (self.interval if data else 300))
            while len(self.images) > 4:
                del self.images[next(iter(self.images))]
            return data
