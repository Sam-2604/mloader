#!/usr/bin/env python3

import os
import sys
import shutil
import subprocess
import yt_dlp

try:
    from mutagen.easyid3 import EasyID3
except ImportError:
    print("❌ Error: mutagen library is not installed.")
    print("Please install it using: pip install mutagen")
    sys.exit(1)

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
                download_errors = download_spotdl(url, output_path)
            elif choice == '4':
                download_errors = download_scdl(url, output_path)
            else:
                download_errors = download_ytdlp(url, output_path)
                
            files_after = get_all_mp3s(output_path)
            new_files = list(files_after - files_before)
            
            if should_rename and new_files:
                print("🔄 Renaming downloaded files...")
                final_files = rename_files(new_files)
            else:
                final_files = new_files
            
            print("\n" + "-"*40)
            print("✅ Download Summary")
            print("-"*40)
            print(f"Output Path: {output_path}")
            print(f"Files downloaded successfully: {len(final_files)}")
            
            for f in final_files:
                print(f"  -> {os.path.basename(f)}")
            
            if download_errors:
                print("\n⚠️ The following errors were encountered:")
                for err in download_errors:
                    clean_err = err.replace("ERROR: ", "").strip()
                    print(f"  ❌ {clean_err}")
                    
        except Exception as e:
            print(f"\n❌ A critical error occurred during the process:")
            print(str(e))
            
        input("\nPress Enter to return to the main menu...")

def print_intro():
    """Prints a brief description of what the tool does."""
    print("\n" + "="*55)
    print("🎵 mloader - Unified Media Downloader 🎵")
    print("="*55)
    print("A unified CLI tool to download music from multiple")
    print("platforms (Spotify, YouTube, SoundCloud, Bandcamp)")
    print("from a single menu. Converts all downloads to MP3")
    print("and automatically tags/renames them to the format:")
    print("'Song Name - Artist.mp3'.")
    print("="*55)

def check_dependencies():
    """
    Ensure required tools are installed and in the system PATH.
    """
    missing = False
    
    if not shutil.which("ffmpeg"):
        missing = True
        print("\n❌ Error: ffmpeg is not installed or not found in PATH.")
        print("  Windows: winget install ffmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        
    if not shutil.which("spotdl"):
        missing = True
        print("\n❌ Error: spotdl is not installed or not found in PATH.")
        print("  Install: pip install spotdl")

    if not shutil.which("scdl"):
        missing = True
        print("\n❌ Error: scdl is not installed or not found in PATH.")
        print("  Install: pip install scdl")
        
    if not shutil.which("yt-dlp"):
        missing = True
        print("\n❌ Error: yt-dlp is not installed or not found in PATH.")
        print("  Install: pip install yt-dlp")

    if missing:
        sys.exit(1)

def get_all_mp3s(directory):
    """Recursively scans the directory and returns absolute paths to all .mp3 files."""
    mp3_files = set()
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".mp3"):
                mp3_files.add(os.path.abspath(os.path.join(root, file)))
    return mp3_files

class YTDLPLogger:
    """Custom logger for yt-dlp to track specific track errors."""
    def __init__(self):
        self.errors = []
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        self.errors.append(msg)

def download_ytdlp(url, output_path):
    """Download media using the yt-dlp Python API."""
    logger = YTDLPLogger()
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'ignoreerrors': True,
        'logger': logger,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            },
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail'},
        ],
        'writethumbnail': True,
        'quiet': False
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return logger.errors

def download_spotdl(url, output_path):
    """
    Download Spotify media using spotdl via subprocess.
    SpotDL matches Spotify metadata to YouTube audio automatically.
    """
    cmd = [
        "spotdl",
        "download",
        url,
        "--format", "mp3",
        "--output", output_path
    ]
    
    result = subprocess.run(cmd, check=False)
    
    if result.returncode != 0:
        return ["SpotDL encountered an error with one or more tracks."]
    return []

def download_scdl(url, output_path):
    """Download SoundCloud media using scdl via subprocess."""
    cmd = [
        "scdl",
        "-l", url,
        "--path", output_path,
        "--onlymp3"
    ]
    result = subprocess.run(cmd, check=False)
    
    if result.returncode != 0:
        return ["SoundCloud downloader (scdl) encountered an error."]
    return []

def rename_files(new_filepaths):
    """
    Reads MP3 ID3 tags and renames files to 'Song Name - Artist.mp3'.
    """
    renamed_files = []
    for filepath in new_filepaths:
        try:
            audio = EasyID3(filepath)
            title = audio.get('title', [None])[0]
            artist = audio.get('artist', [None])[0]
            
            if title and artist:
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|')
                safe_artist = "".join(c for c in artist if c not in r'\/:*?"<>|')
                
                new_filename = f"{safe_title} - {safe_artist}.mp3"
                dir_name = os.path.dirname(filepath)
                new_filepath = os.path.join(dir_name, new_filename)
                
                if not os.path.exists(new_filepath):
                    os.rename(filepath, new_filepath)
                    renamed_files.append(new_filepath)
                else:
                    renamed_files.append(filepath) 
            else:
                renamed_files.append(filepath) 
        except Exception:
            renamed_files.append(filepath)
            
    return renamed_files

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user. Exiting mloader...")
        sys.exit(0)