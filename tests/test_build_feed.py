import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_feed as bf  # noqa: E402

CONFIG = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config.json")))
CITIES = [
    {"name": "Sydney", "country": "Australia", "countryCode": "AU", "latitude": -33.869, "longitude": 151.209, "timeZone": "Australia/Sydney"},
    {"name": "Tokyo", "country": "Japan", "countryCode": "JP", "latitude": 35.676, "longitude": 139.650, "timeZone": "Asia/Tokyo"},
]


def video(vid, title, live=True, embeddable=True, ended=False, lat=None):
    v = {"id": vid,
         "snippet": {"title": title, "description": "", "channelTitle": "Cam Channel", "liveBroadcastContent": "live" if live else "none"},
         "status": {"embeddable": embeddable, "privacyStatus": "public"},
         "liveStreamingDetails": {"actualStartTime": "2026-01-01T00:00:00Z", **({"actualEndTime": "x"} if ended else {})}}
    if lat is not None:
        v["recordingDetails"] = {"location": {"latitude": lat, "longitude": 151.2}}
    return v


class FakeYouTube:
    def __init__(self, search_results, videos, quota_after_searches=None):
        self.search_results, self.videos = search_results, {v["id"]: v for v in videos}
        self.searches, self.quota_after = 0, quota_after_searches

    def __call__(self, endpoint, params):
        if endpoint == "search":
            if self.quota_after is not None and self.searches >= self.quota_after:
                raise bf.QuotaExceeded()
            self.searches += 1
            city = params["q"].split(" live cam")[0]
            ids = self.search_results.get(city, [])
            return {"items": [{"id": {"videoId": i}} for i in ids]}
        if endpoint == "videos":
            return {"items": [self.videos[i] for i in params["id"].split(",") if i in self.videos]}
        raise AssertionError(endpoint)


class BuildFeedTests(unittest.TestCase):
    today = datetime.date(2026, 10, 11)

    def test_filters_keep_only_live_embeddable_webcams(self):
        yt = FakeYouTube({"Sydney": ["a1", "b2", "c3", "d4", "e5", "x9"]}, [
            video("a1", "🔴 Sydney Harbour Live Cam 24/7", lat=-33.857),
            video("b2", "Sydney beach webcam", embeddable=False),
            video("x9", "Random city webcam 24/7"),
            video("c3", "Opera house camera", live=False),
            video("d4", "Lofi beats to study - live"),
            video("e5", "Bondi webcam", ended=True),
        ])
        feed, used, searched, errors = bf.build(yt, CITIES, CONFIG, previous=[], manual=[], today=self.today)
        self.assertEqual([c["youtubeVideoId"] for c in feed], ["a1"])
        cam = feed[0]
        self.assertEqual(cam["name"], "Sydney Harbour Live Cam 24/7", "Emoji removed from titles")
        self.assertEqual(cam["latitude"], -33.857, "Uses the video's own location when available")
        self.assertEqual(cam["countryCode"], "AU")
        self.assertEqual(cam["player"], "youtube")
        self.assertLessEqual(used, CONFIG["daily_quota_budget"])

    def test_previous_streams_kept_only_while_live(self):
        previous = [
            {"id": "yt-old1", "youtubeVideoId": "old1", "latitude": 35.67, "longitude": 139.65},
            {"id": "yt-old2", "youtubeVideoId": "old2", "latitude": 35.67, "longitude": 139.65},
        ]
        yt = FakeYouTube({}, [video("old1", "Tokyo Shibuya crossing live camera"), video("old2", "Tokyo webcam", ended=True)])
        feed, *_ = bf.build(yt, CITIES, CONFIG, previous=previous, manual=[], today=self.today)
        self.assertEqual([c["youtubeVideoId"] for c in feed], ["old1"])
        self.assertEqual(feed[0]["city"], "Tokyo")

    def test_manual_entries_always_first_and_not_duplicated(self):
        manual = [{"id": "yt-mine", "name": "My cam", "city": "Sydney", "country": "Australia",
                   "latitude": -33.8, "longitude": 151.2, "player": "youtube", "youtubeVideoId": "a1"}]
        yt = FakeYouTube({"Sydney": ["a1"]}, [video("a1", "Sydney Harbour live cam")])
        feed, *_ = bf.build(yt, CITIES, CONFIG, previous=[], manual=manual, today=self.today)
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["id"], "yt-mine")

    def test_quota_during_search_keeps_partial_results(self):
        yt = FakeYouTube({"Sydney": ["a1"], "Tokyo": ["t1"]},
                         [video("a1", "Sydney Harbour live cam"), video("t1", "Tokyo live camera")], quota_after_searches=1)
        feed, used, searched, errors = bf.build(yt, CITIES, CONFIG, previous=[], manual=[], today=self.today)
        self.assertEqual(searched, 1)
        self.assertEqual(len(feed), 1)
        self.assertTrue(any("quota" in e.lower() for e in errors))

    def test_max_per_city(self):
        ids = [f"v{i}" for i in range(10)]
        yt = FakeYouTube({"Sydney": ids}, [video(i, f"Sydney live cam {i}") for i in ids])
        config = {**CONFIG, "max_per_city": 3}
        feed, *_ = bf.build(yt, CITIES, config, previous=[], manual=[], today=self.today)
        self.assertEqual(len(feed), 3)

    def test_rotation_covers_all_cities_over_days(self):
        cities = [{"name": str(i)} for i in range(119)]
        seen = set()
        for day in range(3):
            seen.update(c["name"] for c in bf.rotation(cities, 88, self.today + datetime.timedelta(days=day)))
        self.assertEqual(len(seen), 119)


if __name__ == "__main__":
    unittest.main()
