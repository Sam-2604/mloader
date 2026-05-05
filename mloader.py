#!/usr/bin/env python3

import os
import sys
import json
import shutil
import getpass
import subprocess
import yt_dlp

def check_ffmpeg():
    """Ensure ffmpeg is installed and in the system PATH."""
    if not shutil.which("ffmpeg"):
        print("❌ Error: ffmpeg is not installed or not found in PATH.")
        print("\nPlease install ffmpeg to proceed:")
        print("  macOS:  brew install ffmpeg")
        print("  Linux:  sudo apt install ffmpeg  (Debian/Ubuntu)")
        print("          sudo dnf install ffmpeg  (Fedora)")
        sys.exit(1)

def get_spotify_creds():
    """Prompt for and retrieve Spotify credentials, saving them if necessary."""
    creds_path = os.path.expanduser("~/.config/mloader/spotify_creds.json")
    os.makedirs(os.path.dirname(creds_path), exist_ok=True)

    if os.path.exists(creds_path):
        with open(creds_path, "r") as f:
            return json.load(f)
    
    print("\n--- Spotify Setup (First Run) ---")
    email = input("Spotify Email: ").strip()
    password = getpass.getpass("Spotify Password: ")
    
    creds = {"email": email, "password": password}
    with open(creds_path, "w") as f:
        json.dump(creds, f)
    
    print("✅ Credentials saved securely in ~/.config/mloader/spotify_creds.json")
    return creds

def download_ytdlp(url, output_path):
    """Download using yt-dlp Python API."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            },
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail'},
        ],
        'writethumbnail': True,
        'quiet': False
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def download_zotify(url, output_path, creds):
    """Download using zotify via subprocess."""
    cmd = [
        "zotify",
        "--username", creds["email"],
        "--password", creds["password"],
        "--output", output_path,
        "--audio-format", "mp3",
        url
    ]
    subprocess.run(cmd, check=True)

def download_scdl(url, output_path):
    """Download using scdl via subprocess."""
    cmd = [
        "scdl",
        "-l", url,
        "--path", output_path
    ]
    subprocess.run(cmd, check=True)

def main():
    check_ffmpeg()
    
    while True:
        print("\n" + "="*30)
        print("🎵 mloader - Media Downloader")
        print("="*30)
        print("1. Spotify")
        print("2. YouTube")
        print("3. YouTube Music")
        print("4. SoundCloud")
        print("5. Bandcamp")
        print("6. Mixcloud")
        print("7. Other (paste any link)")
        print("0. Exit")
        
        choice = input("\nSelect a source (0-7): ").strip()
        if choice == '0':
            print("Goodbye!")
            break
        if choice not in [str(i) for i in range(1, 8)]:
            print("❌ Invalid choice. Please try again.")
            continue

        url = input("Paste your link: ").strip()
        if not url:
            print("❌ Error: Link cannot be empty.")
            continue
            
        out_prompt = input("Output path (press Enter for ~/Music/mloader): ").strip()
        if not out_prompt:
            output_path = os.path.expanduser("~/Music/mloader")
        else:
            output_path = os.path.expanduser(out_prompt)
            
        os.makedirs(output_path, exist_ok=True)
        
        # Track files before download for summary
        try:
            files_before = set(os.listdir(output_path))
        except Exception as e:
            print(f"❌ Error accessing directory: {e}")
            continue

        print(f"\n🚀 Starting download to {output_path}...")
        
        try:
            if choice == '1':
                creds = get_spotify_creds()
                download_zotify(url, output_path, creds)
            elif choice == '4':
                download_scdl(url, output_path)
            else:
                download_ytdlp(url, output_path)
                
            # Track files after download to compute the summary
            files_after = set(os.listdir(output_path))
            new_files = files_after - files_before
            
            print("\n" + "-"*30)
            print("✅ Download Complete Summary")
            print("-"*30)
            print(f"Output Path: {output_path}")
            print(f"Files downloaded: {len(new_files)}")
            for f in new_files:
                if f.endswith('.mp3'):
                    print(f"  -> {f}")
                    
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Download failed (Command Error):")
            print(f"The underlying tool returned a non-zero exit status: {e.returncode}")
        except Exception as e:
            print(f"\n❌ Download failed:")
            print(str(e))
            
        input("\nPress Enter to return to the main menu...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user. Exiting mloader...")
        sys.exit(0)