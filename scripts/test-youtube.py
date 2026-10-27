import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hosting.youtube import LatestVideo, parse_video

FEED = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>rFmtnT0xeWg</yt:videoId><title>New &amp; useful</title><published>2026-10-27T10:00:00Z</published></entry>
<entry><yt:videoId>abcdefghijk</yt:videoId><title>Older</title></entry></feed>'''


class VideoTests(unittest.TestCase):
    def test_first_entry_and_xml_entities(self):
        video = parse_video(FEED)
        self.assertEqual(video['title'], 'New & useful')
        self.assertEqual(video['url'], 'https://www.youtube.com/watch?v=rFmtnT0xeWg')

    def test_invalid_id_cannot_produce_external_link(self):
        with self.assertRaises(ValueError):
            parse_video(FEED.replace(b'rFmtnT0xeWg', b'https://bad').replace(b'abcdefghijk', b'../bad'))

    def test_cached_success_and_stale_fallback(self):
        cache = LatestVideo()
        with patch('hosting.youtube.urllib.request.urlopen', return_value=io.BytesIO(FEED)) as fetch:
            first = cache.get()
            self.assertEqual(first, cache.get())
            fetch.assert_called_once()
        cache.retry_at = 0
        with patch('hosting.youtube.urllib.request.urlopen', side_effect=OSError) as fetch:
            stale = cache.get()
            self.assertTrue(stale['stale'])
            self.assertEqual(stale['videoId'], first['videoId'])
            cache.get()
            fetch.assert_called_once()

    def test_outage_without_cache_keeps_channel_link(self):
        with patch('hosting.youtube.urllib.request.urlopen', side_effect=OSError):
            result = LatestVideo().get()
        self.assertFalse(result['ok'])
        self.assertEqual(result['url'], 'https://www.youtube.com/@BlueKnight-Net/videos')


if __name__ == '__main__':
    unittest.main()
