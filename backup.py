"""Sauvegardes des fichiers de COGBox (zip), aperçu et remise en place.

Ce que COGBox garde du joueur, et que ce module empaquette :

  - ``CogBox.ini`` et ``settings.ini`` (racine du dossier COGBox) ;
  - ``profiles\\<id>\\identity.json`` : le compte local (pseudo, discriminant) ;
  - ``<Jeu>\\user`` (profil 1) et ``<Jeu>\\user-p2``, ``user-p3``... (autres profils) :
    les sauvegardes, dont ``achievements\\<TitleID>.toml`` (succès débloqués).

Un sous-ensemble (``only``, par exemple ``Gears3/user-p2``) suffit pour sauvegarder,
restaurer ou vider un seul profil : c'est ce que fait l'onglet « Game data ».

Les dossiers de contenu ne sont pas pris (ils pèsent des centaines de Mo et se
retéléchargent) : DLC (``00000002``, ``0000000000000000``), title update
(``000B0000``), et les fichiers que le launcher génère (``game``, ``ini-edits``,
``mod-overlay``, ``shadercache``, ``logs``, ``covers``). COGBox fait de même pour
son propre « Back up saves » (main.cpp, ``zip_skip_dir``).

La restauration réécrit les fichiers présents dans le zip ; ceux créés depuis la
sauvegarde ne sont pas supprimés. Les entrées du zip qui ne correspondent à aucun
dossier du dossier COGBox sont ignorées (un zip étranger ne peut pas écrire ailleurs).
"""

import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

DEFAULT_PREFIX = "cogbox-profileinfo-backup-"
ROOT_FILES = ("CogBox.ini", "settings.ini")
BACKUP_DIR = "backups"

SKIP_DIRS = frozenset({
    "00000002",           # DLC
    "000b0000",           # title update
    "0000000000000000",   # DLC installé dans le dossier du profil
    "0000010000",         # contenu de profil
    "game", "shadercache", "logs", "covers", "mod-overlay", "ini-edits",
})

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def default_name(tag=""):
    """cogbox-profileinfo-backup[-<tag>]-AAAA-MM-JJ-hh-mm-ss.zip."""
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return "%s%s%s.zip" % (DEFAULT_PREFIX, tag + "-" if tag else "", stamp)


def profile_tag(game, user_dir):
    """Étiquette d'un profil dans un nom de zip : gears3-user-p2."""
    return ("%s-%s" % (game, Path(user_dir).name)).lower()


def backups_dir(root):
    return Path(root) / BACKUP_DIR


def check_name(name):
    """Nom de fichier valide pour une sauvegarde (pas de dossier, .zip)."""
    return (bool(name) and name == os.path.basename(name) and "." not in (name, "..")
            and "/" not in name and "\\" not in name and ":" not in name
            and name.lower().endswith(".zip") and len(name) > 4)


def fmt_size(n):
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return ("%d %s" % (value, unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024
    return "%.1f GB" % value


def _is_user_dir(name):
    low = name.lower()
    return low == "user" or (low.startswith("user-p") and low[6:].isdigit())


def user_dirs_of(game_dir):
    """Dossiers de sauvegarde d'un jeu : user (profil 1), user-p2, user-p3..."""
    try:
        return sorted(p for p in Path(game_dir).iterdir() if p.is_dir() and _is_user_dir(p.name))
    except OSError:
        return []


def game_user_dirs(root):
    """(nom du dossier de jeu, dossier de sauvegarde) pour tout le dossier COGBox."""
    root = Path(root)
    try:
        tops = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    return [(game.name, sub) for game in tops for sub in user_dirs_of(game)]


def _is_link(entry):
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def _collect(folder, arc, out):
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        if _is_link(entry):
            continue
        if entry.is_dir():
            if entry.name.lower() in SKIP_DIRS:
                continue
            _collect(Path(entry.path), arc + "/" + entry.name, out)
        elif entry.is_file():
            out.append((Path(entry.path), arc + "/" + entry.name))


def files_to_back_up(root, only=None):
    """(chemin absolu, nom dans le zip) de ce qui est sauvegardé ; ``only`` limite à un dossier."""
    root = Path(root)
    out = []
    if only:
        _collect(root / only, only.strip("/"), out)
        return out
    for name in ROOT_FILES:
        if (root / name).is_file():
            out.append((root / name, name))
    profiles = root / "profiles"
    if profiles.is_dir():
        _collect(profiles, "profiles", out)
    for game, user_dir in game_user_dirs(root):
        _collect(user_dir, game + "/" + user_dir.name, out)
    return out


def folder_summary(root, only):
    """(fichiers, octets, date du plus récent) d'un dossier sauvegardé."""
    files = files_to_back_up(root, only)
    total, newest = 0, None
    for path, _arc in files:
        try:
            info = path.stat()
        except OSError:
            continue
        total += info.st_size
        when = datetime.fromtimestamp(info.st_mtime)
        if newest is None or when > newest:
            newest = when
    return len(files), total, newest


def create(root, zip_path, only=None):
    """Écrit le zip (temporaire puis renommage) ; renvoie (fichiers, octets)."""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    part = zip_path.with_name(zip_path.name + ".partial")
    total, count = 0, 0
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for path, arc in files_to_back_up(root, only):
                z.write(path, arc)
                count += 1
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    except Exception:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    os.replace(part, zip_path)
    return count, total


def _allowed_tops(root):
    """Premiers segments qu'une restauration a le droit d'écrire."""
    root = Path(root)
    tops = {name.lower() for name in ROOT_FILES} | {"profiles"}
    try:
        for p in root.iterdir():
            if p.is_dir():
                tops.add(p.name.lower())
    except OSError:
        pass
    return tops


def _member_parts(name):
    """Chemin du zip en morceaux propres, ou None s'il sort du dossier."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or parts[0].endswith(":"):
        return None
    return parts


def restore(root, zip_path, only=None):
    """Réécrit les fichiers du zip dans le dossier COGBox ; renvoie le nombre écrit."""
    root = Path(root)
    tops = _allowed_tops(root)
    only = only.strip("/").lower() if only else None
    written = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = _member_parts(info.filename)
            if parts is None or parts[0].lower() not in tops:
                continue
            if any(p.lower() in SKIP_DIRS for p in parts[:-1]):
                continue
            if only and "/".join(parts).lower() != only and not "/".join(parts).lower().startswith(only + "/"):
                continue
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    return written


def _prune(folder):
    """Enlève les sous-dossiers vides, sans jamais suivre un lien/jonction ni entrer dans un dossier exclu.

    ``rglob`` traverserait la jonction du DLC partagé et viderait des dossiers du contenu installé :
    ici on ne descend que dans de vrais dossiers, et les noms de SKIP_DIRS sont laissés tels quels.
    """
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        if _is_link(entry) or not entry.is_dir() or entry.name.lower() in SKIP_DIRS:
            continue
        path = Path(entry.path)
        _prune(path)
        try:
            path.rmdir()  # seulement s'il est vide
        except OSError:
            pass


def reset(root, only):
    """Efface les fichiers sauvegardés d'un dossier (DLC, liens et dossiers exclus intacts).

    Renvoie le nombre de fichiers supprimés ; le dossier du profil lui-même reste.
    """
    root = Path(root)
    files = files_to_back_up(root, only)  # ne traverse déjà ni les liens ni les dossiers exclus
    for path, _arc in files:
        path.unlink()
    folder = root / only
    if folder.is_dir():
        _prune(folder)
    return len(files)


def profile_name(root, number):
    """Pseudo du profil ``profiles\\<number>\\identity.json`` ('' s'il n'y en a pas)."""
    path = Path(root) / "profiles" / str(number) / "identity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return ""
    name = str(data.get("display_name") or "").strip()
    tag = str(data.get("discriminator") or "").strip()
    return "%s #%s" % (name, tag) if name and tag else name


class Backup:
    """Un zip de sauvegarde ; ``load()`` lit son contenu (petits fichiers seulement)."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        try:
            info = self.path.stat()
            self.mtime = datetime.fromtimestamp(info.st_mtime)
            self.size = info.st_size
        except OSError:
            self.mtime, self.size = datetime.fromtimestamp(0), 0
        self.files = 0
        self.play = {}
        self.last = {}
        self.unlocks = {}
        self.profiles = []
        self.error = ""
        self._loaded = False

    def load(self):
        if self._loaded:
            return self
        self._loaded = True
        try:
            with zipfile.ZipFile(self.path) as z:
                self.files = sum(1 for i in z.infolist() if not i.is_dir())
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename.replace("\\", "/")
                    low = name.lower()
                    if low == "cogbox.ini":
                        self._read_ini(z.read(info).decode("utf-8", "replace"))
                    elif low.startswith("profiles/") and low.endswith("/identity.json"):
                        self._read_identity(z.read(info))
                    elif "/achievements/" in low and low.endswith(".toml"):
                        self._read_unlocks(name, z.read(info))
        except (OSError, zipfile.BadZipFile) as exc:
            self.error = str(exc)
        return self

    def contains(self, only):
        """Le zip contient-il quelque chose de ce dossier ?"""
        prefix = only.strip("/").lower() + "/"
        try:
            with zipfile.ZipFile(self.path) as z:
                return any(n.replace("\\", "/").lower().startswith(prefix) for n in z.namelist())
        except (OSError, zipfile.BadZipFile):
            return False

    def _read_ini(self, text):
        from achievements_manager import CogBoxIni  # CogBoxIni est défini après l'import de ce module

        ini = CogBoxIni.from_text(text)
        for section, out in (("PlayTime", self.play), ("LastPlayed", self.last)):
            for key, value in ini.items(section).items():
                try:
                    out[key.lower()] = max(0, int(value, 10))
                except ValueError:
                    continue

    def _read_identity(self, raw):
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return
        name = str(data.get("display_name") or "").strip()
        if not name:
            return
        tag = str(data.get("discriminator") or "").strip()
        self.profiles.append("%s #%s" % (name, tag) if tag else name)

    def _read_unlocks(self, name, raw):
        from achievements_manager import parse_unlocks

        parts = name.split("/")
        if len(parts) < 3:
            return
        key = (parts[0].lower(), Path(parts[-1]).stem.upper())
        self.unlocks[key] = self.unlocks.get(key, 0) + len(parse_unlocks(raw.decode("utf-8", "replace")))

    def unlock_count(self, folder, title_id):
        return self.unlocks.get((folder.lower(), title_id.upper()), 0)


def list_backups(root, only=None):
    """Sauvegardes du dossier backups, la plus récente d'abord (``only`` : celles d'un profil)."""
    folder = backups_dir(root)
    try:
        paths = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    items = [Backup(p) for p in paths]
    return [item for item in items if item.contains(only)] if only else items
