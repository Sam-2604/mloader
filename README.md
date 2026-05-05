# mloader 🎵

A unified command-line tool for downloading audio from Spotify, YouTube, SoundCloud, Bandcamp, and Mixcloud — all from a single interactive menu.

Downloads are converted to MP3, tagged with full metadata and album art, and can be auto-renamed to `Song Name - Artist.mp3` for clean imports into Rekordbox, Serato, or any DJ software.

---

## How It Works

mloader routes URLs to the best available backend engine:

| Source | Engine | Quality |
|---|---|---|
| Spotify | [spotdl](https://github.com/spotDL/spotify-downloader) | Up to 256kbps (YouTube-sourced) |
| YouTube / YouTube Music | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Best available |
| SoundCloud | [scdl](https://github.com/scdl-org/scdl) | Best available, MP3 enforced |
| Bandcamp / Mixcloud / Other | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Best available |

> **On Spotify quality:** Spotify's audio is DRM-protected. No open-source tool can pull audio directly from Spotify's servers. spotdl works by reading Spotify track metadata and finding the closest audio match on YouTube/YouTube Music. Quality is capped at 256kbps. If a specific track sounds wrong or mismatched, download it directly using the YouTube option with the correct YouTube URL.

---

## Prerequisites

**FFmpeg** must be installed system-wide before running mloader. All backend engines depend on it for audio extraction and MP3 conversion.

```bash
# macOS
brew install ffmpeg

# Windows
winget install ffmpeg

# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
```

Verify the install worked:
```bash
ffmpeg -version
```

---

## Installation

```bash
git clone https://github.com/yourusername/mloader.git
cd mloader
pip install -r requirements.txt
```

**requirements.txt**
```
yt-dlp
scdl
spotdl
mutagen
```

---

## Spotify Setup

spotdl uses a shared Spotify API key by default. Because thousands of users share that same key, Spotify aggressively rate-limits it — you may see a 24-hour block before downloading anything.

The fix is to register your own free Spotify Developer app. Your credentials get their own rate limit bucket that only you consume.

**Steps:**

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account
2. Click **Create App**
3. Give it any name (e.g. `mloader`). Set the Redirect URI to `http://localhost:8080`
4. Copy your **Client ID** and **Client Secret** from the app dashboard

On the first Spotify download, mloader will ask for these. It validates them against Spotify's API before saving, so you will know immediately if something was mistyped. Credentials are saved to `~/.config/mloader/spotdl_creds.json` and reused automatically on every subsequent run.

To re-enter credentials at any time, select **option 8** from the main menu.

---

## Usage

```bash
python mloader.py
```

**Interactive menu:**

```
1. Spotify
2. YouTube
3. YouTube Music
4. SoundCloud
5. Bandcamp
6. Mixcloud
7. Other (paste any link)
8. Reset Spotify credentials
0. Exit
```

1. Select a source
2. Paste the URL — track, album, and playlist links all work
3. Set an output path, or press Enter for the default (`~/Music/mloader`)
4. Choose whether to auto-rename files to `Song Name - Artist.mp3`

mloader downloads, converts, tags, and optionally renames. A summary prints at the end showing every file saved and any errors encountered.

---

## Output

All files are saved as MP3 with embedded ID3 tags — title, artist, album, and album art. The optional rename step reads these tags and standardises filenames to:

```
Song Name - Artist.mp3
```

Files where ID3 tags are missing or malformed are kept under their original downloaded filename and flagged separately in the summary so you know which ones need manual attention.

---

## Known Limitations

**Spotify**
- Audio quality is capped at 256kbps — this is a platform constraint, not a tool limitation
- spotdl may occasionally match the wrong YouTube video for tracks with common names, live versions, or remixes — if a track sounds wrong, grab it directly via the YouTube option with the correct YouTube URL
- Regional or non-Latin-titled tracks (Hindi, Tamil, etc.) have lower match accuracy on YouTube — direct YouTube downloads are more reliable for these

**SoundCloud**
- Tracks with copyright mutes (silence replacing flagged audio) cannot be recovered — SoundCloud serves the muted version and that is what gets downloaded. Get the clean version from Spotify or YouTube instead
- Private tracks will silently fail

**YouTube / yt-dlp**
- YouTube occasionally changes its internal structure and breaks yt-dlp temporarily — if YouTube downloads suddenly stop working, run `pip install -U yt-dlp` first before anything else
- Age-restricted videos require browser cookies passed to yt-dlp — not currently supported in mloader

**General**
- mloader warns you if free disk space drops below 1GB before starting a download, but does not enforce a hard stop — monitor space manually for very large playlist downloads

---

## Troubleshooting

**Spotify rate limit error (Retry after 86400s)**
You are hitting the shared spotdl API rate limit. Fix: set up your own Spotify Developer credentials as described in [Spotify Setup](#spotify-setup). Once you have your own Client ID and Secret, this error will not occur.

**Credentials rejected during setup**
Double-check that you copied both values correctly from the Spotify Developer Dashboard and that the app is not in a suspended state. Select option 8 from the menu to reset and re-enter.

**ffmpeg not found**
Install ffmpeg system-wide and confirm it is in your PATH with `ffmpeg -version`. mloader exits on launch if ffmpeg is missing since all three engines depend on it.

**yt-dlp fails on YouTube**
Run `pip install -U yt-dlp`. YouTube structure changes break yt-dlp periodically — updating the package is almost always the fix.

**Download summary shows 0 files**
Check the output directory manually. This can happen if ffmpeg failed to convert the file mid-process — the raw audio file may be present without the `.mp3` extension.

**Rename step shows files as failed**
The file downloaded successfully but has no ID3 tags embedded, so mloader cannot read a title or artist to rename from. This is common with some SoundCloud uploads. The file is still saved under its original downloaded filename.

---

## Dependencies

| Package | Purpose |
|---|---|
| `yt-dlp` | YouTube, Bandcamp, Mixcloud, and general URL downloads |
| `spotdl` | Spotify track resolution and download |
| `scdl` | SoundCloud downloads |
| `mutagen` | ID3 tag reading for file renaming |
| `ffmpeg` | Audio extraction and MP3 conversion (system install, not pip) |

---

## License

MIT