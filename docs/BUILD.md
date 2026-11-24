# Build

L'application est un seul fichier Python (`achievements_manager.py`) empaqueté par
[PyInstaller](https://pyinstaller.org) en exécutable autonome. Toute sortie va sous
`build/output/<platform>/` (le dossier `build/` est ignoré par git) :

| Plateforme | Script local (ignoré par git) | Sortie |
| --- | --- | --- |
| Toutes (une seule commande) | `build-all.bat` (versionné) | selon la machine, voir plus bas |
| Windows (cible principale) | `build-windows.bat` | `build/output/windows/AchievementsManager.exe` |
| Linux (optionnel) | `build-linux.sh` | `build/output/linux/AchievementsManager` |
| macOS (optionnel) | `build-mac.sh` | `build/output/macos/AchievementsManager.app` |

`build/work/` et `build/*.spec` reçoivent les fichiers intermédiaires de PyInstaller.

## Toutes les plateformes

```bat
build-all.bat
```

`build-all.bat` enchaîne ce que la machine peut produire, et le dit pour le reste (sortie en anglais,
comme celle du `--selftest`) :

- **Windows** : toujours, avec la commande ci-dessous (fichier unique, sans console) ;
- **Linux** : seulement depuis WSL, et seulement si une distribution par défaut existe et que son
  `python3` a tkinter ; sinon la ligne est marquée `Skipped` ;
- **macOS** : jamais depuis Windows — PyInstaller ne compile pas en cross. Sur un Mac :
  `./build-mac.sh`.

Il sort en code 1 si un build tenté a échoué, et affiche en fin de course le chemin de chaque
binaire produit (`OK: …`). Contrairement aux trois scripts ci-dessus, il est versionné (rien dedans
n'est spécifique à une machine) ; les commandes Linux/macOS restent dans leurs scripts locaux.

## Windows

```bat
build-windows.bat
```

Le script vérifie Python + tkinter, installe PyInstaller (et Pillow) si besoin, puis lance :

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name AchievementsManager ^
  --distpath build\output\windows ^
  --workpath build\work ^
  --specpath build ^
  achievements_manager.py
```

`--onefile` = un seul `.exe` ; `--windowed` = pas de fenêtre de console (les `print` du
`--selftest` sont alors perdus : seul le code de sortie est parlant).

## Linux

```sh
./build-linux.sh
```

Nécessite `python3-tk` (Debian/Ubuntu) ou `python3-tkinter` (Fedora). Même commande avec
`--distpath build/output/linux` ; `--windowed` n'a pas d'effet sur Linux.

## macOS

```sh
./build-mac.sh
```

Nécessite un Python avec tkinter (python.org, ou `brew install python-tk`). `--windowed` produit un
bundle `.app` ; le premier lancement demande l'autorisation Gatekeeper car le bundle n'est pas signé.

## Vérifier un build

```sh
build/output/windows/AchievementsManager.exe --selftest
echo %ERRORLEVEL%
```

Le code de retour vaut 0 si les conversions FILETIME, l'aller-retour TOML et l'aller-retour
`CogBox.ini` sont corrects. En build `--windowed`, c'est le seul signal disponible.
