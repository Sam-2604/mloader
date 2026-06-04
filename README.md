# mloader 🎵

A unified command-line tool for downloading audio from Spotify, YouTube, SoundCloud, Bandcamp, and Mixcloud, all from a single interactive menu.

Downloads are converted to MP3, tagged with full metadata and album art, and can be auto-renamed to `Song Name - Artist.mp3` for clean imports into Rekordbox, Serato, or any DJ software.

---

## How It Works

mloader routes URLs to the best available backend engine:

| Source | Engine | Quality |
|---|---|---|
| Spotify | [spotdl](https://github.com/spotDL/spotify-downloader) | Best available from YouTube source (up to ~256kbps) |
| YouTube / YouTube Music | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Best available |
| SoundCloud | [scdl](https://github.com/scdl-org/scdl) | Best available, MP3 enforced |
| Bandcamp / Mixcloud / Other | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Best available |

> **On Spotify quality:** Spotify's audio is DRM-protected. No open-source tool can pull audio directly from Spotify's servers. spotdl works by reading Spotify track metadata and finding the closest audio match on YouTube/YouTube Music. The practical ceiling is around 256kbps (the YouTube Music source). mloader sets the spotdl bitrate to `auto`, so the best available source quality is preserved rather than re-encoded down. If a specific track sounds wrong or mismatched, download it directly using the YouTube option with the correct YouTube URL.

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

Spotify downloads require your own free Spotify Developer credentials. spotdl uses these to read track metadata (title, artist, album) from Spotify's API. The actual audio is sourced from YouTube, so Spotify only ever sees metadata reads, never a download.

**Steps:**

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account
2. Click **Create App**
3. Give it any name (e.g. `mloader`). Set the Redirect URI to `http://localhost:8080`
4. Copy your **Client ID** and **Client Secret** from the app dashboard

On the first Spotify download, mloader will ask for these. It validates them against Spotify's API before saving, so you will know immediately if something was mistyped. Credentials are saved to `~/.config/mloader/spotdl_creds.json` and reused automatically on every subsequent run.

To re-enter credentials at any time, select **option 11** from the main menu.

> **Note on credentials and rate limits:** Each Spotify Developer app has its own rate-limit budget. A development-mode app can occasionally get throttled (Spotify returns a `Retry-After` of up to 86400 seconds). If that happens, you can either wait it out or create a second app and switch to it via option 11. mloader passes `--no-cache` to spotdl on every run so it always authenticates with the exact credentials you provided (see Troubleshooting for why this matters).

---

## Usage

```bash
python mloader.py
```

**Interactive menu:**

```
--- Download ---
1. Spotify
2. YouTube
3. YouTube Music
4. SoundCloud
5. Bandcamp
6. Mixcloud
7. Other (paste any link)

--- Playlists & Sync ---
8. Save a playlist for syncing
9. List saved playlists
10. Sync all saved playlists

--- Settings ---
11. Reset Spotify credentials
0. Exit
```

For a one-off download (options 1-7):

1. Select a source
2. Paste the URL. Track, album, and playlist links all work
3. Set an output path, or press Enter for the default (`~/Music/mloader`)
4. Choose whether to auto-rename files to `Song Name - Artist.mp3`

mloader downloads, converts, tags, and optionally renames. If a newly downloaded file shares a name with one you already have, it asks whether to keep both, skip, or replace (see Duplicate Handling). A summary prints at the end showing every file saved and any errors encountered.

> **Changing the default download folder:** The default for one-off downloads is `~/Music/mloader`. To change it permanently, edit the `DEFAULT_OUTPUT` line near the top of `mloader.py`. It accepts `~` for your home folder or any absolute path.

---

## How Spotify Downloads Pick a Source (audio providers)

spotdl can fetch the matched audio from several providers. mloader tries them in order and falls back automatically if one fails:

1. **youtube-music** - tried first. By far the most accurate matches and the most reliable downloads.
2. **youtube** - fallback. Plain YouTube search; matches less reliably.
3. **piped** - last resort. Public proxy instances, often unavailable.

The fallback order lives in the `provider_chain` list inside `download_spotdl()` in `mloader.py`. Reorder or trim it if you want different behaviour.

> **About "You are blocked by YouTube Music":** spotdl has an unreliable pre-flight check that searches the single letter "a" and treats an empty result as a block. YouTube Music often returns nothing for that query even when real song searches work fine, so the check raises a false "blocked" error and aborts the whole run. mloader launches spotdl through a small shim that neutralises that one check, so this false positive no longer stops your downloads. A genuine network block (rare) still fails during the real search and falls back to the next provider.

---

## Playlist Syncing

Beyond one-off downloads, mloader can keep playlists in sync: download new tracks, remove tracks you deleted from the playlist, and never re-download what you already have.

**Save a playlist (option 8):** give it a name, pick the source (Spotify / SoundCloud / YouTube), and paste the playlist URL. mloader records it in a registry at `~/.config/mloader/playlists.json` and assigns it a managed folder (see Library Structure below).

**List saved playlists (option 9):** prints every registered playlist with its source, URL, and folder.

**Sync all saved playlists (option 10):** runs every saved playlist through its engine's native sync, renames new files, then regenerates the Rekordbox XML. Each source syncs differently:

| Source | Sync behaviour |
|---|---|
| Spotify | `spotdl sync` - downloads new tracks **and deletes tracks removed from the playlist** |
| SoundCloud | `scdl --sync` against a per-folder archive - adds and removes changed tracks |
| YouTube | yt-dlp with a download-archive - skips already-downloaded tracks (does not delete) |

> Spotify is the only source that deletes removed tracks from disk, because spotdl's sync file tracks the full playlist state. SoundCloud does this too via its archive. YouTube only adds.

---

## Library Structure

Saved/synced playlists are organised automatically under the mloader library root (`~/Music/mloader` by default):

```
~/Music/mloader/
├── spotify/<playlist-slug>/
├── soundcloud/<playlist-slug>/
├── youtube/<playlist-slug>/
├── general/                  <- loose / uncategorised songs
└── rekordbox.xml             <- generated on every sync
```

Playlist names are slugified (lowercase, spaces become hyphens). One-off downloads (options 1-7) are **not** forced into this structure - they still go to whatever path you type, so you can keep project downloads anywhere. To relocate the whole managed library, edit the `MLOADER_ROOT` line near the top of `mloader.py`.

---

## Duplicate Handling

For one-off downloads only, after a download finishes mloader checks whether any new file shares a filename with one that already existed under the output path. For each match it asks:

- **[b]oth** - keep both copies
- **[s]kip** - delete the newly downloaded copy
- **[r]eplace** - delete the old copy, keep the new one

Sync runs never prompt - de-duplication there is handled by each engine and by the Rekordbox export.

---

## Rekordbox Export

Every sync regenerates `~/Music/mloader/rekordbox.xml`, ready to import into Rekordbox (File > Import Collection, or as an XML source under Preferences > Advanced > Database).

- Every folder becomes a Rekordbox playlist, mirroring your library's folder tree.
- The collection is **deduplicated by title + artist (case-insensitive)**: if the same song exists as two files in two folders, it appears **once** in the collection but is referenced in **both** playlists. No duplicate library entries in Rekordbox.
- Track locations are written as `file://localhost/` URLs per the Rekordbox XML spec.

---

## Weekly Automation (macOS)

mloader can sync on a schedule with zero interaction. The headless command is:

```bash
python mloader.py --sync
```

This runs all saved playlists and regenerates the XML with no menu and no prompts. The `automation/` folder contains a ready-made macOS `launchd` schedule (`com.mloader.sync.plist`) that runs this every Friday at 2 AM, plus a plain-language setup guide in [automation/README.md](automation/README.md).

---

## Output

All files are saved as MP3 with embedded ID3 tags: title, artist, album, and album art. The optional rename step reads these tags and standardises filenames to:

```
Song Name - Artist.mp3
```

Files where ID3 tags are missing or malformed are kept under their original downloaded filename and flagged separately in the summary so you know which ones need manual attention.

---

## Known Limitations

**Spotify**
- Audio quality is capped at roughly 256kbps. This is a platform constraint (YouTube-sourced audio), not a tool limitation
- spotdl may occasionally match the wrong YouTube video for tracks with common names, live versions, or remixes. If a track sounds wrong, grab it directly via the YouTube option with the correct YouTube URL
- Regional or non-Latin-titled tracks (Hindi, Tamil, etc.) have lower match accuracy on YouTube. Direct YouTube downloads are more reliable for these

**SoundCloud**
- Tracks with copyright mutes (silence replacing flagged audio) cannot be recovered. SoundCloud serves the muted version and that is what gets downloaded. Get the clean version from Spotify or YouTube instead
- Private tracks will silently fail

**YouTube / yt-dlp**
- YouTube occasionally changes its internal structure and breaks yt-dlp temporarily. If YouTube downloads suddenly stop working, run `pip install -U yt-dlp` first before anything else
- Age-restricted videos require browser cookies passed to yt-dlp, not currently supported in mloader

**General**
- mloader warns you if free disk space drops below 1GB before starting a download, but does not enforce a hard stop. Monitor space manually for very large playlist downloads

---

## Troubleshooting

**Spotify error: "Your application has reached a rate/request limit. Retry will occur after: 86400 s"**
This means the Spotify app spotdl authenticated with is rate-limited. Two things to check:

1. **Stale token cache (most common, now handled automatically).** spotdl caches its Spotify token at `~/.spotdl/.spotipy`. If that cache holds a token from a different, rate-limited app, spotdl will keep using it even when you pass fresh credentials, producing this exact error while your real credentials are perfectly fine. mloader now passes `--no-cache` so a fresh token is minted from your credentials every run, preventing this. If you ever hit it manually, delete `~/.spotdl/.spotipy`.
2. **Genuinely throttled app.** If the app really is over its budget, wait for the limit to reset, or create a second Spotify Developer app and switch to it with option 11.

**Error: "You are blocked by YouTube Music"**
This is almost always a false positive from spotdl's unreliable pre-flight check (it searches "a" and treats an empty result as a block). mloader already bypasses that check with a shim, so you should rarely see this. If a Spotify download still fails:
- Try again in a moment. spotdl's search results for some queries are momentarily flaky.
- If it persists, your network may be genuinely blocking YouTube. Switch network (mobile data / hotspot on the computer itself, or a VPN) or wait a few minutes.
- mloader also falls back from youtube-music to youtube automatically, though plain youtube matches less reliably.

**Credentials rejected during setup**
Double-check that you copied both values correctly from the Spotify Developer Dashboard and that the app is not in a suspended state. Select option 11 from the menu to reset and re-enter.

**ffmpeg not found**
Install ffmpeg system-wide and confirm it is in your PATH with `ffmpeg -version`. mloader exits on launch if ffmpeg is missing since all engines depend on it.

**yt-dlp fails on YouTube**
Run `pip install -U yt-dlp`. YouTube structure changes break yt-dlp periodically and updating the package is almost always the fix.

**Download summary shows 0 files**
Check the output directory manually. This can happen if ffmpeg failed to convert the file mid-process. The raw audio file may be present without the `.mp3` extension.

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
