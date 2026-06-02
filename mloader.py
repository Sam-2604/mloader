#!/usr/bin/env python3

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import base64
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
# ── DEFAULT DOWNLOAD PATH ── change this line to set where downloads go by default.
# Accepts ~ for your home folder, or an absolute path like "/Users/you/Music".
DEFAULT_OUTPUT = os.path.expanduser("~/Music/mloader")
DISK_WARN_THRESHOLD_GB = 1.0  # Warn the user if free disk space drops below this


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def main():
    print_intro()
    check_dependencies()

    while True:
        print("\n1. Spotify")
        print("2. YouTube")
        print("3. YouTube Music")
        print("4. SoundCloud")
        print("5. Bandcamp")
        print("6. Mixcloud")
        print("7. Other (paste any link)")
        print("8. Reset Spotify credentials")
        print("0. Exit")

        choice = input("\nSelect a source (0-8): ").strip()

        if choice == '0':
            print("Goodbye!")
            break

        if choice == '8':
            reset_spotdl_creds()
            continue

        if choice not in [str(i) for i in range(1, 8)]:
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
                download_errors = download_scdl(url, output_path)
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


def download_ytdlp(url, output_path):
    """Download via yt-dlp Python API. Handles YouTube, Bandcamp, Mixcloud, and any other yt-dlp-supported URL."""
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
        # Launch spotdl via the current Python (which has spotdl installed) using the
        # shim, instead of the bare "spotdl" binary, so the broken check is bypassed.
        cmd = [
            sys.executable, "-c", SPOTDL_SHIM,
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


def download_scdl(url, output_path):
    """Download SoundCloud tracks via scdl. --onlymp3 enforces mp3 output regardless of source format."""
    cmd = [
        "scdl",
        "-l", url,
        "--path", output_path,
        "--onlymp3",
    ]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return ["scdl encountered an error. Check the console output above for details."]
    return []


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


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. Exiting mloader...")
        sys.exit(0)