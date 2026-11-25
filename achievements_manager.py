import argparse
import backup
import i18n
import os
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

FILETIME_UNIX_DELTA = 116_444_736_000_000_000  # 1601-01-01 -> 1970-01-01, en 100 ns
TICKS_PER_SECOND = 10_000_000

CATALOG_HEADER = "# COGBox achievement catalog"
TOML_HEADER = "# Achievement unlock state - managed by ReXGlue runtime"
SHOW_UNACHIEVED_FLAG = 0x8  # sans ce drapeau, le succès est secret

INI_NAME = "CogBox.ini"
INI_PLAY_SECTION = "PlayTime"
INI_LAST_SECTION = "LastPlayed"

# Ordre de COGBox (achievements_data.cpp, kGames) ; le dossier du jeu est aussi sa clé dans CogBox.ini.
GAMES = [
    ("Gears1", "4D5307D5", "Gears of War", "gears1"),
    ("Gears2", "4D53082D", "Gears of War 2", "gears2"),
    ("Gears3", "4D5308AB", "Gears of War 3", "gears3"),
    ("Judgment", "4D530A26", "Gears of War: Judgment", "judgment"),
]

BG = "#14161b"
PANEL = "#1b1f27"
CARD = "#1f242e"
CARD_SEL = "#232a36"
BORDER = "#2c313d"
TEXT = "#e6e8ee"
MUTED = "#8b93a7"
ACCENT = "#3fb950"
ACCENT_DARK = "#2ea043"
GOLD = "#e3b341"


# ---------------------------------------------------------------- temps

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def filetime_to_local(ft):
    """FILETIME -> datetime local (à la microseconde près), ou None."""
    if not ft:
        return None
    try:
        dt = FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None
    return dt.astimezone().replace(tzinfo=None)


def local_to_filetime(dt):
    """datetime (local si naïf) -> FILETIME : 100 ns depuis 1601-01-01 UTC. Calcul entier, sans float."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    delta = dt.astimezone(timezone.utc) - FILETIME_EPOCH
    return (delta.days * 86400 + delta.seconds) * TICKS_PER_SECOND + delta.microseconds * 10


def fmt_time(ft):
    dt = filetime_to_local(ft)
    return dt.strftime("%d/%m/%Y %H:%M") if dt else i18n.t("unknown_date")


def fmt_duration(seconds):
    """Comme human_duration() de COGBox (util.cpp)."""
    s = int(seconds or 0)
    if s <= 0:
        return "—"
    if s < 60:
        return i18n.t("less_minute")
    m, h = s // 60 % 60, s // 3600
    if h == 0:
        return i18n.t("dur_min", m=m)
    if m == 0:
        return i18n.t("dur_hour", h=h)
    return i18n.t("dur_hour_min", h=h, m=m)


def fmt_unix_local(t):
    """Date Unix -> texte local, ou None."""
    try:
        return datetime.fromtimestamp(int(t)).strftime("%d/%m/%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return None


def fmt_last_played(t):
    """Texte relatif, comme last_played_text() de COGBox (front.cpp)."""
    t = int(t or 0)
    if t <= 0:
        return i18n.t("never_launched")
    ago = int(datetime.now().timestamp()) - t
    if ago < 0:
        return i18n.t("rel_now")
    if ago < 3600:
        return i18n.t("rel_now")
    if ago < 86400:
        return i18n.t("rel_today")
    if ago < 2 * 86400:
        return i18n.t("rel_yesterday")
    return i18n.t("rel_days", n=ago // 86400)


# ---------------------------------------------------------------- CogBox.ini

class CogBoxIni:
    """Édition ligne à ligne de CogBox.ini, comme Ini de COGBox (util.cpp).

    Le launcher garde le fichier en mémoire et le réécrit en entier en sortant du jeu : rien
    d'autre que les valeurs touchées ne doit être reformaté ici.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.lines = []
        self.crlf = True
        self.error = ""
        self.load()

    def load(self):
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            self.lines, self.error = [], str(exc)
            return self
        self.error = ""
        return self.set_text(raw.decode("utf-8", "replace"))

    def set_text(self, text):
        """Charge depuis une chaîne (un CogBox.ini lu dans un zip, par exemple)."""
        if text.startswith("\ufeff"):
            text = text[1:]
        self.crlf = "\r\n" in text
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        self.lines = [l[:-1] if l.endswith("\r") else l for l in lines]
        while self.lines and not self.lines[-1].strip():
            self.lines.pop()
        return self

    @classmethod
    def from_text(cls, text):
        ini = cls.__new__(cls)
        ini.path = None
        ini.lines, ini.crlf, ini.error = [], True, ""
        return ini.set_text(text)

    @property
    def exists(self):
        return bool(self.path and self.path.is_file())

    def save(self):
        """Écrit un temporaire puis remplace (jamais de fichier à moitié écrit)."""
        if not self.lines or self.path is None:
            return False
        out = "".join(l + "\r\n" for l in self.lines)
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(out)
            os.replace(tmp, self.path)
        except OSError as exc:
            self.error = str(exc)
            return False
        return True

    @staticmethod
    def _trim(s):
        return s.strip(" \t\r\n")

    @classmethod
    def _section(cls, line):
        t = cls._trim(line)
        if len(t) < 2 or t[0] != "[" or t[-1] != "]":
            return None
        return cls._trim(t[1:-1])

    @classmethod
    def _kv(cls, line):
        t = cls._trim(line)
        if not t or t[0] in ";#":
            return None
        key, sep, value = t.partition("=")
        if not sep:
            return None
        key = cls._trim(key)
        return (key, cls._trim(value)) if key else None

    def get(self, section, key, default=""):
        current = ""
        for line in self.lines:
            name = self._section(line)
            if name is not None:
                current = name
                continue
            if current.lower() != section.lower():
                continue
            kv = self._kv(line)
            if kv and kv[0].lower() == key.lower():
                return kv[1]
        return default

    def geti64(self, section, key, default=0):
        value = self.get(section, key, "")
        try:
            return int(value.strip(), 10)
        except ValueError:
            return default

    def items(self, section):
        """{clé: valeur} d'une section, clés telles qu'écrites."""
        found, current = {}, ""
        for line in self.lines:
            name = self._section(line)
            if name is not None:
                current = name
                continue
            if current.lower() != section.lower():
                continue
            kv = self._kv(line)
            if kv:
                found[kv[0]] = kv[1]
        return found

    def set(self, section, key, value):
        """Même règle que Ini::set : remplace la ligne, sinon insère en fin de section."""
        line = "%s = %s" % (key, value)
        current = ""
        section_end = -1
        for i, raw in enumerate(self.lines):
            name = self._section(raw)
            if name is not None:
                current = name
                if current.lower() == section.lower():
                    section_end = i + 1
                continue
            if current.lower() != section.lower():
                continue
            kv = self._kv(raw)
            if kv and kv[0].lower() == key.lower():
                self.lines[i] = line
                return
            if self._trim(raw):
                section_end = i + 1
        if section_end < 0:
            if self.lines:
                self.lines.append("")
            self.lines.append("[%s]" % section)
            self.lines.append(line)
            return
        self.lines.insert(section_end, line)


# ---------------------------------------------------------------- catalogue

def unescape(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "\\":
                out.append("\\")
                i += 2
                continue
            if n == "n":
                out.append("\n")
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _u32(s, base=10):
    try:
        return int(s.strip(), base)
    except ValueError:
        return None


class Entry:
    __slots__ = ("id", "gamerscore", "flags", "image", "label", "description", "unachieved")

    def __init__(self):
        self.id = 0
        self.gamerscore = 0
        self.flags = 0
        self.image = 0
        self.label = ""
        self.description = ""
        self.unachieved = ""

    @property
    def secret(self):
        return (self.flags & SHOW_UNACHIEVED_FLAG) == 0


class Catalog:
    def __init__(self):
        self.title_id = ""
        self.game = ""
        self.language = 0
        self.entries = []


def parse_catalog(text):
    """Mêmes règles que xenos::ach::ParseCatalog ; None si l'en-tête manque."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith(CATALOG_HEADER):
        return None
    cat = Catalog()
    current = None
    have_title = False

    def finish():
        if current is not None and current.id:
            cat.entries.append(current)

    for line in lines[1:]:
        if not line or line.startswith("#"):
            continue
        if line == "[achievement]":
            finish()
            current = Entry()
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if current is None:
            if key == "title":
                v = _u32(value, 16)
                if v is not None:
                    cat.title_id = "%08X" % v
                    have_title = True
            elif key == "game":
                cat.game = unescape(value)
            elif key == "language":
                cat.language = _u32(value) or 0
            continue
        if key == "id":
            current.id = _u32(value) or 0
        elif key == "gamerscore":
            current.gamerscore = _u32(value) or 0
        elif key == "flags":
            current.flags = _u32(value) or 0
        elif key == "image":
            current.image = _u32(value) or 0
        elif key == "label":
            current.label = unescape(value)
        elif key == "description":
            current.description = unescape(value)
        elif key == "unachieved":
            current.unachieved = unescape(value)
    finish()
    return cat if have_title else None


def parse_unlocks(text):
    """[unlocked.<id>] / filetime = <n> ; ids entre guillemets acceptés, lignes inconnues ignorées."""
    unlocks = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[unlocked.") and line.endswith("]"):
            key = line[len("[unlocked."):-1].strip()
            if len(key) >= 2 and key[0] == '"' and key[-1] == '"':
                key = key[1:-1]
            current = _u32(key)
            if current:
                unlocks[current] = 0
            else:
                current = None
            continue
        if current is None:
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() == "filetime":
            ft = _u32(value)
            if ft:
                unlocks[current] = ft
    return unlocks


def save_unlocks(path, unlocks, header=TOML_HEADER):
    """Écrit le TOML (temporaire puis renommage, comme WriteFileAtomic de COGBox)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header, ""]
    for ach_id in sorted(unlocks):
        lines.append("[unlocked.%d]" % ach_id)
        lines.append("filetime = %d" % unlocks[ach_id])
        lines.append("")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.replace(tmp, path)


def existing_header(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line.strip():
                    return line if line.lstrip().startswith("#") else TOML_HEADER
    except OSError:
        pass
    return TOML_HEADER


# ---------------------------------------------------------------- jeux

class Game:
    def __init__(self, root, folder, title_id, name, cover_key, ini=None):
        self.root = root
        self.folder = folder
        self.key = folder.lower()  # clé de COGBox dans CogBox.ini ([gears1], [judgment]...)
        self.title_id = title_id
        self.name = name
        self.cover_key = cover_key
        self.ini = ini
        self.catalog = None
        self.unlocks = {}
        self.play_seconds = 0
        self.last_played = 0
        self.catalog_path = root / "achievements" / title_id / "catalog.txt"
        self.icon_dir = root / "achievements" / title_id / "icons"
        # 0.5.0 : un dossier de sauvegarde par profil (user, user-p2, user-p3...)
        self.user_dirs = backup.user_dirs_of(root / folder)
        self.user_dir = self._profile_dir()
        self.unlock_path = self.user_dir / "achievements" / (title_id + ".toml")

    def _profile_dir(self):
        """Dossier du profil courant de COGBox ([Profiles] Current), user s'il n'existe pas encore."""
        profile = max(1, self.ini.geti64("Profiles", "Current", 1)) if self.ini is not None else 1
        want = "user" if profile == 1 else "user-p%d" % profile
        for d in self.user_dirs:
            if d.name.lower() == want:
                return d
        return self.root / self.folder / want

    def load(self):
        try:
            self.catalog = parse_catalog(self.catalog_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            self.catalog = None
        try:
            self.unlocks = parse_unlocks(self.unlock_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            self.unlocks = {}
        if self.ini is not None:
            self.play_seconds = max(0, self.ini.geti64(INI_PLAY_SECTION, self.key, 0))
            self.last_played = max(0, self.ini.geti64(INI_LAST_SECTION, self.key, 0))
        return self

    @property
    def entries(self):
        return self.catalog.entries if self.catalog else []

    def has_catalog(self):
        return bool(self.catalog and self.catalog.entries)

    def totals(self):
        total = len(self.entries)
        gp_total = sum(e.gamerscore for e in self.entries)
        got = [e for e in self.entries if e.id in self.unlocks]
        return len(got), total, sum(e.gamerscore for e in got), gp_total

    def icon_path(self, entry):
        p = self.icon_dir / ("%d.png" % entry.id)
        return p if p.is_file() else None

    def is_unlocked(self, entry):
        return entry.id in self.unlocks

    def set_unlocked(self, entry, unlocked, when=None):
        if unlocked:
            self.unlocks[entry.id] = when if when else local_to_filetime(datetime.now())
        else:
            self.unlocks.pop(entry.id, None)

    def save(self):
        save_unlocks(self.unlock_path, self.unlocks, existing_header(self.unlock_path))

    # -- compteurs du launcher (CogBox.ini)
    def set_play_seconds(self, seconds):
        self.play_seconds = max(0, int(seconds))
        if self.ini is None:
            return False
        self.ini.set(INI_PLAY_SECTION, self.key, str(self.play_seconds))
        return self.ini.save()

    def set_last_played(self, unix_ts):
        self.last_played = max(0, int(unix_ts))
        if self.ini is None:
            return False
        self.ini.set(INI_LAST_SECTION, self.key, str(self.last_played))
        return self.ini.save()


def _has_content(folder):
    """Le dossier du jeu contient-il quelque chose (données de jeu ou un profil) ?"""
    if not folder.is_dir():
        return False
    for d in [folder / "game"] + backup.user_dirs_of(folder):
        if d.is_dir():
            try:
                if any(d.iterdir()):
                    return True
            except OSError:
                pass
    return False


def discover_games(root, ini=None):
    """Jeux COGBox qui existent et ont du contenu, plus ceux découverts par un .toml."""
    games, seen = [], set()
    for folder, title_id, name, cover in GAMES:
        d = root / folder
        catalog = root / "achievements" / title_id / "catalog.txt"
        if d.is_dir() and (_has_content(d) or catalog.is_file()):
            games.append(Game(root, folder, title_id, name, cover, ini))
            seen.add(folder.lower())
    # jeux non listés : un <dossier>/user/achievements/<TitleID>.toml suffit
    try:
        subdirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        subdirs = []
    for d in subdirs:
        if d.name.lower() in seen or d.name.startswith((".", "_")):
            continue
        for udir in backup.user_dirs_of(d):
            adir = udir / "achievements"
            if not adir.is_dir():
                continue
            tomls = sorted(adir.glob("*.toml"))
            if tomls:
                games.append(Game(root, d.name, tomls[0].stem.upper(), d.name, "", ini))
                break
    return games


def looks_like_cogbox(path):
    try:
        return (path / "achievements").is_dir() or (path / INI_NAME).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------- réglages (dossier COGBox retenu)

def _script_or_exe_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path():
    return _script_or_exe_dir() / "AppData" / "Roaming" / "JMD" / "AchievementsManager" / "settings.ini"


def save_remembered_root(root):
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ini = CogBoxIni(path)
        ini.set("App", "Root", str(root))
        ini.save()
    except OSError:
        pass


def remembered_root():
    path = config_path()
    if not path.is_file():
        return None
    ini = CogBoxIni(path)
    value = ini.get("App", "Root", "")
    return Path(value) if value else None


def find_root(explicit=None):
    """Retourne (root_dir, should_save).

    Ordre :
      1. Argument --root
      2. Dossier courant de l'exe / du script
      3. Fichier settings.ini
    should_save est True uniquement si l'étape 1 ou l'étape 2 a réussi.
    """
    # 1. Argument --root
    if explicit:
        p = Path(explicit)
        try:
            if looks_like_cogbox(p):
                return p.resolve(), True
        except OSError:
            pass

    # 2. Dossier de l'exe / du script
    here = _script_or_exe_dir()
    try:
        if looks_like_cogbox(here):
            return here.resolve(), True
    except OSError:
        pass

    # 3. Fichier settings.ini
    saved = remembered_root()
    if saved:
        try:
            if looks_like_cogbox(saved):
                return saved.resolve(), False
        except OSError:
            pass

    if explicit:
        return Path(explicit).resolve(), False
    return here.resolve(), False


def ini_language(ini):
    """Langue de COGBox.ini ([Launcher] Language) ; anglais si absente ou inconnue."""
    return i18n.normalize(ini.get("Launcher", "Language"))


def fold(s):
    """Minuscules sans accents, pour la recherche."""
    return "".join(c for c in unicodedata.normalize("NFD", s.casefold()) if not unicodedata.combining(c))


# ---------------------------------------------------------------- interface

def dpi_scale():
    """Conscience DPI (texte net) + facteur d'échelle, 1.0 hors Windows."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


# Segoe UI n'a pas les glyphes du chinois ni du coréen : on prend une police de Windows.
CJK_FONTS = {"zh": ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun"),
             "ko": ("Malgun Gothic", "Gulim")}


def make_ui():
    try:
        import tkinter as tk
        from tkinter import ttk  # noqa: F401  (présent pour PyInstaller)
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("tkinter is missing from this Python: %s" % exc)
    return tk


class App:
    def __init__(self, root_dir):
        self.tk = make_ui()
        tk = self.tk
        self.root_dir = root_dir
        self.ini = None
        self.games = []
        self.game = None
        self.images = []          # références gardées (PhotoImage)
        self.filter_mode = "all"
        self.query = ""
        self.screen = "games"
        self.tab = "achievements"

        self.scale = dpi_scale()
        self.win = tk.Tk()
        self.win.title(i18n.t("app_title"))
        self.win.configure(bg=BG)
        self.win.geometry("%dx%d" % (int(1120 * self.scale), int(780 * self.scale)))
        self.win.minsize(int(960 * self.scale), int(620 * self.scale))

        try:
            from PIL import Image, ImageTk
            self.Image, self.ImageTk = Image, ImageTk
        except ImportError:  # pragma: no cover
            self.Image = self.ImageTk = None

        self._fonts()
        self._build_shell()
        self.reload()

    # -- styles
    def _fonts(self):
        from tkinter import font as tkfont

        s = self.scale
        self.family = "Segoe UI"
        for name in CJK_FONTS.get(i18n.code(), ()):
            if name in tkfont.families(self.win):
                self.family = name
                break

        def pt(n):
            return max(8, int(round(n * s)))

        self.f_title = (self.family, pt(20), "bold")
        self.f_h1 = (self.family, pt(15), "bold")
        self.f_h2 = (self.family, pt(10), "bold")
        self.f_body = (self.family, pt(10))
        self.f_small = (self.family, pt(9))

    def _build_shell(self):
        tk = self.tk
        head = tk.Frame(self.win, bg=BG, padx=22, pady=16)
        head.pack(fill="x")
        self.head_success = tk.Label(head, text=i18n.t("head_success"), bg=BG, fg=TEXT, font=self.f_title)
        self.head_success.pack(side="left")
        self.head_brand = tk.Label(head, text="  COGBox", bg=BG, fg=MUTED, font=(self.family, 12))
        self.head_brand.pack(side="left")
        self.head_path = tk.Label(head, text=str(self.root_dir), bg=BG, fg=MUTED, font=self.f_small)
        self.head_path.pack(side="left", padx=(16, 0))
        self.btn_reload = tk.Button(head, text=i18n.t("head_reload"), command=self.reload, bg=PANEL, fg=TEXT,
                                    font=self.f_body, relief="flat", padx=12, pady=4, cursor="hand2",
                                    activebackground=CARD_SEL, activeforeground=TEXT, bd=0)
        self.btn_reload.pack(side="right")
        self.btn_folder = tk.Button(head, text=i18n.t("head_folder"), command=self._choose_root, bg=PANEL, fg=TEXT,
                                    font=self.f_body, relief="flat", padx=12, pady=4, cursor="hand2",
                                    activebackground=CARD_SEL, activeforeground=TEXT, bd=0)
        self.btn_folder.pack(side="right", padx=(0, 8))

        self.tools = tk.Frame(self.win, bg=BG, padx=22)
        self.tools.pack(fill="x", pady=(0, 10))
        self.btn_backup = self._tool_button("head_backup", self._backup_dialog)
        self.btn_restore = self._tool_button("head_restore", lambda: self._backups_dialog(True))
        self.btn_backups = self._tool_button("head_backups", lambda: self._backups_dialog(False))

        self.body = tk.Frame(self.win, bg=BG, padx=22, pady=0)
        self.body.pack(fill="both", expand=True)

        foot = tk.Frame(self.win, bg=BG, padx=22, pady=10)
        foot.pack(fill="x", side="bottom")
        self.status = tk.Label(foot, text="", bg=BG, fg=MUTED, font=self.f_small, anchor="w")
        self.status.pack(side="left")
        self.warn = tk.Label(foot, text=i18n.t("foot_warning"), bg=BG, fg=MUTED, font=self.f_small)
        self.warn.pack(side="right")

    def _tool_button(self, key, command):
        tk = self.tk
        button = tk.Button(self.tools, text=i18n.t(key), command=command, bg=PANEL, fg=TEXT,
                           font=self.f_body, relief="flat", padx=12, pady=4, cursor="hand2",
                           activebackground=CARD_SEL, activeforeground=TEXT, bd=0)
        button.pack(side="left", padx=(0, 8))
        return button

    def _dialog_button(self, parent, key, command, bg=PANEL, fg=TEXT):
        tk = self.tk
        return tk.Button(parent, text=i18n.t(key), command=command, bg=bg, fg=fg, font=self.f_body,
                         relief="flat", padx=12, pady=5, cursor="hand2",
                         activebackground=ACCENT if bg != PANEL else CARD_SEL,
                         activeforeground=fg, bd=0)

    def _confirm(self, text):
        from tkinter import messagebox

        return messagebox.askyesno(i18n.t("confirm_title"), text, parent=self.win)

    def _info(self, title, text):
        from tkinter import messagebox

        messagebox.showinfo(title, text, parent=self.win)

    def _retranslate(self):
        """Relibelle l'en-tête et le pied après un changement de langue (dossier COGBox)."""
        self.win.title(i18n.t("app_title"))
        self.head_success.config(text=i18n.t("head_success"), font=self.f_title)
        self.head_brand.config(font=(self.family, 12))
        self.head_path.config(font=self.f_small)
        self.btn_reload.config(text=i18n.t("head_reload"), font=self.f_body)
        self.btn_folder.config(text=i18n.t("head_folder"), font=self.f_body)
        for button, key in ((self.btn_backup, "head_backup"), (self.btn_restore, "head_restore"),
                            (self.btn_backups, "head_backups")):
            button.config(text=i18n.t(key), font=self.f_body)
        self.warn.config(text=i18n.t("foot_warning"), font=self.f_small)
        self.status.config(font=self.f_small)

    # -- dossier COGBox
    def _choose_root(self):
        tk = self.tk
        from tkinter import filedialog

        chosen = filedialog.askdirectory(initialdir=str(self.root_dir), title=i18n.t("folder_dialog"))
        if not chosen:
            return
        path = Path(chosen)
        if not looks_like_cogbox(path):
            self.status.config(text=i18n.t("folder_invalid", path=path))
            return
        self.root_dir = path.resolve()
        save_remembered_root(self.root_dir)
        self.head_path.config(text=str(self.root_dir))
        self.reload()

    # -- sauvegardes
    def _backup_dialog(self, only=None, tag=""):
        """Zip des fichiers de COGBox (``only`` : un profil), nom proposé dans le dossier backups."""
        tk = self.tk
        folder = backup.backups_dir(self.root_dir)
        dlg = tk.Toplevel(self.win)
        dlg.title(i18n.t("dlg_backup"))
        dlg.configure(bg=BG, padx=22, pady=18)
        dlg.transient(self.win)
        dlg.resizable(False, False)
        wrap = int(430 * self.scale)

        tk.Label(dlg, text=i18n.t("backup_intro"), bg=BG, fg=TEXT, font=self.f_h2,
                 wraplength=wrap, justify="left").pack(anchor="w")
        tk.Label(dlg, text=i18n.t("backup_where", path=folder), bg=BG, fg=MUTED, font=self.f_small,
                 wraplength=wrap, justify="left").pack(anchor="w", pady=(2, 12))

        tk.Label(dlg, text=i18n.t("field_name"), bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w")
        name_var = tk.StringVar(value=backup.default_name(tag))
        entry = tk.Entry(dlg, textvariable=name_var, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=self.f_body, width=46, bd=0)
        entry.pack(fill="x", ipady=6, pady=(3, 0))
        entry.focus_set()
        entry.select_range(0, "end")

        error = tk.Label(dlg, text="", bg=BG, fg="#f85149", font=self.f_small,
                         wraplength=wrap, justify="left")
        error.pack(anchor="w", pady=(8, 0))

        def on_backup():
            name = name_var.get().strip()
            if not backup.check_name(name):
                error.config(text=i18n.t("err_name"))
                return
            path = folder / name
            if path.exists() and not self._confirm(i18n.t("confirm_overwrite", path=path)):
                return
            try:
                files, size = backup.create(self.root_dir, path, only)
            except Exception as exc:  # disque plein, fichier verrouillé par COGBox...
                error.config(text=i18n.t("err_backup", err=exc))
                return
            dlg.destroy()
            text = i18n.t("backup_done", path=path, files=files, size=backup.fmt_size(size))
            self.status.config(text=text)
            self._info(i18n.t("dlg_backup"), text)

        buttons = tk.Frame(dlg, bg=BG)
        buttons.pack(pady=(12, 0))
        self._dialog_button(buttons, "btn_backup", on_backup, ACCENT_DARK, "#ffffff").pack(side="left", padx=(0, 8))
        self._dialog_button(buttons, "btn_cancel", dlg.destroy).pack(side="left")

        dlg.bind("<Return>", lambda _e: on_backup())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        self._center(dlg)

    def _backups_dialog(self, restore, only=None):
        """Liste des sauvegardes + aperçu ; en mode restauration, remise en place du zip."""
        tk = self.tk
        folder = backup.backups_dir(self.root_dir)
        items = backup.list_backups(self.root_dir, only)
        dlg = tk.Toplevel(self.win)
        dlg.title(i18n.t("dlg_restore" if restore else "dlg_backups"))
        dlg.configure(bg=BG, padx=22, pady=18)
        dlg.transient(self.win)
        dlg.geometry("%dx%d" % (int(820 * self.scale), int(440 * self.scale)))
        dlg.minsize(int(700 * self.scale), int(360 * self.scale))

        intro = (i18n.t("restore_intro", root=self.root_dir) if restore
                 else i18n.t("backups_intro", path=folder))
        tk.Label(dlg, text=intro, bg=BG, fg=TEXT, font=self.f_body,
                 wraplength=int(760 * self.scale), justify="left").pack(anchor="w", pady=(0, 10))

        body = tk.Frame(dlg, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both")
        listbox = tk.Listbox(left, width=36, bg=PANEL, fg=TEXT, selectbackground=CARD_SEL,
                             selectforeground=TEXT, font=self.f_small, relief="flat", bd=0,
                             highlightthickness=0, activestyle="none", exportselection=False)
        scroll = tk.Scrollbar(left, orient="vertical", command=listbox.yview)
        listbox.config(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for item in items:
            listbox.insert("end", "%s  ·  %s" % (item.name, backup.fmt_size(item.size)))

        preview = tk.Frame(body, bg=BG, padx=18)
        preview.pack(side="left", fill="both", expand=True)

        def show(_event=None):
            for child in preview.winfo_children():
                child.destroy()
            wrap = int(380 * self.scale)
            sel = listbox.curselection()
            if not items or not sel:
                tk.Label(preview, text=i18n.t("backups_empty", path=folder), bg=BG, fg=MUTED,
                         font=self.f_body, wraplength=wrap, justify="left").pack(anchor="w")
                return
            item = items[sel[0]].load()
            tk.Label(preview, text=item.name, bg=BG, fg=TEXT, font=self.f_h2, wraplength=wrap,
                     justify="left").pack(anchor="w")
            tk.Label(preview, text="%s   ·   %s" % (item.mtime.strftime("%d/%m/%Y %H:%M"),
                     i18n.t("preview_files", n=item.files, size=backup.fmt_size(item.size))),
                     bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 8))
            if item.error:
                tk.Label(preview, text=i18n.t("err_read_backup", err=item.error), bg=BG, fg="#f85149",
                         font=self.f_small, wraplength=wrap, justify="left").pack(anchor="w")
                return
            names = ", ".join(item.profiles)
            tk.Label(preview, text=i18n.t("preview_profile", names=names) if names
                     else i18n.t("preview_noprofiles"), bg=BG, fg=TEXT, font=self.f_small,
                     wraplength=wrap, justify="left").pack(anchor="w", pady=(0, 8))
            for game in self.games:
                tk.Label(preview, text=i18n.t(
                    "preview_game", name=game.name, a=item.unlock_count(game.folder, game.title_id),
                    b=len(game.entries), time=fmt_duration(item.play.get(game.key, 0)),
                    last=fmt_unix_local(item.last.get(game.key, 0)) or i18n.t("never_launched")),
                    bg=BG, fg=TEXT, font=self.f_small, wraplength=wrap,
                    justify="left").pack(anchor="w", pady=(0, 2))

        listbox.bind("<<ListboxSelect>>", show)
        if items:
            listbox.selection_set(0)
        show()

        bottom = tk.Frame(dlg, bg=BG)
        bottom.pack(fill="x", pady=(12, 0))

        if restore:
            keep = tk.BooleanVar(value=True)
            tk.Checkbutton(bottom, text=i18n.t("check_current"), variable=keep, bg=BG, fg=TEXT,
                           selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
                           font=self.f_small, bd=0, highlightthickness=0,
                           cursor="hand2").pack(side="left")

            def on_restore():
                sel = listbox.curselection()
                if not items or not sel:
                    self.status.config(text=i18n.t("err_no_backup"))
                    return
                item = items[sel[0]]
                asked = i18n.t("confirm_restore", root=self.root_dir, name=item.name)
                if not self._confirm(asked):
                    return
                try:
                    if keep.get():
                        backup.create(self.root_dir, folder / backup.default_name(), only)
                    files = backup.restore(self.root_dir, item.path, only)
                except Exception as exc:  # zip abîmé, fichier verrouillé...
                    self._info(i18n.t("dlg_restore"), i18n.t("err_restore", err=exc))
                    return
                if not files:
                    self._info(i18n.t("dlg_restore"), i18n.t("err_no_profile_files"))
                    return
                dlg.destroy()
                text = i18n.t("restore_done", files=files, name=item.name)
                self.status.config(text=text)
                self._info(i18n.t("dlg_restore"), text)
                self.reload()

            self._dialog_button(bottom, "btn_restore", on_restore, ACCENT_DARK,
                                "#ffffff").pack(side="right", padx=(8, 0))
        self._dialog_button(bottom, "btn_close", dlg.destroy).pack(side="right")

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        self._center(dlg)

    # -- données
    def reload(self):
        self.ini = CogBoxIni(self.root_dir / INI_NAME)
        self._apply_language(ini_language(self.ini))
        self.games = [g.load() for g in discover_games(self.root_dir, self.ini)]
        self.images = []
        if self.screen == "game" and self.game is not None:
            found = next((g for g in self.games if g.folder == self.game.folder), None)
            if found:
                self.game = found
                self.show_game(found, self.tab)
                return
        self.show_games()

    def _apply_language(self, value):
        """Suit la langue de CogBox.ini quand le dossier change ; refait l'en-tête et le pied."""
        if value == i18n.code():
            return
        i18n.set_language(value)
        self._fonts()
        self._retranslate()

    def _clear_body(self):
        for child in self.body.winfo_children():
            child.destroy()

    # -- écran 1 : les jeux
    def show_games(self):
        tk = self.tk
        self.screen = "games"
        self.tab = "achievements"
        self.game = None
        self._clear_body()

        if not self.games:
            tk.Label(self.body, text=i18n.t("empty_title", root=self.root_dir), bg=BG, fg=MUTED,
                     font=self.f_h2, justify="center").pack(pady=80)
            self.status.config(text=i18n.t("empty_status"))
            return

        got, total, gp, gp_total, played = 0, 0, 0, 0, 0
        for g in self.games:
            a, b, c, d = g.totals()
            got, total, gp, gp_total = got + a, total + b, gp + c, gp_total + d
            played += g.play_seconds
        tk.Label(self.body, text=i18n.t("summary", got=got, total=total, gp=gp, gpt=gp_total,
                                  time=fmt_duration(played)),
                 bg=BG, fg=MUTED, font=self.f_body).pack(anchor="w", pady=(0, 14))

        grid = tk.Frame(self.body, bg=BG)
        grid.pack(fill="both", expand=True, anchor="n")
        for i, g in enumerate(self.games):
            card = self._game_card(grid, g)
            card.grid(row=i // 2, column=i % 2, padx=(0, 14), pady=(0, 14), sticky="nsew")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        note = i18n.t("games_note", n=len(self.games), root=self.root_dir)
        if not self.ini.exists:
            note += i18n.t("games_note_noini")
        self.status.config(text=note)

    def _game_card(self, parent, game):
        tk = self.tk
        a, b, gp, gp_total = game.totals()
        cover = self._cover(game.cover_key, 104, 138)

        card = tk.Frame(parent, bg=CARD, padx=14, pady=14, highlightbackground=BORDER,
                        highlightthickness=1, cursor="hand2")
        thumb = tk.Label(card, bg=CARD, image=cover) if cover else tk.Label(card, bg=PANEL, width=14, height=8)
        if cover:
            thumb.image = cover
        thumb.pack(side="left")

        right = tk.Frame(card, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        tk.Label(right, text=game.name, bg=CARD, fg=TEXT, font=self.f_h1, anchor="w").pack(anchor="w")
        tk.Label(right, text=game.title_id, bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 10))
        tk.Label(right, text=i18n.t("card_unlocks", a=a, b=b) if b else i18n.t("card_nocatalog"),
                 bg=CARD, fg=TEXT, font=self.f_h2).pack(anchor="w")
        tk.Label(right, text=i18n.t("card_gs", gp=gp, gpt=gp_total), bg=CARD, fg=GOLD,
                 font=self.f_body).pack(anchor="w")
        self._progress(right, a, b, width=250)
        tk.Label(right, text="%s  ·  %s" % (fmt_duration(game.play_seconds), fmt_last_played(game.last_played)),
                 bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(8, 0))
        tk.Label(right, text=i18n.t("card_open"), bg=CARD, fg=ACCENT, font=self.f_h2).pack(anchor="w", pady=(8, 0))

        widgets = [card, thumb, right] + list(right.winfo_children())
        for w in widgets:
            w.bind("<Button-1>", lambda _e, g=game: self.show_game(g))
        card.bind("<Enter>", lambda _e: card.config(bg=CARD_SEL))
        card.bind("<Leave>", lambda _e: card.config(bg=CARD))
        return card

    def _progress(self, parent, a, b, width=250, height=6):
        tk = self.tk
        cv = tk.Canvas(parent, width=width, height=height, bg=BORDER, highlightthickness=0, bd=0)
        cv.pack(anchor="w", pady=(6, 0))
        if b:
            cv.create_rectangle(0, 0, int(width * a / b), height, fill=ACCENT, width=0)
        return cv

    def _cover(self, key, w, h):
        if not key or not self.Image:
            return None
        path = self.root_dir / "covers" / ("%s-boxart.jpg" % key)
        if not path.is_file():
            return None
        try:
            img = self.Image.open(path).convert("RGB")
            img.thumbnail((w * 2, h * 2))
            img = img.resize((w, h), self.Image.LANCZOS)
            photo = self.ImageTk.PhotoImage(img)
            self.images.append(photo)
            return photo
        except Exception:
            return None

    def _icon(self, game, entry, size=44):
        tk = self.tk
        path = game.icon_path(entry)
        if path and self.Image:
            try:
                img = self.Image.open(path).convert("RGBA").resize((size, size), self.Image.LANCZOS)
                photo = self.ImageTk.PhotoImage(img)
                self.images.append(photo)
                return photo
            except Exception:
                pass
        # pastille grise si le PNG manque
        canvas_img = tk.PhotoImage(width=size, height=size)
        canvas_img.put(BORDER, to=(0, 0, size, size))
        self.images.append(canvas_img)
        return canvas_img

    # -- écran 2 : un jeu
    def show_game(self, game, tab=None):
        tk = self.tk
        self.screen = "game"
        self.game = game
        if tab is not None:
            self.tab = tab
        self._clear_body()

        top = tk.Frame(self.body, bg=BG)
        top.pack(fill="x", pady=(0, 12))
        tk.Button(top, text=i18n.t("back"), command=self.show_games, bg=PANEL, fg=TEXT, font=self.f_body,
                  relief="flat", padx=12, pady=4, cursor="hand2", activebackground=CARD_SEL,
                  activeforeground=TEXT, bd=0).pack(side="left")

        a, b, gp, gp_total = game.totals()
        info = tk.Frame(top, bg=BG)
        info.pack(side="left", padx=(16, 0))
        tk.Label(info, text=game.name, bg=BG, fg=TEXT, font=self.f_h1).pack(anchor="w")
        self.game_sub = tk.Label(info, text=i18n.t("game_sub", a=a, b=b, gp=gp, gpt=gp_total,
                                                   title_id=game.title_id),
                                 bg=BG, fg=MUTED, font=self.f_small)
        self.game_sub.pack(anchor="w")

        self._stats_strip(game)

        # onglets : succès, puis données de jeu de chaque profil
        tabs = tk.Frame(self.body, bg=BG)
        tabs.pack(fill="x")
        self.tab_buttons = {}
        for key in ("achievements", "saves"):
            button = tk.Button(tabs, text=i18n.t("tab_" + key),
                               command=lambda k=key: self.show_game(self.game, k), bg=PANEL, fg=MUTED,
                               font=self.f_body, relief="flat", padx=14, pady=4, cursor="hand2",
                               activebackground=CARD_SEL, activeforeground=TEXT, bd=0)
            button.pack(side="left", padx=(0, 6))
            self.tab_buttons[key] = button
        self.tab_buttons[self.tab].config(bg=CARD_SEL, fg=TEXT)

        self.tab_body = tk.Frame(self.body, bg=BG)
        self.tab_body.pack(fill="both", expand=True, pady=(8, 0))
        if self.tab == "saves":
            self._saves_tab(game)
        else:
            self._achievements_tab(game)

    def _achievements_tab(self, game):
        tk = self.tk
        self.query = ""

        # barre d'outils
        bar = tk.Frame(self.tab_body, bg=BG)
        bar.pack(fill="x", pady=(4, 10))
        self.search_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.search_var, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=self.f_body, width=34, bd=0)
        entry.pack(side="left", ipady=6, ipadx=8)
        entry.bind("<KeyRelease>", lambda _e: self._set_query())
        tk.Label(bar, text="⌕", bg=BG, fg=MUTED, font=(self.family, 12)).pack(side="left", padx=(0, 16))

        self.filter_buttons = {}
        for mode, label in (("all", i18n.t("filter_all")), ("got", i18n.t("filter_got")),
                            ("todo", i18n.t("filter_todo"))):
            b = tk.Button(bar, text=label, command=lambda m=mode: self._set_filter(m), bg=PANEL, fg=MUTED,
                          font=self.f_body, relief="flat", padx=12, pady=4, cursor="hand2",
                          activebackground=CARD_SEL, activeforeground=TEXT, bd=0)
            b.pack(side="left", padx=(0, 6))
            self.filter_buttons[mode] = b

        self.count_label = tk.Label(bar, text="", bg=BG, fg=MUTED, font=self.f_body)
        self.count_label.pack(side="right")

        self._scroll_area(self.tab_body)
        self.refresh_rows()
        self._update_filter_buttons()

    def _scroll_area(self, parent):
        """Zone défilante des deux onglets : self.canvas (vue) et self.inner (contenu)."""
        tk = self.tk
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        scroll = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        return self.inner

    # -- onglet « données de jeu » : un dossier de sauvegarde par profil
    def _saves_tab(self, game):
        self._scroll_area(self.tab_body)
        self.refresh_saves()

    @staticmethod
    def _profile_number(user_dir):
        name = Path(user_dir).name.lower()
        return 1 if name == "user" else int(name[6:])

    def refresh_saves(self):
        game = self.game
        if game is None or self.tab != "saves":
            return
        for child in self.inner.winfo_children():
            child.destroy()
        current = game.user_dir
        dirs = list(game.user_dirs)
        if current not in dirs:
            dirs.append(current)
        for user_dir in sorted(dirs, key=self._profile_number):
            self._profile_row(self.inner, game, user_dir, user_dir == current)
        self.status.config(text=i18n.t("status_saves", path=self.root_dir / game.folder))
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _profile_row(self, parent, game, user_dir, is_current):
        tk = self.tk
        number = self._profile_number(user_dir)
        only = "%s/%s" % (game.folder, user_dir.name)
        files, size, when = backup.folder_summary(self.root_dir, only)
        name = backup.profile_name(self.root_dir, number)
        try:
            unlocks = len(parse_unlocks((user_dir / "achievements" / (game.title_id + ".toml"))
                                        .read_text(encoding="utf-8", errors="replace")))
        except OSError:
            unlocks = 0

        card = tk.Frame(parent, bg=CARD, padx=14, pady=12)
        card.pack(fill="x", pady=(0, 6))
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x")
        title = i18n.t("profile_title", n=number) + ("  ·  " + name if name else "")
        tk.Label(head, text=title, bg=CARD, fg=TEXT, font=self.f_h2).pack(side="left")
        if is_current:
            tk.Label(head, text=i18n.t("profile_current"), bg=CARD, fg=ACCENT,
                     font=self.f_small).pack(side="left", padx=(10, 0))
        tk.Label(card, text=str(user_dir), bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 0))
        stats = i18n.t("profile_stats", files=files, size=backup.fmt_size(size),
                       when=when.strftime("%d/%m/%Y %H:%M") if when else i18n.t("never_launched"))
        stats += "   ·   " + i18n.t("profile_ach", a=unlocks)
        tk.Label(card, text=stats, bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(3, 8))

        buttons = tk.Frame(card, bg=CARD)
        buttons.pack(anchor="w")
        tag = backup.profile_tag(game.folder, user_dir)
        self._dialog_button(buttons, "btn_backup", lambda: self._backup_dialog(only, tag)).pack(side="left", padx=(0, 6))
        self._dialog_button(buttons, "btn_restore",
                            lambda: self._backups_dialog(True, only)).pack(side="left", padx=(0, 6))
        self._dialog_button(buttons, "btn_reset_profile",
                            lambda: self._reset_profile(game, user_dir, only, number, name)).pack(side="left")

    def _reset_profile(self, game, user_dir, only, number, name):
        """Vide un profil après une sauvegarde automatique de ses fichiers."""
        asked = i18n.t("confirm_reset_profile", n=number, name=name or str(user_dir), game=game.name)
        if not self._confirm(asked):
            return
        tag = backup.profile_tag(game.folder, user_dir)
        try:
            zip_path = backup.backups_dir(self.root_dir) / backup.default_name(tag + "-before-reset")
            backup.create(self.root_dir, zip_path, only)
            files = backup.reset(self.root_dir, only)
        except Exception as exc:  # fichier verrouillé par COGBox...
            self._info(i18n.t("dlg_reset"), i18n.t("err_reset", err=exc))
            return
        text = i18n.t("reset_done", files=files, n=number, game=game.name, name=zip_path.name)
        self.status.config(text=text)
        self._info(i18n.t("dlg_reset"), text)
        self.reload()

    def _stats_strip(self, game):
        """Temps de jeu et dernier lancement de COGBox (CogBox.ini), éditables."""
        tk = self.tk
        strip = tk.Frame(self.body, bg=CARD, padx=11, pady=11, highlightbackground=BORDER, highlightthickness=1)
        strip.pack(fill="x", pady=(0, 12))
        # deux colonnes de largeur identique : le bandeau ne bouge pas d'un jeu à l'autre
        strip.columnconfigure(0, weight=1, uniform="stats")
        strip.columnconfigure(1, weight=1, uniform="stats")

        for col, (title, attr, cmd) in enumerate(((i18n.t("stats_playtime"), "play_value", self._edit_playtime),
                                                  (i18n.t("stats_last"), "last_value", self._edit_last_played))):
            box = tk.Frame(strip, bg=CARD)
            box.grid(row=0, column=col, sticky="w")
            tk.Label(box, text=title.upper(), bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w")
            row = tk.Frame(box, bg=CARD)
            row.pack(anchor="w", pady=(3, 0))
            value = tk.Label(row, text="", bg=CARD, fg=TEXT, font=self.f_h2)
            value.pack(side="left")
            setattr(self, attr, value)
            if attr == "last_value":
                # « lancé aujourd'hui » en petit et grisé : c'est un rappel, pas la valeur
                self.last_hint = tk.Label(row, text="", bg=CARD, fg=MUTED, font=self.f_small)
                self.last_hint.pack(side="left", padx=(8, 0))
            tk.Button(row, text=i18n.t("edit"), command=cmd, bg=PANEL, fg=TEXT, font=self.f_small, width=8,
                      relief="flat", padx=6, pady=3, cursor="hand2", activebackground=CARD_SEL,
                      activeforeground=TEXT, bd=0).pack(side="left", padx=(14, 0))

        if self.ini is not None and not self.ini.exists:
            note = i18n.t("stats_noini")
        else:
            note = game.key
        self.stat_note = tk.Label(strip, text=note, bg=CARD, fg=MUTED, font=self.f_small)
        self.stat_note.grid(row=0, column=2, sticky="ne", padx=(14, 1))
        self.refresh_stats()

    def refresh_stats(self):
        game = self.game
        if game is None:
            return
        self.play_value.config(text=fmt_duration(game.play_seconds))
        when = fmt_unix_local(game.last_played)
        self.last_value.config(text=when or i18n.t("never_launched"))
        self.last_hint.config(text="·  %s" % fmt_last_played(game.last_played) if when else "")

    def _on_wheel(self, event):
        if isinstance(event.widget, (self.tk.Entry, self.tk.Text)):
            return
        try:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    def _set_query(self):
        self.query = self.search_var.get()
        self.refresh_rows()

    def _set_filter(self, mode):
        self.filter_mode = mode
        self.refresh_rows()
        self._update_filter_buttons()

    def _update_filter_buttons(self):
        for mode, b in self.filter_buttons.items():
            if mode == self.filter_mode:
                b.config(bg=CARD_SEL, fg=TEXT)
            else:
                b.config(bg=PANEL, fg=MUTED)

    def refresh_tab(self):
        """Redessine l'onglet visible après une modification."""
        if self.tab == "saves":
            self.refresh_saves()
        else:
            self.refresh_rows()

    def refresh_rows(self):
        game = self.game
        if game is None or self.tab != "achievements":
            return
        tk = self.tk
        keep = self.canvas.yview()[0]
        for child in self.inner.winfo_children():
            child.destroy()

        if not game.has_catalog():
            tk.Label(self.inner, text=i18n.t("catalog_missing"),
                     bg=BG, fg=MUTED, font=self.f_body, pady=40).pack()

        needle = fold(self.query.strip())
        shown = 0
        for entry in game.entries:
            unlocked = game.is_unlocked(entry)
            if self.filter_mode == "got" and not unlocked:
                continue
            if self.filter_mode == "todo" and unlocked:
                continue
            if needle and needle not in fold(entry.label + " " + entry.description):
                continue
            self._row(self.inner, game, entry, unlocked)
            shown += 1

        a, b, gp, gp_total = game.totals()
        self.game_sub.config(text=i18n.t("game_sub", a=a, b=b, gp=gp, gpt=gp_total, title_id=game.title_id))
        self.count_label.config(text=i18n.t("shown", n=shown))
        self.status.config(text=i18n.t("status_unlocks", path=game.unlock_path))
        self.refresh_stats()
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(keep)

    def _row(self, parent, game, entry, unlocked):
        tk = self.tk
        row = tk.Frame(parent, bg=CARD, padx=12, pady=10)
        row.pack(fill="x", pady=(0, 2))

        icon = tk.Label(row, bg=CARD, image=self._icon(game, entry))
        icon.image = self.images[-1]
        icon.pack(side="left")

        text = tk.Frame(row, bg=CARD)
        text.pack(side="left", fill="x", expand=True, padx=(12, 12))
        title = tk.Frame(text, bg=CARD)
        title.pack(anchor="w", fill="x")
        tk.Label(title, text=entry.label or i18n.t("row_noname"), bg=CARD,
                 fg=TEXT if unlocked else "#c9cede", font=self.f_h2, anchor="w").pack(side="left")
        if entry.secret:
            tk.Label(title, text=i18n.t("row_secret"), bg="#2d2438", fg="#c39bf5",
                     font=self.f_small).pack(side="left", padx=(8, 0))
        desc = entry.description or entry.unachieved or ""
        if desc:
            tk.Label(text, text=desc, bg=CARD, fg=MUTED, font=self.f_small, anchor="w",
                     justify="left", wraplength=520).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(row, bg=CARD)
        right.pack(side="right")
        tk.Label(right, text="%d G" % entry.gamerscore, bg=CARD, fg=GOLD, font=self.f_h2).pack(anchor="e")
        tk.Label(right, text=fmt_time(game.unlocks.get(entry.id)) if unlocked else i18n.t("not_unlocked"),
                 bg=CARD, fg=ACCENT if unlocked else MUTED, font=self.f_small).pack(anchor="e", pady=(2, 6))

        buttons = tk.Frame(right, bg=CARD)
        buttons.pack(anchor="e")
        if unlocked:
            tk.Button(buttons, text=i18n.t("row_unlocked"), command=lambda: self._toggle(entry, False), bg="#1d3327",
                      fg=ACCENT, font=self.f_small, relief="flat", padx=10, pady=3, cursor="hand2",
                      activebackground="#264535", activeforeground=ACCENT, bd=0).pack(side="left")
            tk.Button(buttons, text=i18n.t("row_date"), command=lambda: self._edit_date(entry), bg=PANEL, fg=TEXT,
                      font=self.f_small, relief="flat", padx=10, pady=3, cursor="hand2",
                      activebackground=CARD_SEL, activeforeground=TEXT, bd=0).pack(side="left", padx=(6, 0))
        else:
            tk.Button(buttons, text=i18n.t("row_unlock"), command=lambda: self._toggle(entry, True), bg=PANEL, fg=TEXT,
                      font=self.f_small, relief="flat", padx=10, pady=3, cursor="hand2",
                      activebackground=ACCENT_DARK, activeforeground="#ffffff", bd=0).pack(side="left")

    # -- actions
    def _toggle(self, entry, unlocked):
        name = entry.label or i18n.t("row_noname")
        asked = i18n.t("confirm_unlock", name=name) if unlocked else i18n.t("confirm_lock", name=name)
        if not self._confirm(asked):
            return
        self.game.set_unlocked(entry, unlocked)
        self.game.save()
        self.refresh_tab()

    def _edit_date(self, entry):
        current = filetime_to_local(self.game.unlocks.get(entry.id, 0)) or datetime.now()

        def apply(when):
            asked = i18n.t("confirm_date", name=entry.label or i18n.t("row_noname"),
                           when=when.strftime("%d/%m/%Y %H:%M:%S"))
            if not self._confirm(asked):
                return False
            self.game.set_unlocked(entry, True, local_to_filetime(when))
            self.game.save()
            self.refresh_tab()
            return True

        self._moment_dialog(i18n.t("dlg_unlock_date"), entry.label, i18n.t("dlg_local_time"),
                            current, apply, None)

    def _edit_playtime(self):
        game = self.game
        tk = self.tk
        total = int(game.play_seconds or 0)

        dlg = tk.Toplevel(self.win)
        dlg.title(i18n.t("dlg_playtime"))
        dlg.configure(bg=BG, padx=22, pady=18)
        dlg.transient(self.win)
        dlg.resizable(False, False)

        tk.Label(dlg, text=game.name, bg=BG, fg=TEXT, font=self.f_h2).pack(anchor="w")
        tk.Label(dlg, text=i18n.t("dlg_source", section=INI_PLAY_SECTION, name=game.key),
                 bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 12))

        form = tk.Frame(dlg, bg=BG)
        form.pack()
        vars_ = []
        for col, (label, value) in enumerate(((i18n.t("hours"), total // 3600),
                                              (i18n.t("minutes"), (total % 3600) // 60),
                                              (i18n.t("seconds"), total % 60))):
            # libellé centré au-dessus de son champ, marges symétriques
            cell = tk.Frame(form, bg=BG)
            cell.grid(row=0, column=col, padx=7)
            tk.Label(cell, text=label, bg=BG, fg=MUTED, font=self.f_small).pack(anchor="center")
            var = tk.StringVar(value=str(value))
            e = tk.Entry(cell, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                         font=(self.family, 11), width=7, bd=0, justify="center")
            e.pack(fill="x", ipady=6, pady=(3, 0))
            if col == 0:
                e.focus_set()
            vars_.append(var)

        error = tk.Label(dlg, text="", bg=BG, fg="#f85149", font=self.f_small)
        error.pack(pady=(10, 0))
        buttons = tk.Frame(dlg, bg=BG)
        buttons.pack(pady=(12, 0))

        def apply_seconds(seconds):
            asked = (i18n.t("confirm_reset_playtime", name=game.name) if seconds == 0
                     else i18n.t("confirm_playtime", time=fmt_duration(seconds), name=game.name))
            if not self._confirm(asked):
                return
            if not game.set_play_seconds(seconds):
                error.config(text=i18n.t("err_write", err=self.ini.error or ""))
                return
            dlg.destroy()
            self.refresh_tab()

        def on_apply():
            try:
                h, m, s = (int(v.get().strip() or "0") for v in vars_)
            except ValueError:
                error.config(text=i18n.t("err_integers"))
                return
            if h < 0 or m < 0 or s < 0:
                error.config(text=i18n.t("err_positive"))
                return
            apply_seconds(h * 3600 + m * 60 + s)

        tk.Button(buttons, text=i18n.t("btn_reset"), command=lambda: apply_seconds(0), bg=PANEL, fg=TEXT,
                  font=self.f_body, relief="flat", padx=12, pady=5, cursor="hand2",
                  activebackground=CARD_SEL, activeforeground=TEXT, bd=0).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text=i18n.t("btn_apply"), command=on_apply, bg=ACCENT_DARK, fg="#ffffff", font=self.f_body,
                  relief="flat", padx=14, pady=5, cursor="hand2", activebackground=ACCENT,
                  activeforeground="#ffffff", bd=0).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text=i18n.t("btn_cancel"), command=dlg.destroy, bg=PANEL, fg=MUTED, font=self.f_body,
                  relief="flat", padx=12, pady=5, cursor="hand2", activebackground=CARD_SEL,
                  activeforeground=TEXT, bd=0).pack(side="left")

        dlg.bind("<Return>", lambda _e: on_apply())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        self._center(dlg)

    def _edit_last_played(self):
        current = fmt_unix_local(self.game.last_played)
        when = datetime.fromtimestamp(self.game.last_played) if current else datetime.now()

        def apply(dt):
            asked = i18n.t("confirm_last", name=self.game.name,
                           when=dt.strftime("%d/%m/%Y %H:%M:%S"))
            if not self._confirm(asked):
                return False
            if not self.game.set_last_played(int(dt.timestamp())):
                self.status.config(text=i18n.t("err_write", err=self.ini.error or ""))
                return False
            self.refresh_stats()
            return True

        self._moment_dialog(i18n.t("dlg_last"), self.game.name,
                            i18n.t("dlg_source", section=INI_LAST_SECTION, name=self.game.key),
                            when, apply, self._clear_last_played)

    def _clear_last_played(self):
        if not self._confirm(i18n.t("confirm_clear_last", name=self.game.name)):
            return False
        if self.game.set_last_played(0):
            self.refresh_stats()
            return True
        self.status.config(text=i18n.t("err_write", err=self.ini.error or ""))
        return False

    def _moment_dialog(self, title, subject, subtitle, current, on_apply, on_clear):
        """Dialogue date + heure (local), avec « Maintenant » et un effacement optionnel."""
        tk = self.tk
        dlg = tk.Toplevel(self.win)
        dlg.title(title)
        dlg.configure(bg=BG, padx=22, pady=18)
        dlg.transient(self.win)
        dlg.resizable(False, False)

        tk.Label(dlg, text=subject, bg=BG, fg=TEXT, font=self.f_h2, wraplength=380,
                 justify="left").pack(anchor="w")
        tk.Label(dlg, text=subtitle, bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 12))

        form = tk.Frame(dlg, bg=BG)
        form.pack()
        date_var = tk.StringVar(value=current.strftime("%d/%m/%Y"))
        time_var = tk.StringVar(value=current.strftime("%H:%M:%S"))
        for col, (label, var, width) in enumerate(((i18n.t("field_date"), date_var, 14),
                                                   (i18n.t("field_time"), time_var, 10))):
            cell = tk.Frame(form, bg=BG)
            cell.grid(row=0, column=col, padx=7)
            tk.Label(cell, text=label, bg=BG, fg=MUTED, font=self.f_small).pack(anchor="center")
            e = tk.Entry(cell, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                         font=(self.family, 11), width=width, bd=0, justify="center")
            e.pack(fill="x", ipady=6, pady=(3, 0))
            if col == 0:
                e.focus_set()

        error = tk.Label(dlg, text="", bg=BG, fg="#f85149", font=self.f_small)
        error.pack(pady=(10, 0))

        buttons = tk.Frame(dlg, bg=BG)
        buttons.pack(pady=(12, 0))

        def apply(when):
            if on_apply(when) is False:
                return
            dlg.destroy()

        def on_now():
            apply(datetime.now())

        def on_submit():
            try:
                dt = datetime.strptime(date_var.get().strip() + " " + time_var.get().strip(),
                                       "%d/%m/%Y %H:%M:%S")
            except ValueError:
                error.config(text=i18n.t("err_datetime_format"))
                return
            if dt > datetime.now():
                error.config(text=i18n.t("err_future"))
                return
            apply(dt)

        tk.Button(buttons, text=i18n.t("btn_now"), command=on_now, bg=PANEL, fg=TEXT, font=self.f_body,
                  relief="flat", padx=12, pady=5, cursor="hand2", activebackground=CARD_SEL,
                  activeforeground=TEXT, bd=0).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text=i18n.t("btn_apply"), command=on_submit, bg=ACCENT_DARK, fg="#ffffff", font=self.f_body,
                  relief="flat", padx=14, pady=5, cursor="hand2", activebackground=ACCENT,
                  activeforeground="#ffffff", bd=0).pack(side="left", padx=(0, 8))
        if on_clear is not None:
            def clear():
                if on_clear() is False:
                    return
                dlg.destroy()

            tk.Button(buttons, text=i18n.t("btn_clear"), command=clear, bg=PANEL, fg=TEXT, font=self.f_body,
                      relief="flat", padx=12, pady=5, cursor="hand2", activebackground=CARD_SEL,
                      activeforeground=TEXT, bd=0).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text=i18n.t("btn_cancel"), command=dlg.destroy, bg=PANEL, fg=MUTED, font=self.f_body,
                  relief="flat", padx=12, pady=5, cursor="hand2", activebackground=CARD_SEL,
                  activeforeground=TEXT, bd=0).pack(side="left")

        dlg.bind("<Return>", lambda _e: on_submit())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        self._center(dlg)

    def _center(self, dlg):
        dlg.update_idletasks()
        x = self.win.winfo_rootx() + (self.win.winfo_width() - dlg.winfo_width()) // 2
        y = self.win.winfo_rooty() + (self.win.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
        dlg.grab_set()
        dlg.wait_window()

    def run(self, autoclose=None):
        if autoclose:
            self.win.after(int(autoclose * 1000), self.win.destroy)
        self.win.mainloop()


# ---------------------------------------------------------------- hors interface

def selftest(root_dir):
    print("COGBox folder: %s" % root_dir)
    print("  achievements/ %s" % ("present" if (root_dir / "achievements").is_dir() else "MISSING"))
    ini = CogBoxIni(root_dir / INI_NAME)
    print("  %s %s" % (INI_NAME, "present" if ini.exists else "MISSING"))
    games = [g.load() for g in discover_games(root_dir, ini)]
    print("games with content: %d" % len(games))
    ok = True
    total_play = 0
    for g in games:
        a, b, gp, gp_total = g.totals()
        total_play += g.play_seconds
        print("  %-9s %s  catalog=%3d  unlocked=%3d  %4d/%4d G  toml=%s"
              % (g.folder, g.title_id, b, a, gp, gp_total,
                 "yes" if g.unlock_path.is_file() else "no"))
        print("            [%s] %s = %d (%s)   [%s] %s = %d (%s)"
              % (INI_PLAY_SECTION, g.key, g.play_seconds, fmt_duration(g.play_seconds),
                 INI_LAST_SECTION, g.key, g.last_played,
                 fmt_unix_local(g.last_played) or "never"))
        ids = set()
        for e in g.entries:
            if e.id in ids:
                print("    WARNING duplicate id %d in the catalog" % e.id)
                ok = False
            ids.add(e.id)
        for aid in g.unlocks:
            if ids and aid not in ids:
                print("    note: id %d unlocked but not in the catalog" % aid)
    print("total play time: %d s (%s)" % (total_play, fmt_duration(total_play)))

    sample = {3: 134388782347605409, 1: 0, 12: local_to_filetime(datetime(2026, 1, 2, 3, 4, 5))}
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "user" / "achievements" / "TEST.toml"
        save_unlocks(p, sample)
        back = parse_unlocks(p.read_text(encoding="utf-8"))
        same = back == sample
        text = p.read_text(encoding="utf-8")
        print("TOML round trip: %s (%s)" % ("OK" if same else "FAILED", p.name))
        print("  header kept: %s" % ("yes" if text.startswith(TOML_HEADER) else "NO"))
        if not same:
            print("  expected  %s" % sample)
            print("  read back %s" % back)
            ok = False
        ft = sample[3]
        print("  FILETIME %d -> %s (local)" % (ft, fmt_time(ft)))
        if filetime_to_local(ft) is None:
            ok = False
        round_trip = local_to_filetime(filetime_to_local(ft))
        if abs(round_trip - ft) > 10:  # l'affichage s'arrête à la microseconde
            print("  FILETIME conversion: %d ticks off" % (round_trip - ft))
            ok = False
        if local_to_filetime(datetime(2026, 1, 2, 3, 4, 5)) != sample[12]:
            print("  datetime -> FILETIME mismatch")
            ok = False

        # CogBox.ini : remplacement en place, insertion en fin de section, section créée, reste intact
        src = ("[Front]\r\nBox = 3\r\n\r\n[PlayTime]\r\ngears2 = 13709\r\ngears1 = 93695\r\n"
               "\r\n[Window]\r\nFullscreen = 1\r\n")
        ini2 = Path(td) / INI_NAME
        ini2.write_bytes(src.encode("utf-8"))
        edit = CogBoxIni(ini2)
        edit.set(INI_PLAY_SECTION, "gears1", "1000")
        edit.set(INI_PLAY_SECTION, "gears3", "2000")
        edit.set(INI_LAST_SECTION, "gears1", "1795438448")
        saved = edit.save()
        again = CogBoxIni(ini2)
        checks = {
            "value replaced": again.geti64(INI_PLAY_SECTION, "gears1") == 1000,
            "key inserted in section": again.geti64(INI_PLAY_SECTION, "gears3") == 2000,
            "section created": again.geti64(INI_LAST_SECTION, "gears1") == 1795438448,
            "other sections intact": again.get("Front", "Box") == "3" and again.get("Window", "Fullscreen") == "1",
            "neighbouring key intact": again.geti64(INI_PLAY_SECTION, "gears2") == 13709,
            "CRLF kept": (lambda raw: raw.count(b"\r\n") == raw.count(b"\n"))(ini2.read_bytes()),
        }
        print("round trip %s: %s%s" % (INI_NAME, "OK" if all(checks.values()) and saved else "FAILED",
                                          "" if all(checks.values()) else "  " +
                                          ", ".join(k for k, v in checks.items() if not v)))
        if not all(checks.values()) or not saved:
            print("  written content:\n%s" % ini2.read_text(encoding="utf-8", errors="replace"))
            ok = False
    # sauvegardes : zip des fichiers COGBox, aperçu de son contenu, restauration
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src"
        (src / "Gears3" / "user" / "achievements").mkdir(parents=True)
        (src / "Gears3" / "user-p2" / "achievements").mkdir(parents=True)
        (src / "profiles" / "1").mkdir(parents=True)
        (src / "Gears3" / "user" / "0000000000000000").mkdir()
        (src / "Gears3" / "user" / "0000000000000000" / "dlc.bin").write_bytes(b"0" * 4096)
        (src / INI_NAME).write_text("[PlayTime]\r\ngears3 = 3600\r\n\r\n[LastPlayed]\r\ngears3 = 1795438448\r\n",
                                    encoding="utf-8", newline="")
        (src / "settings.ini").write_text("[General]\r\nGame=2\r\n", encoding="utf-8", newline="")
        (src / "profiles" / "1" / "identity.json").write_text(
            '{"display_name": "Myth", "discriminator": "2722"}', encoding="utf-8")
        unlocked = "# Achievement unlock state\r\n\r\n[unlocked.%d]\r\nfiletime = %d\r\n"
        (src / "Gears3" / "user" / "achievements" / "4D5308AB.toml").write_text(
            unlocked % (1, 1) + "\r\n" + unlocked % (2, 2), encoding="utf-8", newline="")
        (src / "Gears3" / "user-p2" / "achievements" / "4D5308AB.toml").write_text(
            unlocked % (3, 3), encoding="utf-8", newline="")

        zpath = backup.backups_dir(src) / backup.default_name()
        files, size = backup.create(src, zpath)
        info = backup.Backup(zpath).load()
        dest = Path(td) / "dest"
        (dest / "Gears3").mkdir(parents=True)
        written = backup.restore(dest, zpath)
        profile = backup.folder_summary(dest, "Gears3/user-p2")
        checks = {
            "DLC left out": files == 5,
            "preview finds the play time": info.play.get("gears3") == 3600,
            "preview counts unlocks of both profiles": info.unlock_count("Gears3", "4D5308AB") == 3,
            "preview reads the profile name": info.profiles == ["Myth #2722"],
            "restore writes every file": written == files,
            "profile summary sees its save": profile[0] == 1,
            "restored file has its content": "[unlocked.3]" in (dest / "Gears3" / "user-p2" / "achievements" /
                                                                 "4D5308AB.toml").read_text(encoding="utf-8"),
        }
        checks["reset empties the profile"] = (backup.reset(dest, "Gears3/user-p2") == 1
                                               and not (dest / "Gears3" / "user-p2" / "achievements").exists())
        print("backup round trip: %s%s" % ("OK" if all(checks.values()) else "FAILED",
                                          "" if all(checks.values()) else
                                          "  " + ", ".join(k for k, v in checks.items() if not v)))
        if not all(checks.values()):
            ok = False

    gaps = i18n.missing()
    print("interface language: %s" % i18n.code())
    if gaps:
        print("  missing translations: %s" % ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(gaps.items())))
        ok = False
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None):
    if sys.stdout is None:  # build --windowed : pas de console
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    for stream in (sys.stdout, sys.stderr):
        # console Windows en cp1252 : une durée en chinois ne doit pas faire planter --selftest
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Achievements and play time editor for COGBox")
    ap.add_argument("--root", help="COGBox folder (default: exe/script folder, then settings.ini)")
    ap.add_argument("--selftest", action="store_true", help="check the files without opening the window")
    ap.add_argument("--autoclose", type=float, help="close the window after N seconds (test)")
    args = ap.parse_args(argv)

    root_dir, should_save = find_root(args.root)
    if args.selftest:
        i18n.set_language(ini_language(CogBoxIni(root_dir / INI_NAME)))
        return selftest(root_dir)
    if should_save:
        save_remembered_root(root_dir)

    try:
        App(root_dir).run(autoclose=args.autoclose)
    except Exception:
        import traceback

        text = traceback.format_exc()
        try:
            (root_dir / "AchievementsManager-error.txt").write_text(text, encoding="utf-8")
        except OSError:
            pass
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror("Achievements Manager", text[-1800:])
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())