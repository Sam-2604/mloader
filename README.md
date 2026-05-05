# mloader 🎵

**mloader** is a unified, interactive Command-Line Interface (CLI) built in Python for downloading audio from various streaming platforms. It centralizes multiple top-tier downloading engines into a single, easy-to-use menu.

All downloads are automatically extracted, converted to MP3, embedded with ID3 metadata (including album art), and can optionally be renamed to a clean `Song Name - Artist.mp3` format.

## Features
* **Unified Interface**: One interactive menu to handle URLs from Spotify, YouTube, SoundCloud, Mixcloud, and Bandcamp.
* **Auto-Renaming**: Integrates with `mutagen` to parse ID3 tags and standardize file names, perfect for importing into DJ software like Rekordbox.
* **Playlist Resilience**: Handles massive playlists effortlessly. If a single track fails or is geo-blocked, `mloader` continues the batch without crashing.
* **Smart Summaries**: Tracks directory states to provide accurate, clean download summaries and specific error logs at the end of every run.

## Under the Hood
`mloader` acts as an intelligent wrapper routing URLs to the best backend engines:
* **Spotify**: Powered by [`spotdl`](https://github.com/spotDL/spotify-downloader) (Matches Spotify metadata to YouTube audio).
* **YouTube / Bandcamp / Mixcloud**: Powered by [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) Python API.
* **SoundCloud**: Powered by [`scdl`](https://github.com/flyingrub/scdl).

> **Note on Spotify Downloads:** `mloader` utilizes `spotdl` to process Spotify URLs. Because Spotify's backend is heavily DRM-protected against direct third-party rips, `spotdl` works by downloading the Spotify metadata, searching for the exact audio match on YouTube/YouTube Music, and downloading that stream (max 256kbps). 

## Prerequisites
Before running `mloader`, you must have **FFmpeg** installed on your system, as the backend engines rely on it for audio extraction and conversion.

* **macOS**: `brew install ffmpeg`
* **Windows**: `winget install ffmpeg`
* **Linux (Debian/Ubuntu)**: `sudo apt install ffmpeg`

## Installation

1. **Clone the repository** (or download the script):
   ```bash
   git clone [https://github.com/yourusername/mloader.git](https://github.com/yourusername/mloader.git)
   cd mloader