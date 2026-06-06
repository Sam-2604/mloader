#!/usr/bin/env python3

import os
import re
import sys
import json
import shutil
import argparse
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import base64
import xml.etree.ElementTree as ET
import yt_dlp

try:
    from mutagen.easyid3 import EasyID3
except ImportError:
    print("❌ Error: mutagen library is not installed.")
    print("Please install it using: pip install mutagen")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
CREDS_PATH = os.path.expanduser("~/.config/mloader/spotdl_creds.json")
SC_CREDS_PATH = os.path.expanduser("~/.config/mloader/soundcloud_creds.json")

# ── MLOADER LIBRARY ROOT ── the managed library where synced playlists live, organised
# as <root>/<source>/<playlist-slug>/. Also where rekordbox.xml is written. Change this
# one line to relocate your whole synced library (e.g. an external drive).
MLOADER_ROOT = os.path.expanduser("~/Music/mloader")

# ── DEFAULT DOWNLOAD PATH ── default destination for standalone (non-playlist) downloads.
# Accepts ~ for your home folder, or an absolute path like "/Users/you/Music".
DEFAULT_OUTPUT = os.path.expanduser("~/Music/mloader")

# Playlist sync registry + spotdl per-playlist tracking files (all outside the repo).
PLAYLISTS_PATH = os.path.expanduser("~/.config/mloader/playlists.json")
SYNC_DIR = os.path.expanduser("~/.config/mloader/sync")
REKORDBOX_XML = os.path.join(MLOADER_ROOT, "rekordbox.xml")

# Sources that can be registered for syncing, mapped to their library sub-folder.
SYNC_SOURCES = {"spotify": "spotify", "soundcloud": "soundcloud", "youtube": "youtube"}

DISK_WARN_THRESHOLD_GB = 1.0  # Warn the user if free disk space drops below this


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def main():
    print_intro()
    check_dependencies()

    # Source menu numbers -> downloader engine, for the standalone (one-off) flow.
    STANDALONE_SOURCES = {'1', '2', '3', '4', '5', '6', '7'}

    while True:
        print("\n--- Download ---")
        print("1. Spotify")
        print("2. YouTube")
        print("3. YouTube Music")
        print("4. SoundCloud")
        print("5. Bandcamp")
        print("6. Mixcloud")
        print("7. Other (paste any link)")
        print("\n--- Playlists & Sync ---")
        print("8. Save a playlist for syncing")
        print("9. List saved playlists")
        print("10. Sync all saved playlists")
        print("11. Sync specific playlists")
        print("\n--- Settings ---")
        print("12. Reset Spotify credentials")
        print("13. Reset SoundCloud credentials")
        print("0. Exit")

        choice = input("\nSelect an option (0-13): ").strip()

        if choice == '0':
            print("Goodbye!")
            break
        if choice == '8':
            add_playlist()
            continue
        if choice == '9':
            list_playlists()
            continue
        if choice == '10':
            run_sync()
            input("\nPress Enter to return to the main menu...")
            continue
        if choice == '11':
            sync_specific_playlists()
            input("\nPress Enter to return to the main menu...")
            continue
        if choice == '12':
            reset_spotdl_creds()
            continue
        if choice == '13':
            reset_scdl_creds()
            continue
        if choice not in STANDALONE_SOURCES:
            print("❌ Invalid choice. Please try again.")
            continue

        url = input("Paste your link: ").strip()
        if not url:
            print("❌ Error: Link cannot be empty.")
            continue

        out_prompt = input(f"Output path (press Enter for {DEFAULT_OUTPUT}): ").strip()
        output_path = os.path.expanduser(out_prompt) if out_prompt else DEFAULT_OUTPUT
        os.makedirs(output_path, exist_ok=True)

        # Warn early if disk is getting low - better than crashing mid-playlist
        check_disk_space(output_path)

        rename_choice = input("Rename files to 'Song Name - Artist' after download? (y/n): ").strip().lower()
        should_rename = rename_choice == 'y'

        try:
            files_before = get_all_mp3s(output_path)
        except Exception as e:
            print(f"❌ Error accessing directory: {e}")
            continue

        print(f"\n🚀 Starting download to {output_path}...")

        try:
            download_errors = []

            if choice == '1':
                creds = get_spotdl_creds()
                download_errors = download_spotdl(url, output_path, creds)
            elif choice == '4':
                token = get_scdl_token()
                download_errors = download_scdl(url, output_path, auth_token=token)
            else:
                download_errors = download_ytdlp(url, output_path)

            files_after = get_all_mp3s(output_path)
            new_files = list(files_after - files_before)

            failed_renames = []
            if should_rename and new_files:
                print("🔄 Standardizing file names...")
                final_files, failed_renames = rename_files(new_files)
            else:
                final_files = new_files

            # Standalone-only: prompt on any newly downloaded file that duplicates
            # an existing one by filename. Sync runs never prompt (handled natively).
            if final_files:
                final_files = handle_duplicate_downloads(final_files, files_before)

            # ── Summary ──
            print("\n" + "-" * 40)
            print("✅ Download Summary")
            print("-" * 40)
            print(f"Output Path   : {output_path}")
            print(f"Files saved   : {len(final_files)}")

            for f in final_files:
                print(f"  -> {os.path.basename(f)}")

            if failed_renames:
                print("\n⚠️  Could not rename (missing ID3 tags):")
                for f in failed_renames:
                    print(f"  -> {os.path.basename(f)}")

            if download_errors:
                print("\n⚠️  Errors during download:")
                for err in download_errors:
                    print(f"  ❌ {err.replace('ERROR: ', '').strip()}")

        except Exception as e:
            print(f"\n❌ A critical error occurred: {e}")

        input("\nPress Enter to return to the main menu...")


# ─────────────────────────────────────────────
# SETUP & CHECKS
# ─────────────────────────────────────────────
def print_intro():
    print("\n" + "=" * 55)
    print("🎵  mloader - Unified Media Downloader 🎵")
    print("=" * 55)
    print("Downloads from Spotify, YouTube, SoundCloud,")
    print("Bandcamp, and Mixcloud. Converts everything to")
    print("MP3 and renames to 'Song Name - Artist.mp3'.")
    print("Sync saved playlists and export a Rekordbox XML.")
    print("=" * 55)


def check_dependencies():
    """Check all required CLI tools are installed before doing anything."""
    tools = {
        "ffmpeg":  "brew install ffmpeg  /  winget install ffmpeg  /  sudo apt install ffmpeg",
        "spotdl":  "pip install spotdl",
        "scdl":    "pip install scdl",
        "yt-dlp":  "pip install yt-dlp",
    }
    missing = False
    for tool, install_hint in tools.items():
        if not shutil.which(tool):
            missing = True
            print(f"\n❌ {tool} not found in PATH.")
            print(f"   Install: {install_hint}")
    if missing:
        sys.exit(1)


def check_disk_space(path):
    """Warn the user if free disk space on the output drive is below the threshold."""
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < DISK_WARN_THRESHOLD_GB:
            print(f"\n⚠️  Warning: Only {free_gb:.1f}GB free on disk. Large downloads may fail.")
    except Exception:
        pass  # Non-critical - don't block the download if this check itself fails


# ─────────────────────────────────────────────
# SPOTIFY CREDENTIALS
# ─────────────────────────────────────────────
def validate_spotify_creds(client_id, client_secret):
    """
    Hit Spotify's token endpoint with a client_credentials grant to confirm
    the credentials work before saving them. Returns True if valid.
    Uses only stdlib (urllib) - no extra dependencies.
    """
    token_url = "https://accounts.spotify.com/api/token"
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        token_url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def get_spotdl_creds():
    """Load saved Spotify Developer credentials, or prompt and validate on first run."""
    os.makedirs(os.path.dirname(CREDS_PATH), exist_ok=True)

    if os.path.exists(CREDS_PATH):
        with open(CREDS_PATH, "r") as f:
            return json.load(f)

    print("\n--- Spotify API Setup (First Run) ---")
    print("Register a free app at: https://developer.spotify.com/dashboard")
    print("Set any Redirect URI (e.g. http://localhost:8080) when prompted there.\n")

    while True:
        client_id = input("Client ID     : ").strip()
        client_secret = input("Client Secret : ").strip()

        if not client_id or not client_secret:
            print("❌ Both fields are required. Try again.")
            continue

        print("⏳ Validating credentials with Spotify...")
        if validate_spotify_creds(client_id, client_secret):
            break
        else:
            print("❌ Credentials rejected by Spotify. Double-check your Client ID and Secret and try again.")

    creds = {"client_id": client_id, "client_secret": client_secret}
    with open(CREDS_PATH, "w") as f:
        json.dump(creds, f, indent=2)

    print(f"✅ Credentials validated and saved to {CREDS_PATH}")
    return creds


def reset_spotdl_creds():
    """Delete saved Spotify credentials so the user can re-enter them."""
    if os.path.exists(CREDS_PATH):
        os.remove(CREDS_PATH)
        print("✅ Spotify credentials cleared. You will be prompted to re-enter them on the next Spotify download.")
    else:
        print("ℹ️  No saved credentials found.")


# ─────────────────────────────────────────────
# SOUNDCLOUD CREDENTIALS
# ─────────────────────────────────────────────
def _clean_oauth(token):
    """Strip a leading 'OAuth ' prefix in case the user pasted the whole header value."""
    token = token.strip().strip('"')
    if token.lower().startswith("oauth "):
        token = token[6:].strip()
    return token


def validate_scdl_token(token):
    """
    Confirm a SoundCloud OAuth token works before saving it, mirroring how Spotify creds
    are validated. Scrapes a public client_id, then calls the authenticated /me endpoint
    with the token. Returns True if SoundCloud accepts it. Uses only stdlib (urllib).
    On a scrape/network failure it returns True (cannot prove it invalid, so don't block).
    """
    def _get(u):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    try:
        client_id = None
        for js in re.findall(r'<script[^>]+src="(https://[^"]+\.js)"', _get("https://soundcloud.com/"))[::-1]:
            try:
                m = re.search(r'client_id:"([0-9a-zA-Z]{20,})"', _get(js))
                if m:
                    client_id = m.group(1)
                    break
            except Exception:
                continue
        if not client_id:
            return True  # could not scrape a client_id; let scdl be the judge
        req = urllib.request.Request(
            f"https://api-v2.soundcloud.com/me?client_id={client_id}",
            headers={"Authorization": f"OAuth {token}", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False   # 401/403 -> token genuinely rejected
    except Exception:
        return True    # network hiccup -> don't block saving


def get_scdl_token():
    """
    Load the saved SoundCloud auth token, or prompt for it on first run, validate it, and
    save it. Returns the token string, or None if the user declines (scdl then runs
    unauthenticated).

    Many SoundCloud tracks fail to download anonymously (yt-dlp gets HTTP 403 on the audio
    stream); a logged-in OAuth token fixes that, the same way personal Spotify credentials
    fix Spotify rate limits.
    """
    os.makedirs(os.path.dirname(SC_CREDS_PATH), exist_ok=True)

    if os.path.exists(SC_CREDS_PATH):
        try:
            with open(SC_CREDS_PATH, "r") as f:
                return json.load(f).get("auth_token")
        except (json.JSONDecodeError, OSError):
            pass  # fall through to re-prompt if the file is unreadable

    print("\n--- SoundCloud Auth Setup (First Run) ---")
    print("Some SoundCloud tracks need a logged-in token to download.")
    print("Go to soundcloud.com (logged in) -> open Dev Tools (Cmd+Option+I) -> Network tab ->")
    print("play any track -> click a request to api-v2.soundcloud.com -> in Request Headers")
    print("find 'Authorization: OAuth ...' and copy the part after 'OAuth '.")
    print("It should look like '2-XXXXXX-XXXXXX-XXXXXXXXXXXX'.\n")

    while True:
        token = _clean_oauth(input("Paste your SoundCloud OAuth token (leave blank to skip): "))
        if not token:
            print("⚠️  No token entered; continuing without authentication.")
            return None
        print("⏳ Validating token with SoundCloud...")
        if validate_scdl_token(token):
            break
        print("❌ Token rejected by SoundCloud. Make sure you copied the value after 'OAuth ' "
              "(it starts with '2-'). Try again, or leave blank to skip.")

    with open(SC_CREDS_PATH, "w") as f:
        json.dump({"auth_token": token}, f, indent=2)
    print(f"✅ SoundCloud token validated and saved to {SC_CREDS_PATH}")
    return token


def load_scdl_token_noninteractive():
    """Load the saved SoundCloud token without prompting (for headless sync). None if absent."""
    if os.path.exists(SC_CREDS_PATH):
        try:
            with open(SC_CREDS_PATH, "r") as f:
                return json.load(f).get("auth_token")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def reset_scdl_creds():
    """Delete the saved SoundCloud token so the user can re-enter it."""
    if os.path.exists(SC_CREDS_PATH):
        os.remove(SC_CREDS_PATH)
        print("✅ SoundCloud token cleared. You will be prompted to re-enter it on the next SoundCloud download.")
    else:
        print("ℹ️  No saved SoundCloud token found.")


# ─────────────────────────────────────────────
# DOWNLOADERS
# ─────────────────────────────────────────────
class YTDLPLogger:
    """Captures yt-dlp errors per-track without crashing the whole run."""
    def __init__(self):
        self.errors = []
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        self.errors.append(msg)


def download_ytdlp(url, output_path, archive_path=None):
    """
    Download via yt-dlp Python API. Handles YouTube, Bandcamp, Mixcloud, and any other
    yt-dlp-supported URL.

    archive_path (optional): when set, yt-dlp records every successfully downloaded video
    ID in that file and skips IDs already listed. This is what makes YouTube playlist sync
    idempotent - re-running only fetches tracks added since last time.
    """
    logger = YTDLPLogger()
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'ignoreerrors': True,   # Skip failed tracks in playlists instead of aborting
        'logger': logger,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',  # Best available - does not upscale compressed audio
            },
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail'},
        ],
        'writethumbnail': True,
        'quiet': False,
    }
    if archive_path:
        ydl_opts['download_archive'] = archive_path
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return logger.errors


# spotdl's pre-flight "are we blocked by YouTube Music?" check is unreliable: it
# searches the single letter "a" and treats an empty result as a block. YouTube
# Music frequently returns nothing for that query even when real song searches work
# perfectly, producing a false "You are blocked by YouTube Music" error that aborts
# the whole run. We launch spotdl through this shim, which neutralises that one check
# (sets it to always pass) and then hands control to spotdl's normal entry point.
# A genuine block still fails naturally during the real search and triggers fallback.
SPOTDL_SHIM = (
    "import spotdl.console.entry_point as ep; "
    "ep.check_ytmusic_connection = lambda: True; "
    "ep.console_entry_point()"
)


def _spotdl_base():
    """
    Command prefix that runs spotdl through SPOTDL_SHIM using the current Python
    (which has spotdl installed), rather than the bare 'spotdl' binary. Append spotdl
    arguments to this. Used by both download_spotdl and the Spotify sync path so the
    broken YouTube Music check is bypassed everywhere.
    """
    return [sys.executable, "-c", SPOTDL_SHIM]


def download_spotdl(url, output_path, creds):
    """
    Download Spotify tracks via spotdl using your own Developer API credentials.
    spotdl matches Spotify metadata to YouTube/YouTube Music audio, then converts to mp3.
    Output is named by spotdl's own template so rename_files can standardise it afterward.

    Two spotdl quirks are worked around here:

    1. --no-cache: spotdl otherwise caches the Spotify token at ~/.spotdl/.spotipy and
       reuses it even when you pass different credentials. A stale token from a DIFFERENT
       (rate-limited) app produces a bogus "rate/request limit, retry after 86400 s" error.
       --no-cache forces a fresh token from the credentials below on every run.

    2. SPOTDL_SHIM: spotdl's YouTube Music pre-flight check false-positives as "blocked"
       (see comment above SPOTDL_SHIM). We run spotdl through the shim so that broken check
       can't abort an otherwise-working download.

    youtube-music gives by far the best matches and is tried first; plain youtube and piped
    are weaker fallbacks for the rare case youtube-music genuinely fails.
    """
    # ── AUDIO PROVIDER FALLBACK ORDER ── tweak this list to change which sources
    # spotdl tries (valid: youtube-music, youtube, piped, soundcloud, bandcamp).
    provider_chain = ["youtube-music", "youtube", "piped"]

    for i, provider in enumerate(provider_chain):
        # Launch spotdl via the shim (see _spotdl_base) so the broken check is bypassed.
        cmd = _spotdl_base() + [
            "download", url,
            "--format", "mp3",
            "--output", output_path,
            "--client-id", creds["client_id"],
            "--client-secret", creds["client_secret"],
            "--audio", provider,
            "--bitrate", "auto",   # keep best source quality, do not re-encode down
            "--no-cache",          # always mint a fresh token from the creds above (see docstring)
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            return []

        # Failed - fall through to the next provider if one is available
        if i < len(provider_chain) - 1:
            next_provider = provider_chain[i + 1]
            print(f"\n⚠️  spotdl failed with '{provider}'. Retrying with '{next_provider}'...")

    return [
        "SpotDL failed with every audio provider. Try again in a moment; if it persists, "
        "your network may be genuinely blocking YouTube (switch network or use a VPN). "
        "Your Spotify credentials are fine."
    ]


def download_scdl(url, output_path, auth_token=None):
    """
    Download SoundCloud tracks via scdl. --onlymp3 enforces mp3 output regardless of source
    format. auth_token (optional): a SoundCloud OAuth token passed as --auth-token, which
    lets scdl download tracks that fail anonymously (HTTP 403 on the audio stream).
    """
    cmd = [
        "scdl",
        "-l", url,
        "--path", output_path,
        "--onlymp3",
    ]
    if auth_token:
        cmd += ["--auth-token", auth_token]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return ["scdl encountered an error. Check the console output above for details."]
    return []


# ─────────────────────────────────────────────
# PLAYLIST REGISTRY
# ─────────────────────────────────────────────
def slugify(name):
    """Turn a playlist name into a safe folder slug: lowercase, spaces -> hyphens."""
    s = name.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)   # drop anything that isn't word char, space or hyphen
    s = re.sub(r"[\s_]+", "-", s)    # collapse spaces/underscores to single hyphens
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "playlist"


def load_registry():
    """Return the list of saved playlists from playlists.json (empty list if none)."""
    if os.path.exists(PLAYLISTS_PATH):
        try:
            with open(PLAYLISTS_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print("⚠️  playlists.json is unreadable; treating as empty.")
    return []


def save_registry(registry):
    """Write the playlist list back to playlists.json."""
    os.makedirs(os.path.dirname(PLAYLISTS_PATH), exist_ok=True)
    with open(PLAYLISTS_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def load_creds_noninteractive():
    """Load saved Spotify credentials without prompting. Returns dict or None."""
    if os.path.exists(CREDS_PATH):
        try:
            with open(CREDS_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def add_playlist():
    """
    Menu action: register a playlist for syncing. Prompts for name + source + URL,
    computes its managed output folder (<root>/<source>/<slug>), and appends it to
    the registry. For Spotify it also assigns a spotdl sync-tracking file.
    """
    print("\n--- Save a Playlist for Syncing ---")
    name = input("Playlist name: ").strip()
    if not name:
        print("❌ Name cannot be empty.")
        return

    print("Source:  1. Spotify   2. SoundCloud   3. YouTube")
    src_map = {"1": "spotify", "2": "soundcloud", "3": "youtube"}
    source = src_map.get(input("Select source (1-3): ").strip())
    if not source:
        print("❌ Invalid source.")
        return

    url = input("Playlist URL: ").strip()
    if not url:
        print("❌ URL cannot be empty.")
        return

    slug = slugify(name)
    output_path = os.path.join(MLOADER_ROOT, SYNC_SOURCES[source], slug)
    sync_file = os.path.join(SYNC_DIR, f"{slug}.spotdl") if source == "spotify" else None

    registry = load_registry()
    if any(p["name"] == slug and p["source"] == source for p in registry):
        print(f"⚠️  A {source} playlist named '{slug}' is already saved. Not adding a duplicate.")
        return

    registry.append({
        "name": slug,
        "source": source,
        "url": url,
        "output_path": output_path,
        "sync_file": sync_file,
    })
    save_registry(registry)
    os.makedirs(output_path, exist_ok=True)
    print(f"✅ Saved '{slug}' ({source}). It will download to {output_path} on the next sync.")


def list_playlists():
    """Menu action: print every saved playlist in the registry."""
    registry = load_registry()
    if not registry:
        print("\nNo playlists saved yet. Use 'Save a playlist for syncing' first.")
        return
    print(f"\n--- Saved Playlists ({len(registry)}) ---")
    for p in registry:
        print(f"\n  {p['name']}  [{p['source']}]")
        print(f"    URL    : {p['url']}")
        print(f"    Folder : {p['output_path']}")


# ─────────────────────────────────────────────
# SYNC
# ─────────────────────────────────────────────
def run_sync(entries=None):
    """
    Sync registered playlists, then regenerate the Rekordbox XML. Has no prompts, so it
    backs menu option 10, the headless `--sync` flag, and the selective-sync paths.

    entries: the list of registry entries to sync. When None (the default), every saved
    playlist is synced - so `run_sync()` with no arguments behaves exactly as before.
    """
    check_dependencies()
    registry = load_registry()
    if not registry:
        print("No saved playlists to sync. Use 'Save a playlist for syncing' first.")
        return

    if entries is None:
        entries = registry
    if not entries:
        print("No matching playlists to sync.")
        return

    creds = load_creds_noninteractive()
    sc_token = load_scdl_token_noninteractive()
    print(f"\n🔄 Syncing {len(entries)} playlist(s)...")
    sync_issues = {}   # playlist name -> list of notable lines
    for entry in entries:
        try:
            errs = sync_one_playlist(entry, creds, sc_token)
            if errs:
                sync_issues[entry.get("name")] = errs
        except Exception as e:
            sync_issues[entry.get("name")] = [f"Critical error: {e}"]
            print(f"❌ Error syncing '{entry.get('name')}': {e}")

    print("\n🎛️  Generating Rekordbox XML...")
    count = generate_rekordbox_xml()
    print(f"✅ Rekordbox XML written to {REKORDBOX_XML} ({count} unique tracks).")

    if sync_issues:
        print("\n" + "-" * 40)
        print("⚠️  Sync notices (errors / failed / skipped / not found)")
        print("-" * 40)
        for pname, errs in sync_issues.items():
            print(f"\n[{pname}]")
            for line in errs:
                print(f"  - {line.replace('ERROR: ', '').strip()}")


def sync_specific_playlists():
    """
    Menu action: show the registry numbered, let the user pick a comma-separated list
    of numbers (e.g. 1,3,5), and sync only those - in the order typed - then regenerate
    the XML via run_sync().
    """
    registry = load_registry()
    if not registry:
        print("\nNo playlists saved yet. Use 'Save a playlist for syncing' first.")
        return

    print("\n--- Sync Specific Playlists ---")
    for i, p in enumerate(registry, start=1):
        print(f"  {i}. {p['name']}  [{p['source']}]")

    raw = input("\nEnter numbers to sync (comma-separated, e.g. 1,3,5): ").strip()
    if not raw:
        print("Nothing selected.")
        return

    selected = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit() or not (1 <= int(token) <= len(registry)):
            print(f"⚠️  Ignoring invalid entry '{token}'.")
            continue
        entry = registry[int(token) - 1]
        if entry not in selected:   # de-dupe repeated numbers, keep first position
            selected.append(entry)

    if not selected:
        print("No valid playlists selected.")
        return
    run_sync(entries=selected)


def sync_playlists_by_name(names):
    """
    Headless helper for --sync-playlist / --sync-playlists. Resolves each given name to
    its registry entry (matching the slugified name, so "House Vibes" and "house-vibes"
    both work) and syncs the matches in order, then regenerates the XML via run_sync().
    A name can match more than one entry if the same playlist name exists on two sources.
    """
    registry = load_registry()
    if not registry:
        print("No saved playlists to sync. Use 'Save a playlist for syncing' first.")
        return

    selected = []
    for name in names:
        slug = slugify(name)
        hits = [e for e in registry if e["name"] == slug]
        if not hits:
            print(f"⚠️  No saved playlist named '{slug}'.")
            continue
        for h in hits:
            if h not in selected:
                selected.append(h)

    if not selected:
        print("No matching playlists to sync.")
        return
    run_sync(entries=selected)


# Lines in spotdl/scdl output matching any of these (case-insensitive) are surfaced
# individually in the sync summary, the same way yt-dlp's captured errors are.
SYNC_ERROR_KEYWORDS = ("error", "failed", "skipped", "not found")


def _run_and_capture(cmd):
    """
    Run a command attached to a pseudo-terminal (pty) and tee its output: the tool renders
    its FULL real-time UI to the console - colours, green download indicators, progress
    bars, and the "retry will occur after Xs" countdowns - exactly as if run directly,
    while we also capture every byte and return it as text for error parsing.

    Why a pty and not a plain pipe: spotdl and scdl (via rich/curses-style output) detect
    when stdout is not a terminal and strip colours, drop progress bars, and block-buffer.
    A pty makes them believe they are on a real terminal, so none of that live feedback is
    lost. Falls back to a line-streamed pipe only where pty is unavailable (e.g. Windows).
    """
    try:
        import pty
    except ImportError:
        return _run_and_capture_pipe(cmd)

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)  # only the child writes to the slave side

    chunks = []
    try:
        while True:
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break  # EIO is raised when the child closes the pty on exit (expected)
            if not data:
                break
            sys.stdout.buffer.write(data)   # pass raw bytes through: keeps colours and \r
            sys.stdout.buffer.flush()
            chunks.append(data)
    finally:
        os.close(master_fd)
        proc.wait()
    return b"".join(chunks).decode("utf-8", errors="replace")


def _run_and_capture_pipe(cmd):
    """Fallback tee for platforms without pty: stream lines live while capturing them."""
    captured = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(line, end="")
        captured.append(line)
    proc.wait()
    return "".join(captured)


# Matches ANSI colour/cursor escape sequences so captured lines are clean in the summary.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _parse_sync_errors(text):
    """
    Pull notable lines out of captured sync output - those containing any of
    SYNC_ERROR_KEYWORDS (case-insensitive) - so they appear individually in the sync
    summary. ANSI colour codes are stripped and exact duplicates collapsed for a clean
    summary. Rate-limit retry countdowns ("retry will occur after Xs") are normal progress,
    not errors, so they are explicitly excluded.
    """
    found = []
    seen = set()
    # splitlines() also breaks on \r, so progress-bar fragments are handled too.
    for raw in text.splitlines():
        line = _ANSI_RE.sub("", raw).strip()
        if not line or line in seen:
            continue
        low = line.lower()
        if "retry will occur" in low:
            continue  # spotdl rate-limit countdown - feedback, not an error
        if any(k in low for k in SYNC_ERROR_KEYWORDS):
            seen.add(line)
            found.append(line)
    return found


def sync_one_playlist(entry, creds, sc_token=None):
    """
    Sync a single registered playlist with its source's native sync mechanism:
      - spotify    : `spotdl sync` (handles new downloads AND deletions on its own)
      - soundcloud : `scdl --sync` against a per-folder archive
      - youtube    : yt-dlp with a download-archive so existing tracks are skipped
    New files are renamed to the standard 'Song - Artist.mp3' afterward.

    sc_token (optional): a SoundCloud OAuth token passed to scdl as --auth-token so it can
    download tracks that fail anonymously.

    Returns a list of notable lines (errors / failures / skips / not-found) so they show
    up individually in the sync summary. For spotdl and scdl, output is teed to the
    console live and captured, then scanned for SYNC_ERROR_KEYWORDS; for youtube the
    yt-dlp logger's own error list is returned.
    """
    name = entry["name"]
    source = entry["source"]
    url = entry["url"]
    output_path = os.path.expanduser(entry["output_path"])
    os.makedirs(output_path, exist_ok=True)

    print(f"\n── {name} [{source}] ──")
    files_before = get_all_mp3s(output_path)
    errors = []

    if source == "spotify":
        if not creds:
            print("  ⏭️  Skipped: no Spotify credentials saved (run a Spotify download once to set them up).")
            return []
        sync_file = os.path.expanduser(entry["sync_file"])
        os.makedirs(os.path.dirname(sync_file), exist_ok=True)
        # Give spotdl an explicit filename template so it both writes AND looks for files
        # under the same deterministic name on every run. spotdl sync decides what to skip
        # by checking whether this exact path exists, so we must NOT rename these files
        # afterwards (doing so made spotdl re-download the whole playlist each sync).
        out_template = os.path.join(output_path, "{title} - {artist}.{output-ext}")
        if os.path.exists(sync_file):
            # Subsequent run: re-sync from the tracking file (adds new, removes deleted).
            cmd = _spotdl_base() + [
                "sync", sync_file,
                "--output", out_template,
                "--client-id", creds["client_id"],
                "--client-secret", creds["client_secret"],
                "--bitrate", "auto", "--no-cache",
            ]
        else:
            # First run: download everything and create the tracking file.
            cmd = _spotdl_base() + [
                "sync", url,
                "--save-file", sync_file,
                "--output", out_template,
                "--format", "mp3",
                "--client-id", creds["client_id"],
                "--client-secret", creds["client_secret"],
                "--bitrate", "auto", "--no-cache",
            ]
        errors = _parse_sync_errors(_run_and_capture(cmd))

    elif source == "soundcloud":
        # scdl --sync compares the playlist against an archive db and downloads/removes
        # changed tracks. The archive lives inside the playlist folder.
        archive = os.path.join(output_path, ".sync_archive")
        cmd = [
            "scdl", "-l", url,
            "--sync", archive,
            "--path", output_path,
            "--onlymp3",
        ]
        if sc_token:
            cmd += ["--auth-token", sc_token]
        errors = _parse_sync_errors(_run_and_capture(cmd))

    elif source == "youtube":
        # A download-archive makes re-runs skip already-fetched videos.
        archive = os.path.join(output_path, ".archive.txt")
        errors = download_ytdlp(url, output_path, archive_path=archive)

    else:
        print(f"  ⏭️  Skipped: unknown source '{source}'.")
        return [f"Unknown source '{source}'"]

    files_after = get_all_mp3s(output_path)
    new_files = list(files_after - files_before)
    # Spotify files are already named by spotdl's template (see the spotify branch).
    # Renaming them would break spotdl sync's "already downloaded" check and cause it to
    # re-download the whole playlist next time, so only rename SoundCloud/YouTube files.
    if new_files and source != "spotify":
        rename_files(new_files)
    print(f"  ✓ {len(new_files)} new track(s).")
    return errors


# ─────────────────────────────────────────────
# FILE UTILITIES
# ─────────────────────────────────────────────
def get_all_mp3s(directory):
    """Recursively returns absolute paths of all .mp3 files under directory."""
    mp3_files = set()
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".mp3"):
                mp3_files.add(os.path.abspath(os.path.join(root, file)))
    return mp3_files


def rename_files(new_filepaths):
    """
    Reads ID3 tags and renames each file to 'Song Name - Artist.mp3'.
    Returns (successfully_handled, failed_due_to_missing_tags).
    Files that can't be renamed are kept under their original name and reported separately.
    """
    renamed = []
    failed = []

    for filepath in new_filepaths:
        try:
            audio = EasyID3(filepath)
            title = audio.get('title', [None])[0]
            artist = audio.get('artist', [None])[0]

            if title and artist:
                # Strip characters that are illegal in filenames across macOS/Windows/Linux
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|')
                safe_artist = "".join(c for c in artist if c not in r'\/:*?"<>|')
                new_filename = f"{safe_title} - {safe_artist}.mp3"
                new_filepath = os.path.join(os.path.dirname(filepath), new_filename)

                if not os.path.exists(new_filepath):
                    os.rename(filepath, new_filepath)
                    renamed.append(new_filepath)
                else:
                    renamed.append(filepath)  # Collision - keep original, still counts as downloaded
            else:
                renamed.append(filepath)
                failed.append(filepath)
        except Exception:
            renamed.append(filepath)
            failed.append(filepath)

    return renamed, failed


def handle_duplicate_downloads(final_files, files_before):
    """
    Standalone-only duplicate guard. For each newly downloaded file whose filename
    matches one that already existed (anywhere under the output path, captured in
    files_before), prompt the user to keep both, skip (delete the new copy), or
    replace (delete the old copy). Returns the list of files that survive.

    Sync runs never call this - dedup there is handled natively by each engine and
    by the Rekordbox collection dedup.
    """
    existing_by_name = {}
    for p in files_before:
        existing_by_name.setdefault(os.path.basename(p), []).append(p)

    survivors = []
    for f in final_files:
        dupes = [d for d in existing_by_name.get(os.path.basename(f), [])
                 if os.path.abspath(d) != os.path.abspath(f)]
        if not dupes:
            survivors.append(f)
            continue

        print(f"\n⚠️  '{os.path.basename(f)}' already exists at:")
        for d in dupes:
            print(f"     {d}")
        ans = input("   [b]oth (keep) / [s]kip (delete new) / [r]eplace existing? ").strip().lower()

        if ans == "s":
            _safe_remove(f)
            print("   Skipped: new copy deleted.")
        elif ans == "r":
            for d in dupes:
                _safe_remove(d)
            survivors.append(f)
            print("   Replaced: old copy deleted.")
        else:
            survivors.append(f)
            print("   Kept both.")
    return survivors


def _safe_remove(path):
    """Delete a file, ignoring errors (best-effort cleanup)."""
    try:
        os.remove(path)
    except OSError:
        pass


# ─────────────────────────────────────────────
# REKORDBOX XML EXPORT
# ─────────────────────────────────────────────
def _read_tags(filepath):
    """Return (title, artist, album) from a file's ID3 tags, falling back to the
    filename for a missing title and empty strings for missing artist/album."""
    title = artist = album = None
    try:
        audio = EasyID3(filepath)
        title = (audio.get("title") or [None])[0]
        artist = (audio.get("artist") or [None])[0]
        album = (audio.get("album") or [None])[0]
    except Exception:
        pass
    if not title:
        title = os.path.splitext(os.path.basename(filepath))[0]
    return title, (artist or ""), (album or "")


def _track_key(title, artist):
    """Case-insensitive identity for a track, used to deduplicate the collection."""
    return (title.strip().lower(), artist.strip().lower())


def _file_uri(path):
    """Build a Rekordbox-style file://localhost/ URL with the path percent-encoded."""
    return "file://localhost" + urllib.parse.quote(os.path.abspath(path))


def _build_collection(root_dir):
    """
    Scan every mp3 under root_dir and build the deduplicated collection.
    Returns (collection, file_to_key) where:
      - collection: {key -> {"id", "name", "artist", "album", "location"}}
        with one entry per unique title+artist, even if it exists as several files
      - file_to_key: {absolute_mp3_path -> key} for resolving playlist membership
    """
    collection = {}
    file_to_key = {}
    next_id = 1
    for mp3 in sorted(get_all_mp3s(root_dir)):
        title, artist, album = _read_tags(mp3)
        key = _track_key(title, artist)
        if key not in collection:
            collection[key] = {
                "id": next_id,
                "name": title,
                "artist": artist,
                "album": album,
                "location": _file_uri(mp3),
            }
            next_id += 1
        file_to_key[mp3] = key
    return collection, file_to_key


def _playlist_node(name, mp3_paths, file_to_key, collection):
    """Build a Type 1 (playlist) NODE referencing each track's collection TrackID once."""
    seen = set()
    track_ids = []
    for p in sorted(mp3_paths):
        key = file_to_key.get(os.path.abspath(p))
        if key and key not in seen:
            seen.add(key)
            track_ids.append(collection[key]["id"])
    node = ET.Element("NODE", Type="1", Name=name, KeyType="0", Entries=str(len(track_ids)))
    for tid in track_ids:
        ET.SubElement(node, "TRACK", Key=str(tid))
    return node


def _dir_to_node(dir_path, name, file_to_key, collection):
    """
    Recursively turn a directory into a Rekordbox NODE mirroring the folder layout:
      - a folder with sub-folders becomes a Type 0 (folder) node
      - a folder with mp3s becomes a Type 1 (playlist) node
      - a folder with both gets sub-folder nodes plus a playlist node for its own tracks
    Returns None for empty directories so they are skipped.
    """
    entries = sorted(os.listdir(dir_path))
    subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
    direct_mp3s = [os.path.join(dir_path, e) for e in entries if e.lower().endswith(".mp3")]

    child_nodes = []
    for d in subdirs:
        child = _dir_to_node(os.path.join(dir_path, d), d, file_to_key, collection)
        if child is not None:
            child_nodes.append(child)

    has_tracks = len(direct_mp3s) > 0

    if child_nodes and has_tracks:
        folder = ET.Element("NODE", Type="0", Name=name, Count=str(len(child_nodes) + 1))
        for c in child_nodes:
            folder.append(c)
        folder.append(_playlist_node(name, direct_mp3s, file_to_key, collection))
        return folder
    if child_nodes:
        folder = ET.Element("NODE", Type="0", Name=name, Count=str(len(child_nodes)))
        for c in child_nodes:
            folder.append(c)
        return folder
    if has_tracks:
        return _playlist_node(name, direct_mp3s, file_to_key, collection)
    return None


def generate_rekordbox_xml():
    """
    Build ~/Music/mloader/rekordbox.xml from the whole managed library.

    The <COLLECTION> holds each unique track (by title+artist, case-insensitive) exactly
    once, even when the same song exists as multiple files in different folders. The
    <PLAYLISTS> tree mirrors the folder structure, and a song that lives in two folders is
    referenced by its single TrackID in both playlist nodes. Returns the unique track count.
    """
    if not os.path.isdir(MLOADER_ROOT):
        print(f"⚠️  Library root {MLOADER_ROOT} does not exist yet; nothing to export.")
        return 0

    collection, file_to_key = _build_collection(MLOADER_ROOT)

    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="mloader", Version="1.0", Company="mloader")

    collection_el = ET.SubElement(root, "COLLECTION", Entries=str(len(collection)))
    for track in sorted(collection.values(), key=lambda t: t["id"]):
        ET.SubElement(
            collection_el, "TRACK",
            TrackID=str(track["id"]),
            Name=track["name"],
            Artist=track["artist"],
            Album=track["album"],
            Kind="MP3 File",
            Location=track["location"],
        )

    playlists_el = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(playlists_el, "NODE", Type="0", Name="ROOT")

    children = 0
    for entry in sorted(os.listdir(MLOADER_ROOT)):
        full = os.path.join(MLOADER_ROOT, entry)
        if os.path.isdir(full):
            node = _dir_to_node(full, entry, file_to_key, collection)
            if node is not None:
                root_node.append(node)
                children += 1
    # Any mp3s sitting loose directly in the library root become their own playlist.
    loose = [os.path.join(MLOADER_ROOT, e) for e in sorted(os.listdir(MLOADER_ROOT))
             if e.lower().endswith(".mp3")]
    if loose:
        root_node.append(_playlist_node("loose", loose, file_to_key, collection))
        children += 1
    root_node.set("Count", str(children))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(REKORDBOX_XML, encoding="UTF-8", xml_declaration=True)
    return len(collection)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="mloader - unified media downloader with playlist sync and Rekordbox export."
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Headless mode: sync ALL saved playlists and regenerate rekordbox.xml, then exit. "
             "No menu, no prompts (used by the weekly automation).",
    )
    parser.add_argument(
        "--sync-playlist",
        metavar="NAME",
        help="Headless mode: sync a single saved playlist by its registered name, then exit. "
             "Example: python mloader.py --sync-playlist house-vibes",
    )
    parser.add_argument(
        "--sync-playlists",
        metavar="NAME1,NAME2,...",
        help="Headless mode: sync several saved playlists by name (comma-separated), then exit. "
             "Example: python mloader.py --sync-playlists english,hindi-party,edm",
    )
    args = parser.parse_args()

    try:
        if args.sync:
            run_sync()
        elif args.sync_playlist:
            sync_playlists_by_name([args.sync_playlist])
        elif args.sync_playlists:
            names = [n.strip() for n in args.sync_playlists.split(",") if n.strip()]
            sync_playlists_by_name(names)
        else:
            main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. Exiting mloader...")
        sys.exit(0)