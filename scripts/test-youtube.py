"""Synthetic API fixtures for tests only; never served by production."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hosting.youtube import LatestVideo, normalize, DEFAULT_CHANNEL


def fixture(vid='abcdefghijk', date='2026-01-01T00:00:00Z'):
    return {'id':vid,'snippet':{'channelId':DEFAULT_CHANNEL,'title':'آموزش Firefox 🔥 | Test', 'publishedAt':date,
        'thumbnails':{'maxres':{'url':f'https://i.ytimg.com/vi/{vid}/maxresdefault.jpg'},'high':{'url':f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'}}},
        'statistics':{'viewCount':'123456','likeCount':'765'},'contentDetails':{'duration':'PT3M2S'},
        'status':{'privacyStatus':'public','uploadStatus':'processed'}}


class VideoTests(unittest.TestCase):
    def make(self, directory=None):
        with patch.dict(os.environ, {'YOUTUBE_API_KEY':'synthetic-test-key','YOUTUBE_CHANNEL_ID':DEFAULT_CHANNEL}):
            return LatestVideo(directory)

    def test_exact_normalized_fields_and_missing_statistics(self):
        raw=fixture(); v=normalize(raw,DEFAULT_CHANNEL,time.time())
        self.assertEqual(v['title'],raw['snippet']['title'])
        self.assertEqual(v['publishedAt'],raw['snippet']['publishedAt'])
        self.assertEqual(v['views'],'123456'); self.assertEqual(v['likes'],'765')
        self.assertEqual(v['thumbnail'],raw['snippet']['thumbnails']['maxres']['url'])
        raw['statistics']={}; v=normalize(raw,DEFAULT_CHANNEL,time.time())
        self.assertIsNone(v['likes']); self.assertIsNone(v['views'])

    def test_reject_private_deleted_future_and_upcoming(self):
        variants=[]
        v=fixture();v['status']['privacyStatus']='private';variants.append(v)
        v=fixture();v['status']['uploadStatus']='deleted';variants.append(v)
        v=fixture(date='2099-01-01T00:00:00Z');variants.append(v)
        v=fixture();v['snippet']['liveBroadcastContent']='upcoming';variants.append(v)
        v=fixture();v['liveStreamingDetails']={'scheduledStartTime':'2026-01-01T00:00:00Z'};variants.append(v)
        v=fixture();v['snippet']['channelId']='other';variants.append(v)
        for v in variants:self.assertIsNone(normalize(v,DEFAULT_CHANNEL,time.time()))

    def test_all_pages_compared_by_actual_publication(self):
        client=self.make(); calls=[]
        def request(endpoint,**params):
            calls.append((endpoint,params))
            if endpoint=='channels':return {'items':[{'contentDetails':{'relatedPlaylists':{'uploads':'uploads'}}}]}
            if endpoint=='playlistItems':
                return {'items':[{'contentDetails':{'videoId':'abcdefghijk'}}], 'nextPageToken':'next'} if 'pageToken' not in params else {'items':[{'contentDetails':{'videoId':'zyxwvutsrqp'}}]}
            return {'items':[fixture()]} if params['id']=='abcdefghijk' else {'items':[fixture('zyxwvutsrqp','2026-02-01T00:00:00Z')]}
        client.request=request
        self.assertEqual(client.fetch_latest()['videoId'],'zyxwvutsrqp')
        self.assertEqual(len(calls),5)

    def test_failure_keeps_snapshot_and_success_empty_clears_it(self):
        client=self.make(); v=normalize(fixture(),DEFAULT_CHANNEL,time.time())
        client.cached=v
        with patch.object(client,'fetch_latest',side_effect=OSError):client.refresh()
        self.assertEqual(client.get()['video'],v);self.assertTrue(client.get()['stale'])
        with patch.object(client,'fetch_latest',return_value=None):client.refresh()
        self.assertEqual(client.get()['state'],'empty');self.assertIsNone(client.get()['video'])

    def test_cache_single_flight_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            client=self.make(directory)
            with patch.object(client,'fetch_latest',return_value=normalize(fixture(),DEFAULT_CHANNEL,time.time())):client.refresh()
            with patch.object(client,'request') as request:
                for _ in range(10):client.get()
                request.assert_not_called()
            restored=self.make(directory)
            self.assertEqual(restored.cached,client.cached)
            self.assertNotIn('synthetic-test-key',Path(directory,'youtube-cache.json').read_text())
            client.retry_at=0
            with patch('hosting.youtube.threading.Thread') as thread:
                client.get();client.get();thread.assert_called_once()

    def test_image_fallback_and_exact_id_binding(self):
        client=self.make();v=normalize(fixture(),DEFAULT_CHANNEL,time.time())
        client.image_sources[v['videoId']]=v['thumbnails']
        jpeg=b'\xff\xd8\xfftest'
        with patch('hosting.youtube.urllib.request.urlopen',side_effect=[OSError(),io.BytesIO(jpeg)]) as fetch:
            self.assertEqual(client.thumbnail(v['videoId']),jpeg)
            self.assertEqual(client.thumbnail(v['videoId']),jpeg)
            self.assertEqual(fetch.call_count,2)
            self.assertIn('hqdefault',fetch.call_args.args[0])
            self.assertIsNone(client.thumbnail('zyxwvutsrqp'))
            self.assertEqual(fetch.call_count,2)

    def test_no_key_uses_public_feed_automatically(self):
        client=self.make();client.key=''
        with patch.object(client,'fetch_feed',return_value=None) as feed, patch.object(client,'request') as request:
            client.refresh()
            self.assertEqual(client.get()['state'],'empty')
            feed.assert_called_once();request.assert_not_called()

    def test_feed_title_thumbnail_date_same_video_and_no_invented_stats(self):
        from hosting.youtube import parse_feed
        xml = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">'
        for vid, date in [('abcdefghijk','2026-01-01'),('zyxwvutsrqp','2026-02-01')]:
            xml += f'<entry><yt:videoId>{vid}</yt:videoId><yt:channelId>{DEFAULT_CHANNEL}</yt:channelId><title>Title &amp; exact</title><published>{date}T00:00:00Z</published><media:group><media:thumbnail url="https://i3.ytimg.com/vi/{vid}/hqdefault.jpg"/></media:group></entry>'
        video=parse_feed((xml+'</feed>').encode(),DEFAULT_CHANNEL)
        self.assertEqual(video['videoId'],'zyxwvutsrqp')
        self.assertIn(video['videoId'],video['thumbnail'])
        self.assertIn(video['videoId'],video['videoUrl'])
        self.assertEqual(video['title'],'Title & exact')
        self.assertEqual(video['publishedAt'],'2026-02-01T00:00:00Z')
        self.assertIsNone(video['views']);self.assertIsNone(video['likes'])

    def test_invalid_thumbnail_origin_is_not_proxied(self):
        raw=fixture();raw['snippet']['thumbnails']={'maxres':{'url':'http://127.0.0.1/private'}}
        self.assertEqual(normalize(raw,DEFAULT_CHANNEL,time.time())['thumbnails'],[])

if __name__=='__main__':unittest.main()
