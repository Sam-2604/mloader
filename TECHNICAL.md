# mloader - Technical Documentation

## Project Structure

```
mloader/
├── mloader.py          # Single-file program - all logic lives here
├── requirements.txt    # Python package dependencies
├── README.md           # User-facing setup and usage guide
└── TECHNICAL.md        # This file
```

External config written at runtime:
```
~/.config/mloader/
└── spotdl_creds.json   # Spotify Developer API credentials (created on first Spotify download)
```

spotdl also keeps its own config and token cache (created/managed by spotdl, not mloader):
```
~/.spotdl/
├── config.json         # spotdl defaults (audio providers, bitrate, etc.)
└── .spotipy            # cached Spotify access token (mloader bypasses this with --no-cache)
```

Default download output (user-configurable per run):
```
~/Music/mloader/
```

---

## Architecture Overview

mloader is a single-file CLI wrapper. It has no classes for orchestration - all logic is organised into standalone functions grouped by responsibility. The `main()` loop handles user input and orchestrates calls to the downloader functions.

```
main()
  ├── print_intro()              <- banner on launch
  ├── check_dependencies()       <- verify ffmpeg, spotdl, scdl, yt-dlp are in PATH
  │
  └── [loop]
        ├── input: source choice, url, output path, rename preference
        ├── check_disk_space()   <- warn if <1GB free before starting
        ├── get_all_mp3s()       <- snapshot of output dir before download
        │
        ├── download_spotdl()    <- if choice == 1 (Spotify)
        │     └── get_spotdl_creds()
        │           └── validate_spotify_creds()   <- first run only
        ├── download_scdl()      <- if choice == 4 (SoundCloud)
        └── download_ytdlp()     <- all other sources
        │
        ├── get_all_mp3s()       <- snapshot after download; diff gives new files
        ├── rename_files()       <- optional; reads ID3 tags, renames to standard format
        └── summary block        <- prints results and errors
```

The program never stores any in-memory state between loop iterations. Each download cycle is independent: inputs collected fresh, snapshots taken fresh, errors reported fresh.

---

## Constants

```python
CREDS_PATH = os.path.expanduser("~/.config/mloader/spotdl_creds.json")
DEFAULT_OUTPUT = os.path.expanduser("~/Music/mloader")
DISK_WARN_THRESHOLD_GB = 1.0
```

`os.path.expanduser()` resolves the `~` home directory symbol correctly on macOS, Linux, and Windows. These are defined at the top of the file so they can be changed in one place without hunting through the code. To change the default download folder, edit `DEFAULT_OUTPUT` - it accepts `~` or an absolute path.

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

### `download_ytdlp(url, output_path)`
- **Purpose:** Download audio from YouTube, YouTube Music, Bandcamp, Mixcloud, or any other yt-dlp-supported URL.
- **Input:** URL string, output directory path string.
- **Output:** List of error strings (empty if everything succeeded).
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
- **How it works:** Calls spotdl as a subprocess, once per audio provider in a fallback chain, with:
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
- **YouTube Music IP blocks** - spotdl runs a pre-flight check that aborts the run with "You are blocked by YouTube Music" when YouTube is throttling your IP. This is intermittent and IP-based. mloader falls back to the youtube and piped providers, but those match less reliably. The fastest fix is to change your IP (mobile data, hotspot, or VPN) or wait a few minutes.
- **spotdl playlist resilience** - unlike yt-dlp which has `ignoreerrors: True`, spotdl does not have a native per-track error skip flag. A single failed track in a large playlist may cause spotdl to exit with a non-zero return code even if the other tracks downloaded successfully. The files are still saved - only the error reporting is imprecise.
- **SoundCloud muted tracks** - copyright-muted sections on SoundCloud are replaced with silence at the server level before download. mloader receives and saves the muted version. Unrecoverable from SoundCloud.
- **No download resume** - if a large playlist download is interrupted (network drop, sleep, Ctrl+C), there is no resume state. yt-dlp will skip already-existing files on a re-run (it checks filenames). spotdl has its own archive/cache mechanisms for this but they are not explicitly managed by mloader.
- **Age-restricted YouTube content** - requires browser cookies passed to yt-dlp. Not implemented.
- **Disk space is a warning, not a hard stop** - mloader warns at 1GB free but does not prevent the download. A very large playlist on a nearly-full disk will fail mid-run.

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
| `os`, `sys` | stdlib | File paths, directory creation, exit handling |
