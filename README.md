# Live cameras feed for Map Explorer

This repository builds `live-cameras.json` every day from **YouTube live webcam streams**
around ~120 cities worldwide, using the free YouTube Data API. Map Explorer reads the file
through Remote Config (`live_places.feed_url`).

- **Cost:** free. GitHub Actions is free for public repositories, and the script stays
  within YouTube's free daily quota (10,000 units).
- **What it keeps:** only streams that are **live now, public and allow embedding**, and whose
  title looks like a webcam (music, news, games and similar are filtered out).
- **Self-maintaining:** streams that end disappear; new ones appear. Cities are searched in
  rotation, so every city is checked every 2 days.

## One-time setup

### 1. Create a free YouTube API key
1. Go to **console.cloud.google.com** and create a project (for example "Map Explorer Feed").
   No billing account is needed.
2. Open **APIs & Services › Library**, search **YouTube Data API v3**, and click **Enable**.
3. Open **APIs & Services › Credentials › Create credentials › API key**. Copy the key.
4. Click the key › **API restrictions › Restrict key** › choose **YouTube Data API v3** › **Save**.
   (Leave "Application restrictions" as **None**: the key is used by GitHub's servers, not the app.)

### 2. Create the GitHub repository
1. On **github.com**, click **New repository**. Name it `live-cameras-feed`, choose **Public**,
   and click **Create repository**.
2. Click **uploading an existing file**, drag in **all files and folders from this folder**
   (including the hidden `.github` folder), and click **Commit changes**.
   - On a Mac, press **Cmd + Shift + .** in Finder to show the hidden `.github` folder.

### 3. Add the API key as a secret
1. In the repository: **Settings › Secrets and variables › Actions › New repository secret**.
2. Name: `YOUTUBE_API_KEY`. Secret: paste your key. Click **Add secret**.

The key stays private: it's never shown in logs or in the public files.

### 4. Run it the first time
1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Update live cameras feed › Run workflow › Run workflow**.
3. After a minute or two the run turns green and `live-cameras.json` fills with cameras.
   From now on it runs automatically every day.

### 5. Connect the app
1. Open `live-cameras.json` in the repository and click **Raw**. Copy that address. It looks like:
   `https://raw.githubusercontent.com/YOUR-USERNAME/live-cameras-feed/main/live-cameras.json`
2. In Firebase Remote Config, inside `app_config`:
   ```json
   "live_places": { "feed_url": "https://raw.githubusercontent.com/YOUR-USERNAME/live-cameras-feed/main/live-cameras.json" }
   ```
3. Publish. The cameras appear in Live Places the next time it opens.

## Adding your own cameras

Put hand-picked cameras in `manual.json` (create entries with the feed builder page, then
paste the JSON there). They're always included, first, and never removed automatically.

## Settings (`config.json`)

| Setting | Meaning |
|---|---|
| `daily_quota_budget` | Quota units the script may use per day (free limit is 10,000; 9,000 leaves headroom) |
| `search_radius_km` | Search radius around each city |
| `max_per_city` | Most cameras kept per city, so the globe isn't dominated by one place |
| `max_total` | Most cameras in the feed |
| `include_keywords` | A title must contain one of these to count as a webcam |
| `exclude_keywords` | Titles containing any of these are skipped |

Edit `cities.json` to add or remove cities (name, country, two-letter country code,
latitude, longitude, time zone).

## Good to know

- **Location data:** YouTube's location search only finds streams whose owners added a
  location. Well-known cams without location data won't be found automatically; add them to
  `manual.json`.
- **Paused schedules:** GitHub may pause scheduled workflows in a repository with no activity
  for 60 days and emails you first. If that happens, open the Actions tab and re-enable it.
- **Quota:** each city search costs 100 units; checking whether streams are still live costs
  1 unit per 50 streams. A run logs how many units it used.
- **Terms:** the app plays streams in YouTube's official embedded player, as YouTube's terms
  require. Keep the YouTube API Services Terms in mind if you change how the feed is used.
