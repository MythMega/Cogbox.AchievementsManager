# Cogbox.AchievementsManager

I wanted to manage (especially reset) the data inside cogbox, so I did that. Just bc the files inside cogbox are easy to read, I added some features to test stuffs. Maybe that can be useful to someone else, so feel free to use it 

A small Windows tool (built with Python + tkinter) for **viewing and modifying the data COGBox stores about your gameplay**:
unlocked achievements, the date they were earned, playtime, and the date each game in the *Gears of War* collection was last launched. All changes are made directly to files on your disk; no game processes are touched, and no injectors or external accounts are involved.

This is intended to work with Cogbox 0.6.7+ available [here](https://github.com/Shagg88/COGBox).
This project is not affiliated with any gears of war compagny, the coalition, or CogBox.

## USE IT AT YOUR OWN RISK
(later, i will put something to backup files before and manage backup)

## What the tool does

Screen 1 — **Games**: Displays a card for each game found in the COGBox folder (showing the cover art, unlocked achievements, Gamerscore, playtime, and last launch date). This screen only appears for games that actually have content stored in the folder (such as extracted data, a profile, or an achievement catalog).

Screen 2 — **Achievements for a specific game**: Includes full-text search (covering names and descriptions, ignoring accents), filters for "All / Unlocked / Locked," achievement icons, Gamerscore, and a `SECRET` flag. For each achievement, you can:

- **Unlock** → Sets the unlock date/time to the current moment.
- **✓ Unlocked** → Removes the achievement (marks it as locked).
- **Date…** → Allows you to manually set the unlock date and time (input format: `DD/MM/YYYY` + `HH:MM:SS`; includes a "Now" button).
- Top header: **Playtime** (in `H/M/S` format, with a "Reset" option) and **Last Launched** (date + time, with "Now" and "Clear" options).

IMPORTANT :
All changes are applied immediately without a confirmation prompt; files are rewritten atomically (written to a temporary file, then renamed).

## Data read and written

| Item | Location | Format |
| --- | --- | --- |
| Unlocked achievements | `<COGBox>\<Game>\user\achievements\<TitleID>.toml` | `[unlocked.<id>]` + `filetime = <100 ns since 1601>` |
| Achievements catalog (read-only) | `<COGBox>\achievements\<TitleID>\catalog.txt` | `key = value`, `[achievement]` per achievement |
| Icons (read-only) | `<COGBox>\achievements\<TitleID>\icons\<id>.png` | 64×64 PNG |
| Playtime | `<COGBox>\CogBox.ini` → `[PlayTime] <game> = <seconds>` | cumulative seconds |
| Last launched | `<COGBox>\CogBox.ini` → `[LastPlayed] <game> = <unix>` | Unix seconds |
| COGBox language (read-only) | `<COGBox>\CogBox.ini` → `[Launcher] Language = <code>` | `en`, `fr`, `pt-BR`, `zh-Hans`, `ko`, `pl`, `ru`, `hu`, `auto`… |

The game keys are those used by COGBox: `gears1`, `gears2`, `gears3`, `judgment`.
For format details and source code references, see: [docs/FORMAT.md](docs/FORMAT.md).

## Interface Language

The interface follows the language selected in COGBox: `CogBox.ini` → `[Launcher] Language`, which is re-read whenever a folder is loaded (via the **Reload** / **Folder…** button). Supported languages: **En, Fr, Pt, Zh, Ko, Pl, Ru, Cs, Hu**; any other code (including `de`, `es`, `it`, `ja`, or if the setting is missing or unknown) defaults to **English**. `auto` follows the Windows system language, just like COGBox.

## Close COGBox and the game before making changes

COGBox loads `CogBox.ini` at startup and overwrites the entire file (e.g., when exiting the game or
changing a setting). Similarly, the runtime writes its achievements `.toml` file upon exit.
Any modifications made while these processes are active will be lost. Please close the launcher
before using this tool.

## Running the tool with python

```sh
python achievements_manager.py                 # detects the COGBox folder
python achievements_manager.py --root "C:\path\to\cog"
python achievements_manager.py --selftest      # verifies read/write operations (no UI)
python achievements_manager.py --autoclose 5   # closes the window after 5 seconds (for testing)
```

The tool searches for the COGBox folder in the following order: `--root` argument, `COGBOX_ROOT`
environment variable, the last saved location (stored in `%APPDATA%\AchievementsManager\settings.ini`),
the directory containing the executable, and the current working directory. You can also select the
folder manually using the **Folder…** button in the header; your choice will be saved.

Dependencies: Python 3.8+ and tkinter (included with the standard Python installer from python.org).
[Pillow](https://python-pillow.org) is optional—if omitted, cover art and icons will not be displayed,
but all other features will continue to work.

## Compiling an `.exe`

user the bat files to generate exe in .\build\output\

→ `build\output\windows\AchievementsManager.exe` (a single file, without a console window).

Place that exe directly in cogbox root folder

## Known limitations

- Windows-only for actual use: COGBox is a Windows launcher (the code reads paths like `C:\...` and writes `.toml` files in a specific format). Also I don't have other OS to test it on there.

## AI Disclosure

Parts of the code has been