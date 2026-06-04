# mloader - Technical Documentation

## Project Structure

```
mloader/
├── mloader.py          # Single-file program - all logic lives here
├── requirements.txt    # Python package dependencies
├── README.md           # User-facing setup and usage guide
├── TECHNICAL.md        # This file
└── automation/
    ├── com.mloader.sync.plist   # macOS launchd schedule for weekly headless sync
    └── README.md                # Plain-language install/uninstall guide
```

External config + state written at runtime (all outside the repo):
```
~/.config/mloader/
├── spotdl_creds.json   # Spotify Developer API credentials (first Spotify download)
├── playlists.json      # Saved-playlist registry for syncing
└── sync/
    └── <slug>.spotdl   # spotdl per-playlist tracking file (Spotify only)
```

spotdl also keeps its own config and token cache (created/managed by spotdl, not mloader):
```
~/.spotdl/
├── config.json         # spotdl defaults (audio providers, bitrate, etc.)
└── .spotipy            # cached Spotify access token (mloader bypasses this with --no-cache)
```

Managed library root (synced playlists + generated XML):
```
~/Music/mloader/
├── spotify/<slug>/      soundcloud/<slug>/      youtube/<slug>/
├── general/             # loose songs
└── rekordbox.xml        # regenerated on every sync
```

---

## Two run modes

mloader has two entry behaviours, selected by `argparse` in the `__main__` block:

- **Interactive (default):** `python mloader.py` runs `main()`, the menu loop.
- **Headless sync:** `python mloader.py --sync` runs `run_sync()` once and exits - no menu, no prompts. This is what the weekly `launchd` automation calls.

---

## Architecture Overview

mloader is a single-file CLI wrapper. It has no classes for orchestration - all logic is organised into standalone functions grouped by responsibility. The `main()` loop handles user input and orchestrates calls to the downloader functions.

```
main()                              run_sync()  (also via --sync)
  ├── print_intro()                   ├── check_dependencies()
  ├── check_dependencies()            ├── load_registry()
  │                                   ├── for each playlist:
  └── [loop]                          │     └── sync_one_playlist()
        ├── 1-7  standalone download  │           ├── spotdl sync   (spotify)
        │     ├── download_spotdl()   │           ├── scdl --sync   (soundcloud)
        │     ├── download_scdl()     │           ├── download_ytdlp(archive) (youtube)
        │     ├── download_ytdlp()    │           └── rename_files() on new files
        │     ├── rename_files()      └── generate_rekordbox_xml()
        │     └── handle_duplicate_downloads()
        ├── 8    add_playlist()
        ├── 9    list_playlists()
        ├── 10   run_sync()
        └── 11   reset_spotdl_creds()
```

Standalone downloads carry no in-memory state between iterations. Sync state lives on disk: the registry (`playlists.json`), spotdl's per-playlist `.spotdl` files, scdl's `.sync_archive`, and yt-dlp's `.archive.txt`.

---

## Constants

```python
CREDS_PATH = os.path.expanduser("~/.config/mloader/spotdl_creds.json")
MLOADER_ROOT = os.path.expanduser("~/Music/mloader")          # managed library + XML root
DEFAULT_OUTPUT = os.path.expanduser("~/Music/mloader")        # default for standalone downloads
PLAYLISTS_PATH = os.path.expanduser("~/.config/mloader/playlists.json")
SYNC_DIR = os.path.expanduser("~/.config/mloader/sync")       # spotdl .spotdl tracking files
REKORDBOX_XML = os.path.join(MLOADER_ROOT, "rekordbox.xml")
SYNC_SOURCES = {"spotify": "spotify", "soundcloud": "soundcloud", "youtube": "youtube"}
DISK_WARN_THRESHOLD_GB = 1.0
```

`os.path.expanduser()` resolves the `~` home directory symbol correctly on macOS, Linux, and Windows. These are defined at the top of the file so they can be changed in one place. `MLOADER_ROOT` is the managed library where synced playlists are organised as `<root>/<source>/<slug>/` and where `rekordbox.xml` is written; `DEFAULT_OUTPUT` is only the fallback destination for one-off downloads. They can point to different places.

---

## Key Functions

### `check_dependencies()`
- **Purpose:** Verify all four required CLI tools are installed and accessible in the system PATH before the user does anything.
- **Input:** None.
- **Output:** Prints a specific install command for each missing tool. Calls `sys.exit(1)` if anything is missing.
- **How it works:** Uses `shutil.which(tool)`, the same mechanism your terminal uses to find commands. Returns `None` if the tool isn't found.
- **Why this matters:** Without this check, a missing tool would cause a cryptic crash mid-download instead of a clean error on launch.

---

### `check_disk_space(path)`
- **Purpose:** Warn the user before starting a large download if the target drive is nearly full.
- **Input:** The output directory path.
- **Output:** Console warning if free space is below `DISK_WARN_THRESHOLD_GB` (1.0GB). Silent if space is fine.
- **How it works:** `shutil.disk_usage(path)` returns total, used, and free bytes for the drive containing that path. Divides free bytes by `1024**3` to get gigabytes.
- **Design note:** This is a warning only - it does not block the download. The threshold is set conservatively at 1GB because a large playlist can easily exceed several gigabytes.
- **Edge cases:** Wrapped in a broad `except` block so a permissions error or unexpected filesystem type doesn't crash the program. Disk check failure is non-critical.

---

### `validate_spotify_creds(client_id, client_secret)`
- **Purpose:** Test a Client ID and Secret against Spotify's live API before saving them, so the user gets immediate feedback if they mistyped.
- **Input:** Two strings - Client ID and Client Secret.
- **Output:** `True` if Spotify accepted the credentials, `False` otherwise.
- **How it works:**
  - Combines credentials as `client_id:client_secret`, Base64-encodes the string
  - Makes a POST request to `https://accounts.spotify.com/api/token` with `grant_type=client_credentials`
  - This is Spotify's standard machine-to-machine auth flow - it doesn't require a user login, just a valid Developer app
  - Returns `True` if the response status is 200
- **Why stdlib only:** Uses `urllib.request`, `urllib.parse`, and `base64`, all built into Python. No additional packages needed for this validation step.
- **Edge cases:** `urllib.error.HTTPError` (e.g. 401 Unauthorized) returns `False`. Any other exception (network timeout, DNS failure) also returns `False` - the `except Exception` catches this without crashing.

---

### `get_spotdl_creds()`
- **Purpose:** Return valid Spotify Developer credentials, loading from disk if they exist, otherwise prompting and validating interactively.
- **Input:** None.
- **Output:** Dict with keys `"client_id"` and `"client_secret"`.
- **First run flow:**
  1. Prints setup instructions with the Spotify Developer Dashboard URL
  2. Prompts for Client ID and Secret in a `while True` loop
  3. Calls `validate_spotify_creds()`, looping back with an error message if rejected
  4. On successful validation, writes credentials to `CREDS_PATH` as JSON and returns them
- **Subsequent runs:** File exists -> `json.load()` -> return immediately. No prompts, no validation call.
- **Credentials format on disk:**
  ```json
  {
    "client_id": "your_id_here",
    "client_secret": "your_secret_here"
  }
  ```

---

### `reset_spotdl_creds()`
- **Purpose:** Delete the saved credentials file so the user can re-enter them on the next Spotify download.
- **Input:** None (reads `CREDS_PATH` constant).
- **Output:** Console confirmation. Deletes the file if it exists.
- **When to use:** Wrong credentials were saved, the Spotify Developer app was deleted and replaced, or the current app is rate-limited and you want to switch to a second app.
- **Triggered by:** Menu option 8.

---

### `get_all_mp3s(directory)`
- **Purpose:** Return a complete set of absolute paths to every `.mp3` file in the output directory, including files inside subdirectories.
- **Input:** A directory path string.
- **Output:** A Python `set` of absolute path strings.
- **How it works:** `os.walk(directory)` recursively yields every subdirectory and file underneath the starting path. For each file ending in `.mp3`, `os.path.abspath()` normalises the path before adding it to the set.
- **Why this matters:** This function is called twice per download, once before and once after. The difference between the two sets (`files_after - files_before`) is exactly the new files downloaded in that run. Using a set makes this subtraction a single line.
- **Why recursive matters:** spotdl saves files into `Artist/Album/track.mp3` nested subdirectories. A flat `os.listdir()` would miss these entirely. `os.walk()` catches everything regardless of depth.

---

### `download_ytdlp(url, output_path, archive_path=None)`
- **Purpose:** Download audio from YouTube, YouTube Music, Bandcamp, Mixcloud, or any other yt-dlp-supported URL.
- **Input:** URL string, output directory path string, and an optional `archive_path`.
- **Output:** List of error strings (empty if everything succeeded).
- **`archive_path`:** when provided, sets yt-dlp's `download_archive` option. yt-dlp records every successfully downloaded video ID in that file and skips IDs already listed. This is what makes YouTube playlist sync idempotent - re-runs only fetch tracks added since last time. Standalone downloads pass nothing, so this is off by default.
- **How it works:**
  - Uses yt-dlp's Python API directly (`import yt_dlp`) rather than calling it as a subprocess - this gives more control over error handling
  - `format: bestaudio/best` - selects the highest quality audio-only stream. Falls back to best available if no audio-only stream exists
  - `FFmpegExtractAudio` postprocessor - calls ffmpeg to extract the audio track and convert it to MP3. `preferredquality: '0'` means "use the best available quality" - it does not upscale compressed audio, just preserves what was downloaded
  - `FFmpegMetadata` - embeds title, artist, album, and other tags into the MP3 ID3 header
  - `EmbedThumbnail` - embeds the video/track thumbnail as the MP3 album art. Requires `writethumbnail: True` to download it first
  - `ignoreerrors: True` - if one track in a playlist fails (geo-blocked, deleted, age-restricted), yt-dlp skips it and continues rather than aborting the whole batch
- **Error capture:** `YTDLPLogger` (see below) intercepts per-track errors and stores them in a list instead of letting them crash the program or get lost in stdout.

---

### `class YTDLPLogger`
- **Purpose:** A custom logger passed to yt-dlp to capture error messages per track without crashing the run.
- **How it works:** yt-dlp accepts a logger object with `debug()`, `warning()`, and `error()` methods. Only `error()` is implemented here - it appends each error message to `self.errors`. `debug` and `warning` are intentional no-ops (blank `pass`) to suppress verbose output.
- **Why this exists:** Without a custom logger, yt-dlp prints errors directly to stderr with no way to capture or display them in mloader's summary format. This logger intercepts them so they appear cleanly at the end of the download summary under "Errors during download."

---

### `download_spotdl(url, output_path, creds)`
- **Purpose:** Download Spotify tracks by matching them to YouTube/YouTube Music audio via spotdl.
- **Input:** Spotify URL (track, album, or playlist), output path, credentials dict.
- **Output:** List of error strings.
- **How it works:** Runs spotdl once per audio provider in a fallback chain. It does not call the bare `spotdl` binary; it launches the current Python (`sys.executable`) with a small shim (`SPOTDL_SHIM`) that neutralises spotdl's broken YouTube Music pre-flight check (see "YouTube Music pre-flight check" below), then forwards these arguments to spotdl's entry point:
  - `download` - spotdl subcommand for downloading
  - `--format mp3` - enforce MP3 output
  - `--output output_path` - destination folder
  - `--client-id` / `--client-secret` - your personal Developer app credentials
  - `--audio <provider>` - the current provider from the fallback chain
  - `--bitrate auto` - keep the best available source quality rather than re-encoding down
  - `--no-cache` - mint a fresh Spotify token from the credentials above every run (see "Spotify token cache" below)
- **Audio provider fallback chain:** `provider_chain = ["youtube-music", "youtube", "piped"]`. spotdl is run with the first provider; if it exits non-zero, mloader prints a notice and retries with the next. youtube-music gives the best matches and is tried first. youtube is a weaker fallback. piped (a public proxy) is a last resort and is frequently unavailable. If every provider fails, the run returns a single actionable error string (usually a temporary YouTube Music IP block, not a credential problem).
- **Why subprocess instead of Python API:** spotdl has a Python API but it is less stable and more complex to integrate than its CLI, which is well-maintained and well-documented. Subprocess is simpler and more reliable here.
- **`check=False` (returncode checked manually):** A non-zero exit from spotdl does not raise a Python exception. mloader checks `result.returncode` itself, so one failed provider triggers the fallback instead of crashing the program.
- **Quality:** spotdl sources audio from YouTube/YouTube Music. The practical ceiling is around 256kbps. mloader passes `--bitrate auto` so the best available source quality is preserved rather than re-encoded down. This is passed explicitly on the command line rather than relying on the machine's `~/.spotdl/config.json`, so behaviour is consistent for everyone who clones the repo.

---

### Spotify token cache (why `--no-cache` matters)

spotdl authenticates to Spotify via spotipy, which by default caches the access token at `~/.spotdl/.spotipy`. That cache stores only the token, not which app it belongs to. If the cache holds a still-valid token that was minted by a different Developer app, spotipy will reuse it even when you pass different `--client-id` / `--client-secret` on the command line.

The failure mode this produces: a `Your application has reached a rate/request limit. Retry will occur after: 86400 s` error, while your actual credentials are perfectly healthy. The request is going out under the cached token's (rate-limited) app, not yours. spotipy then honours the `Retry-After` header and sleeps, which looks like a hang.

mloader avoids this entirely by passing `--no-cache`, forcing a fresh token from the supplied credentials on every run. If you hit this error outside mloader, delete `~/.spotdl/.spotipy`.

---

### YouTube Music pre-flight check (why the shim exists)

Before downloading, spotdl runs `check_ytmusic_connection()`. That function searches YouTube Music for the single letter `"a"` and, if it gets zero usable results, raises `You are blocked by YouTube Music` and aborts the entire run.

The problem: YouTube Music regularly returns nothing for that bare one-character query even when real song searches work perfectly. In testing, `get_results("a")` returned 0 while `get_results("The Weeknd - Blinding Lights")` returned 4 and the underlying `ytmusicapi` returned 20 results for normal queries. So the check produces a false "blocked" error and stops downloads that would otherwise succeed. Changing IP, network, or using a VPN does not fix it, because it is not actually an IP block.

`mloader.py` defines `SPOTDL_SHIM`, a one-line Python snippet that sets `check_ytmusic_connection` to always return `True`, then calls spotdl's normal entry point. `download_spotdl` runs spotdl through this shim (via `sys.executable -c`) instead of the bare binary, so the false check can no longer abort a working download. A genuine block still fails naturally during the real search and triggers the provider fallback.

---

### `download_scdl(url, output_path)`
- **Purpose:** Download SoundCloud tracks, sets, or profiles.
- **Input:** SoundCloud URL, output path string.
- **Output:** List of error strings.
- **How it works:** Calls scdl as a subprocess with:
  - `-l url` - the SoundCloud link to download
  - `--path output_path` - destination folder
  - `--onlymp3` - enforces MP3 output format. Without this, scdl may download in the source format (sometimes opus or aac depending on the upload)
- **`check=False`:** Same reasoning as spotdl - non-zero exit is caught manually.

---

### `rename_files(new_filepaths)`
- **Purpose:** Read ID3 metadata tags from each downloaded MP3 and rename the file to `Song Name - Artist.mp3`.
- **Input:** List of absolute file path strings.
- **Output:** Tuple of two lists - `(renamed, failed)`. `renamed` contains the final path of every file (successfully renamed or not). `failed` contains paths of files that could not be renamed due to missing tags.
- **How it works:**
  - `EasyID3(filepath)` from the `mutagen` library opens the MP3 and reads its ID3 tags as a dictionary
  - `.get('title', [None])[0]` - ID3 tags return lists (a track can technically have multiple values per tag). Takes the first element. Returns `None` if the tag doesn't exist
  - Strips characters illegal in filenames across macOS, Windows, and Linux: `\ / : * ? " < > |`
  - Constructs `new_filename = f"{safe_title} - {safe_artist}.mp3"`
  - `os.rename()` performs the actual rename in-place (same directory, new filename)
  - Checks `os.path.exists(new_filepath)` before renaming to avoid overwriting an existing file with the same name (e.g. two versions of the same track)
- **Failure handling:** If `title` or `artist` tags are missing, or if `EasyID3` throws an exception (malformed tags, file locked, etc.), the original filepath is added to `failed` and kept in `renamed` so the summary counts it as downloaded but flags it separately.

---

## Playlist Sync Functions

### `slugify(name)`
- Turns a playlist name into a safe folder slug: lowercase, non-word characters stripped, spaces/underscores collapsed to single hyphens. Falls back to `"playlist"` for an empty result. Used for both folder names and `.spotdl` filenames.

### `load_registry()` / `save_registry(registry)`
- Read/write the saved-playlist list at `PLAYLISTS_PATH` (`playlists.json`). `load_registry` returns `[]` if the file is missing or unreadable; `save_registry` creates the parent directory and writes indented JSON. Each entry has `name`, `source`, `url`, `output_path`, and `sync_file` (the last is `null` for non-Spotify sources).

### `load_creds_noninteractive()`
- Returns saved Spotify credentials as a dict, or `None` if the file is missing/unreadable. Unlike `get_spotdl_creds()` it never prompts, so it is safe in headless `--sync` mode. When it returns `None`, Spotify playlists are skipped during sync rather than blocking on input.

### `add_playlist()` (menu option 8)
- Prompts for name + source (Spotify/SoundCloud/YouTube) + URL, computes the managed folder `MLOADER_ROOT/<source>/<slug>` and (for Spotify) a `SYNC_DIR/<slug>.spotdl` tracking file, then appends the entry to the registry. Refuses to add a duplicate name+source. Creates the output folder so it exists before the first sync.

### `list_playlists()` (menu option 9)
- Prints every registered playlist with its source, URL, and folder.

### `run_sync()` (menu option 10 and `--sync`)
- Verifies dependencies, loads the registry, syncs each playlist via `sync_one_playlist()`, then calls `generate_rekordbox_xml()`. No prompts, so it backs both the menu option and the headless flag. Each playlist sync is wrapped in try/except so one failure does not abort the rest.

### `sync_one_playlist(entry, creds)`
- Runs the source-appropriate native sync, then renames any new files:
  - **spotify:** `spotdl sync` via `_spotdl_base()` (the shim). First run (no `.spotdl` file yet) downloads everything and writes the tracking file with `--save-file`; later runs sync from the tracking file, which adds new tracks **and deletes tracks removed from the playlist**. Skipped with a message if no credentials are available.
  - **soundcloud:** `scdl --sync <archive>` where the archive is `.sync_archive` inside the playlist folder; scdl adds/removes changed tracks.
  - **youtube:** `download_ytdlp(url, output_path, archive_path=.archive.txt)` so already-fetched videos are skipped (additive only, no deletion).
- New files are detected with the same before/after `get_all_mp3s` diff used by standalone downloads and passed through `rename_files`.

---

## Duplicate Handling

### `handle_duplicate_downloads(final_files, files_before)`
- **Standalone only.** Builds a map of basename to existing paths from `files_before`, then for each newly downloaded file whose basename collides with an existing one, prompts: keep both, skip (delete the new copy), or replace (delete the old copy). Returns the surviving file list for the summary. Sync never calls this - its dedup is handled natively per engine and by the Rekordbox export.
- `_safe_remove(path)` is a small best-effort `os.remove` wrapper used for the skip/replace deletions.

---

## Rekordbox XML Export

### `generate_rekordbox_xml()`
- Builds `REKORDBOX_XML` (`~/Music/mloader/rekordbox.xml`) from the entire managed library and returns the unique-track count. Uses only `xml.etree.ElementTree` (stdlib).
- **Collection dedup (the core requirement):** `_build_collection()` walks every mp3 under `MLOADER_ROOT`, reads tags via `_read_tags()`, and keys each track by `(title.lower(), artist.lower())` (`_track_key`). The same song existing as two files in two folders yields **one** `<TRACK>` entry with a single `TrackID`. It returns both the collection and a `file -> key` map.
- **Playlist tree:** `_dir_to_node()` recursively mirrors the folder structure - a folder with sub-folders becomes a `Type="0"` node, a folder with mp3s becomes a `Type="1"` playlist node, and a folder with both gets sub-folder nodes plus a playlist node for its own tracks. `_playlist_node()` resolves each file to its collection `TrackID` (deduped within the playlist) and emits `<TRACK Key="...">` references. A song in two folders is referenced by the same `TrackID` in both playlist nodes.
- **Locations:** `_file_uri()` produces `file://localhost/` + a percent-encoded absolute path, per the Rekordbox XML spec.
- Output is written with `ET.indent()` for readability and a UTF-8 XML declaration, overwriting any previous file.

---

## Data Flow

```
User Input (url, path, preferences)
        │
        ▼
get_all_mp3s(output_path)       <- files_before snapshot
        │
        ▼
   [downloader]
   download_spotdl()  /  download_scdl()  /  download_ytdlp()
        │
        ▼
get_all_mp3s(output_path)       <- files_after snapshot
        │
files_after - files_before = new_files
        │
        ▼
rename_files(new_files)         <- optional, reads ID3 tags
        │
        ▼
Summary: files saved, rename failures, download errors
```

No state is carried between loop iterations. mloader has no persistent storage beyond the credentials file. Every run reads the filesystem fresh.

---

## Credentials File

Location: `~/.config/mloader/spotdl_creds.json`

```json
{
  "client_id": "abc123...",
  "client_secret": "xyz789..."
}
```

| Field | What it is |
|---|---|
| `client_id` | Public identifier for your Spotify Developer app |
| `client_secret` | Private key for your Spotify Developer app |

These are **not** your Spotify account credentials. They are credentials for a free Developer app you register at developer.spotify.com. Spotify uses them to rate-limit API access per app rather than per user.

The file is created by `get_spotdl_creds()` on first Spotify download and read on every subsequent one. Delete it (or use menu option 8) to trigger re-entry.

---

## Error Handling Strategy

| Layer | How errors are handled |
|---|---|
| Missing dependencies | `sys.exit(1)` on launch - clean failure before anything runs |
| Disk space | Warning printed, download proceeds - non-blocking |
| yt-dlp per-track errors | Captured by `YTDLPLogger`, displayed in summary |
| spotdl audio provider failure | `check=False`; non-zero exit triggers fallback to the next provider |
| spotdl / scdl errors | `check=False` on subprocess; non-zero exit caught and reported |
| Rename failures | Caught per-file in `try/except`; file kept, path added to `failed` list |
| Credential validation failure | Loop re-prompts until valid or user force-quits |
| Critical unexpected errors | Top-level `except Exception as e` in main loop prints error, returns to menu |
| `KeyboardInterrupt` (Ctrl+C) | Caught at entry point; prints clean exit message |

The guiding principle throughout: **never crash silently**. Every failure either prints a specific message and exits cleanly, or is caught, reported in the summary, and returns control to the main menu.

---

## Known Limitations

- **spotdl match accuracy** - spotdl searches YouTube for the Spotify track's metadata (title + artist). For regional/non-Latin tracks, live versions, or tracks with very common names, the YouTube match may be incorrect. No programmatic way to detect or fix this - requires manual verification.
- **YouTube Music pre-flight check** - spotdl's "are we blocked by YouTube Music?" check is unreliable and false-positives frequently (see "YouTube Music pre-flight check" above). mloader bypasses it with `SPOTDL_SHIM`. A genuinely throttled network can still fail during the real search; the youtube and piped fallbacks match less reliably, so the practical fix in that rarer case is to change network or wait a few minutes.
- **spotdl playlist resilience** - unlike yt-dlp which has `ignoreerrors: True`, spotdl does not have a native per-track error skip flag. A single failed track in a large playlist may cause spotdl to exit with a non-zero return code even if the other tracks downloaded successfully. The files are still saved - only the error reporting is imprecise.
- **SoundCloud muted tracks** - copyright-muted sections on SoundCloud are replaced with silence at the server level before download. mloader receives and saves the muted version. Unrecoverable from SoundCloud.
- **No download resume** - if a large playlist download is interrupted (network drop, sleep, Ctrl+C), there is no resume state. yt-dlp will skip already-existing files on a re-run (it checks filenames). spotdl has its own archive/cache mechanisms for this but they are not explicitly managed by mloader.
- **Age-restricted YouTube content** - requires browser cookies passed to yt-dlp. Not implemented.
- **Disk space is a warning, not a hard stop** - mloader warns at 1GB free but does not prevent the download. A very large playlist on a nearly-full disk will fail mid-run.
- **YouTube sync is additive only** - the yt-dlp download-archive skips already-downloaded tracks but never deletes. Only Spotify (`spotdl sync`) and SoundCloud (`scdl --sync`) remove tracks dropped from a playlist. Removing a track from a YouTube playlist leaves the file on disk.
- **Rekordbox dedup is tag-based** - the collection is deduplicated by ID3 `title + artist` (case-insensitive). Two files of the same song with inconsistent tags (e.g. "The Weeknd" vs "Weeknd, The") are treated as different tracks and both appear. Clean tags give clean dedup.
- **launchd needs the Mac awake** - the weekly automation only fires if the Mac is powered on and awake at the scheduled time; missed runs are not caught up. See `automation/README.md`.
- **Headless sync cannot enter credentials** - `--sync` uses `load_creds_noninteractive()`; if no Spotify credentials are saved, Spotify playlists are skipped (run one Spotify download interactively first).

---

## Dependencies

| Package | Type | Purpose |
|---|---|---|
| `yt-dlp` | pip | Core download engine for YouTube and all non-Spotify/SC sources |
| `spotdl` | pip | Spotify metadata resolution + YouTube audio download |
| `scdl` | pip | SoundCloud download |
| `mutagen` | pip | Read and write MP3 ID3 tags for the rename feature |
| `ffmpeg` | system | Audio extraction and MP3 conversion - called by yt-dlp internally |
| `urllib` | stdlib | Spotify credential validation HTTP request |
| `base64` | stdlib | Encoding credentials for Spotify's Basic Auth header |
| `json` | stdlib | Reading and writing the credentials config file |
| `shutil` | stdlib | `which()` for dependency checks, `disk_usage()` for space check |
| `subprocess` | stdlib | Running spotdl and scdl as external CLI processes |
| `xml.etree.ElementTree` | stdlib | Building the Rekordbox XML collection and playlist tree |
| `argparse` | stdlib | Parsing the `--sync` headless flag |
| `re` | stdlib | Slugifying playlist names into folder/file slugs |
| `os`, `sys` | stdlib | File paths, directory creation, exit handling |

No new pip packages were introduced by the sync/dedup/Rekordbox features - they use only the standard library.
