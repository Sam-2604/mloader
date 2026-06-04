# Weekly Auto-Sync (macOS)

This folder contains a macOS scheduler file (`com.mloader.sync.plist`) that runs mloader automatically once a week, downloads anything new in your saved playlists, removes tracks you deleted from them, and regenerates your Rekordbox XML. You set it up once and then forget about it.

It uses **launchd**, the built-in macOS task scheduler (the Mac equivalent of a cron job). No extra software needed.

---

## What it does

Every **Friday at 2:00 AM**, it runs the equivalent of:

```
python mloader.py --sync
```

That is the headless version of "Sync all saved playlists" from the menu: no questions, no menu, it just syncs every playlist you saved and rewrites `~/Music/mloader/rekordbox.xml`.

> **Important:** your Mac must be **awake** at the scheduled time. If the Mac is asleep or off at 2 AM Friday, the run is skipped (it does not catch up later). If your Mac is usually asleep overnight, pick a daytime hour instead (see "Change the schedule" below).

---

## One-time setup

### Step 1 - Find your two absolute paths

Open Terminal, `cd` into your mloader folder, and run:

```bash
echo "$(pwd)/.venv/bin/python3"
echo "$(pwd)/mloader.py"
```

Copy the two lines it prints.

### Step 2 - Put those paths into the plist

Open `automation/com.mloader.sync.plist` in any text editor and replace **all** the
`/ABSOLUTE/PATH/TO/mloader/...` placeholders:

- the two paths under `ProgramArguments` (your `.venv/bin/python3` and your `mloader.py`)
- the `.venv/bin` path at the start of the `PATH` string under `EnvironmentVariables`

That `PATH` line matters: launchd runs with a bare environment that does not include
Homebrew or your virtual environment, so without it mloader cannot find ffmpeg or scdl.
The defaults already include the usual Homebrew location (`/opt/homebrew/bin`); you only
need to fix the `.venv/bin` part.

(If you do not use a `.venv`, replace the python path with the output of `which python3`,
and drop the `.venv/bin` segment from the `PATH` line.)

### Step 3 - Install it

Copy the file into your personal LaunchAgents folder and load it:

```bash
cp automation/com.mloader.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mloader.sync.plist
```

That's it. It will now run every Friday at 2 AM.

### Step 4 (optional) - Test it right now

You do not have to wait until Friday to check it works. Force a run with:

```bash
launchctl start com.mloader.sync
```

Then check the log:

```bash
cat /tmp/mloader-sync.log
cat /tmp/mloader-sync.err
```

---

## Change the schedule

Edit the `StartCalendarInterval` block in the plist:

- `Weekday`: 0 or 7 = Sunday, 1 = Monday, 2 = Tuesday, 3 = Wednesday, 4 = Thursday, 5 = Friday, 6 = Saturday
- `Hour`: 0-23 (24-hour clock)
- `Minute`: 0-59

For example, to run **every day at 6 PM**, remove the `Weekday` line and set `Hour` to `18`.

After any edit, reload it:

```bash
launchctl unload ~/Library/LaunchAgents/com.mloader.sync.plist
cp automation/com.mloader.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mloader.sync.plist
```

---

## Uninstall

To stop the weekly sync completely:

```bash
launchctl unload ~/Library/LaunchAgents/com.mloader.sync.plist
rm ~/Library/LaunchAgents/com.mloader.sync.plist
```

---

## Troubleshooting

- **Nothing happened on Friday.** The Mac was almost certainly asleep. Test manually with `launchctl start com.mloader.sync`, and consider a daytime schedule.
- **Spotify playlists were skipped.** The headless run cannot ask for credentials. Run a Spotify download once from the normal menu first so your credentials are saved, then auto-sync will use them.
- **`launchctl load` says "already loaded".** Run the `unload` command first, then `load` again.
- **Check what happened on any run:** `cat /tmp/mloader-sync.log` (normal output) and `cat /tmp/mloader-sync.err` (errors).
