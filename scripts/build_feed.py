#!/usr/bin/env python3
"""Builds live-cameras.json for Map Explorer from YouTube live webcam streams.

Runs daily on GitHub Actions (free). Uses the YouTube Data API's free daily quota:
  - search (100 units) finds live, embeddable streams near each city;
  - video lookups (1 unit per 50 videos) confirm each stream is live, public and embeddable.

Streams found on earlier days are kept as long as they're still live, so the cities are
searched in rotation without the list shrinking. Hand-picked cameras in manual.json are
always included. Only Python's standard library is used.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://www.googleapis.com/youtube/v3/"
SEARCH_COST = 100
LOOKUP_COST = 1


class QuotaExceeded(Exception):
    pass


def load_json(name, default):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_json(name, data):
    path = os.path.join(ROOT, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def http_get(endpoint, params, api_key, retries=2):
    """Calls the YouTube Data API. Raises QuotaExceeded when today's quota is used up."""
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = API + endpoint + "?" + query
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            if error.code == 403 and ("quotaExceeded" in body or "dailyLimitExceeded" in body):
                raise QuotaExceeded() from error
            if error.code in (500, 502, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"YouTube API error {error.code}: {body[:300]}") from error
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return {}


def looks_like_webcam(title, description, config):
    text = f"{title} {description}".lower()
    if any(word in text for word in config["exclude_keywords"]):
        return False
    return any(word in text for word in config["include_keywords"])


def mentions_city(video, city):
    snippet = video.get("snippet", {})
    text = " ".join([snippet.get("title", ""), snippet.get("description", "")[:500], snippet.get("channelTitle", "")]).lower()
    name = city["name"].lower()
    return name in text or name.split()[0] in text


def clean_title(title):
    title = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", title)   # emoji
    title = re.sub(r"\s+", " ", title).strip(" -|·•")
    return title[:80].rstrip() or "Live camera"


def rotation(cities, searches_today, today):
    """Different cities each day, so every city is searched every few days."""
    if not cities:
        return []
    start = (today.toordinal() * searches_today) % len(cities)
    ordered = cities[start:] + cities[:start]
    return ordered[:searches_today]


def search_city(city, config, get):
    """Live, embeddable streams for "<city> live cam". Searching by name finds far more webcams than
    YouTube's location filter, which only matches the few streams that carry location data."""
    data = get("search", {
        "part": "snippet",
        "type": "video",
        "eventType": "live",
        "videoEmbeddable": "true",
        "safeSearch": "moderate",
        "q": f"{city['name']} live cam|{city['name']} webcam|{city['name']} live camera",
        "order": "viewCount",
        "maxResults": 50,
    })
    found = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if video_id:
            found.append(video_id)
    return found


def lookup_videos(video_ids, get):
    """Returns {video_id: video} for up to thousands of IDs at 1 unit per 50."""
    details = {}
    ids = list(dict.fromkeys(video_ids))
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        data = get("videos", {
            "part": "snippet,status,liveStreamingDetails,recordingDetails",
            "id": ",".join(batch),
            "maxResults": 50,
        })
        for video in data.get("items", []):
            details[video["id"]] = video
    return details


def is_live_and_embeddable(video):
    snippet = video.get("snippet", {})
    status = video.get("status", {})
    live = video.get("liveStreamingDetails", {})
    return (
        snippet.get("liveBroadcastContent") == "live"
        and status.get("embeddable") is True
        and status.get("privacyStatus") == "public"
        and "actualEndTime" not in live
    )


def camera_entry(video, city):
    snippet = video.get("snippet", {})
    location = video.get("recordingDetails", {}).get("location", {})
    latitude = location.get("latitude", city["latitude"])
    longitude = location.get("longitude", city["longitude"])
    entry = {
        "id": "yt-" + video["id"],
        "name": clean_title(snippet.get("title", "")),
        "city": city["name"],
        "country": city["country"],
        "countryCode": city["countryCode"],
        "latitude": round(float(latitude), 5),
        "longitude": round(float(longitude), 5),
        "player": "youtube",
        "youtubeVideoId": video["id"],
        "provider": snippet.get("channelTitle") or "YouTube",
    }
    if city.get("timeZone"):
        entry["timeZone"] = city["timeZone"]
    return entry


def nearest_city(latitude, longitude, cities):
    return min(cities, key=lambda c: (c["latitude"] - latitude) ** 2 + (c["longitude"] - longitude) ** 2)


def build(get, cities, config, previous, manual, today):
    budget = int(config["daily_quota_budget"])
    used = 0
    errors = []

    # Keep previous automatic entries as candidates; they're re-checked below (cheap).
    previous_auto = [c for c in previous if str(c.get("id", "")).startswith("yt-") and c.get("youtubeVideoId")]
    candidates = {c["youtubeVideoId"]: nearest_city(c["latitude"], c["longitude"], cities) for c in previous_auto}

    reserve = len(candidates) // 50 + 20            # keep units for verification
    searches_today = max(0, (budget - reserve) // SEARCH_COST)
    searched = 0
    for city in rotation(cities, searches_today, today):
        if used + SEARCH_COST > budget - reserve:
            break
        try:
            ids = search_city(city, config, get)
            used += SEARCH_COST
            searched += 1
        except QuotaExceeded:
            errors.append("Daily quota reached during search; using what was found so far.")
            break
        except Exception as error:  # one city failing shouldn't stop the run
            errors.append(f"{city['name']}: {error}")
            continue
        for video_id in ids:
            candidates.setdefault(video_id, city)

    try:
        details = lookup_videos(list(candidates), get)
        used += (len(candidates) + 49) // 50 * LOOKUP_COST
    except QuotaExceeded:
        errors.append("Daily quota reached during verification; keeping the previous feed.")
        return None, used, searched, errors

    manual_ids = {c.get("youtubeVideoId") or c.get("youtubeChannelId") for c in manual}
    per_city = {}
    automatic = []
    dropped = {"not live/embeddable": 0, "not a webcam title": 0, "city not mentioned": 0, "city full": 0}
    for video_id, city in candidates.items():
        video = details.get(video_id)
        if not video or video_id in manual_ids:
            continue
        if not is_live_and_embeddable(video):
            dropped["not live/embeddable"] += 1
            continue
        snippet = video.get("snippet", {})
        if not looks_like_webcam(snippet.get("title", ""), snippet.get("description", "")[:300], config):
            dropped["not a webcam title"] += 1
            continue
        has_location = "location" in video.get("recordingDetails", {})
        if not has_location and not mentions_city(video, city):
            dropped["city not mentioned"] += 1
            continue
        key = city["name"]
        if per_city.get(key, 0) >= config["max_per_city"]:
            dropped["city full"] += 1
            continue
        per_city[key] = per_city.get(key, 0) + 1
        automatic.append(camera_entry(video, city))

    errors.append(f"Found {len(candidates)} candidate streams; kept {len(automatic)}; dropped: "
                  + ", ".join(f"{reason} {count}" for reason, count in dropped.items()))
    automatic.sort(key=lambda c: (c["country"], c["city"], c["name"]))
    feed = list(manual) + automatic[: max(0, config["max_total"] - len(manual))]
    return feed, used, searched, errors


def main():
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        print("YOUTUBE_API_KEY is not set. Add it under Settings › Secrets and variables › Actions.", file=sys.stderr)
        return 1

    config = load_json("config.json", {})
    cities = load_json("cities.json", [])
    manual = load_json("manual.json", [])
    previous = load_json("live-cameras.json", [])

    feed, used, searched, errors = build(
        get=lambda endpoint, params: http_get(endpoint, params, api_key),
        cities=cities, config=config, previous=previous, manual=manual,
        today=datetime.date.today(),
    )
    for error in errors[:10]:
        print("Note:", error)
    if len(errors) > 10:
        print(f"Note: ...and {len(errors) - 10} more")
    # Every search was rejected (usually a wrong or restricted API key): fail visibly with the reason.
    if searched == 0 and errors:
        print("::error::No YouTube search succeeded. First error: " + errors[0])
        print("Check the YOUTUBE_API_KEY secret: it must be a YouTube Data API v3 key with "
              "Application restrictions set to None (not your iOS Maps key).")
        return 1
    if feed is None:
        print("Feed not updated.")
        return 0
    if not feed and previous:
        print("No cameras found this run; keeping the previous feed instead of publishing an empty one.")
        return 0

    save_json("live-cameras.json", feed)
    print(f"Searched {searched} cities, used about {used} quota units, wrote {len(feed)} cameras.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
