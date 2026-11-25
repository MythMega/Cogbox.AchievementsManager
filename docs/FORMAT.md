# Formats de COGBox utilisés

Tout est vérifié dans le code source de COGBox (dépôt `cogbox`, branche `dev`). Les chemins cités
sont relatifs à ce dépôt.

## 1. Catalogue des succès (lecture seule)

`<COGBox>\achievements\<TitleID>\catalog.txt`, écrit par le launcher.

```
# COGBox achievement catalog
title = 4D5307D5
game = Gears of War
language = 1

[achievement]
id = 1
gamerscore = 5
flags = 8
image = 17
label = ...
description = ...
unachieved = ...
```

- En-tête obligatoire : la première ligne doit commencer par `# COGBox achievement catalog`
  (`Gears2-Native/src/layer0_xenos/achievements_data.cpp`, `ParseCatalog`).
- `title` est hexadécimal ; les autres entiers sont décimaux.
- `flags & 0x8 == 0` ⇒ succès secret (affiché avec la mention `SECRET`).
- Chaînes échappées : `\\` et `\n` (`unescape`).

Icônes : `icons\<id>.png` (64×64). Jaquettes utilisées par l'écran des jeux :
`<COGBox>\covers\<clé>-boxart.jpg`, où la clé est celle de `kGames` (`gears1`…`judgment`) — c'est le
même nom de fichier que celui employé par le launcher pour le fond d'écran.

TitleIDs : Gears 1 `4D5307D5`, Gears 2 `4D53082D`, Gears 3 `4D5308AB`, Judgment `4D530A26`.

## 2. Déblocages (lecture + écriture)

`<COGBox>\<Jeu>\user\achievements\<TitleID>.toml`. Le runtime ReXGlue le lit au démarrage et le
réécrit en quittant.

- Depuis COGBox 0.5.0 il y a un dossier par profil : `user` pour le profil 1, `user-p2`, `user-p3`…
  pour les suivants (`games.cpp`, `game_user_dir_for`). Le profil courant est `[Profiles] Current`
  de `CogBox.ini` (1 par défaut) : l'outil lit et écrit le `.toml` de ce dossier, et la sauvegarde
  couvre tous les profils.

```
# Achievement unlock state - managed by ReXGlue runtime

[unlocked.27]
filetime = 134398520130840056
```

- Une section par succès débloqué, triées par identifiant à l'écriture.
- `filetime` = 100 ns depuis le 1601-01-01 **UTC** (FILETIME Windows) :
  `filetime = (unix + 11644473600) * 10 000 000`.
- Pas d'en-tête `[unlocked.<id>]` ⇒ succès non obtenu. Retirer la section décoche le succès.
- L'en-tête du fichier existant est conservé s'il y en a un, sinon celui du runtime est écrit.
- Écriture atomique (`.tmp` puis `os.replace`), comme `WriteFileAtomic` de COGBox : un crash ne
  laisse pas de fichier tronqué.

## 3. Compteurs du launcher (lecture + écriture)

`<COGBox>\CogBox.ini`, à côté de `cogbox.exe` — cf. `Gears2-Native/cogbox/src/util.cpp` (`Ini`) et
`src/play.cpp`.

```
[PlayTime]
gears1 = 93695
gears2 = 13709
gears3 = 77856
judgment = 1411

[LastPlayed]
gears1 = 1795438448
...
```

- **Temps de jeu** : secondes cumulées. `play.cpp` (fin de partie) ajoute la durée écoulée, mais
  seulement si elle atteint 20 s — une partie plus courte n'est pas comptée. C'est la valeur que le
  launcher affiche sous la jaquette (`human_duration` dans `util.cpp`).
- **Dernier lancement** : secondes Unix, posées au *démarrage* du jeu (`play.cpp`, juste après
  `CreateProcessW`) et non à sa fermeture.
- Le fichier est un ini simple : lignes `clé = valeur`, sections `[...]`, **CRLF**, sections et clés
  comparées sans tenir compte de la casse, commentaires `;` ou `#`.
- `Ini::set` remplace la ligne existante (`clé = valeur`, espaces autour du `=`), sinon insère la clé
  en fin de section, sinon crée la section (précédée d'une ligne vide). L'outil reproduit exactement
  ces règles et ne reformate rien d'autre : le launcher réécrit le fichier en entier, une
  reformatisation serait écrasée de toute façon.
- Valeur `0` : temps de jeu nul / jeu jamais lancé (le launcher n'affiche alors rien).

## 4. Langue du launcher (lecture seule)

```
[Launcher]
Language = fr
```

- Valeurs écrites par COGBox (`Gears2-Native/cogbox/src/i18n.cpp`, `languages()`) : `en`, `es`,
  `fr`, `de`, `it`, `pt-BR`, `pl`, `hu`, `ru`, `ja`, `zh-Hans`, `ko`, plus `auto` (langue de
  Windows).
- L'outil la relit à chaque chargement de dossier pour choisir la langue de son interface. Il
  comprend `en`, `fr`, `pt-BR`, `zh-Hans`, `ko`, `pl`, `ru`, `cs`, `hu` ; les autres codes tombent
  sur l'anglais.

## 5. Profils et comptes locaux

- `CogBox.ini` → `[Profiles] Current` (profil utilisé) et `[Profiles] Count` (`front.cpp`).
- Dossier de sauvegarde du jeu pour le profil N : `<Jeu>\user` (N = 1) ou `<Jeu>\user-pN`
  (`games.cpp`, `game_user_dir_for`), avec `achievements\<TitleID>.toml` dedans. Le contenu
  téléchargé (DLC) vit dans `0000000000000000` du profil 1 et est partagé par une jonction.
- Compte local : `profiles\<id>\identity.json` (`profiles.cpp`, `profile_dir`) — `display_name`,
  `discriminator`, `xuid`, `uuid`, `token`.
- Les réglages propres au jeu sont rangés sous `<user>\<TitleID>\profile\<gamertag>\`, donc le
  gamertag est un nom de dossier. Le patch SDK 124 (GitHub #416 / #424) reprend la sauvegarde la
  plus récente d'un autre gamertag quand le nom change : renommer un profil ne perd plus ses
  réglages.

## 6. Succès d'un autre jeu (patch 127, GitHub #439)

Gears 2 demande les succès de Gears 1 (`4D5307D5`) pour débloquer Carmine, RAAM et Kim. Le launcher
passe `--xam_other_title_achievements "<TitleID>=<chemin>;…"` (`page.cpp`, `env_refresh`) avec, pour
globaliser, le `.toml` du profil courant des trois autres jeux ; le patch lit ce fichier.
Conséquence pour cet outil : débloquer un succès de Gears 1 change aussi ce que Gears 2 voit, et
inversement rien n'est recopié entre les fichiers.

## 7. Sauvegardes de l'outil

`<COGBox>\backups\cogbox-profileinfo-backup-<AAAA-MM-JJ-hh-mm-ss>.zip` (nom modifiable) contient
`CogBox.ini`, `settings.ini`, `profiles\<id>\identity.json` et tous les `<Jeu>\user` / `user-pN`.

- Ne sont pas pris : `00000002` (DLC), `000B0000` (title update) — comme `zip_skip_dir` du
  « Back up saves » de COGBox (`main.cpp`) —, ni `0000000000000000`, `0000010000`, `game`,
  `ini-edits`, `mod-overlay`, `shadercache`, `logs`, `covers`, qui sont du contenu ou des fichiers
  régénérés. Les liens et jonctions ne sont pas suivis.
- Le zip s'écrit en `.partial` puis est renommé, comme COGBox.
- Restauration : les fichiers du zip sont réécrits (pas d'effacement de ce qui a été créé depuis),
  et toute entrée qui ne correspond à aucun dossier du dossier COGBox est ignorée.
- Un profil seul se sauvegarde, se restaure et se vide de la même façon, en se limitant à
  `<Jeu>\user*` (onglet « Données de jeu ») ; le nom du zip porte alors `-<jeu>-<dossier>-`. Le
  « reset » écrit d'abord `…-before-reset-….zip`, puis supprime les mêmes fichiers que la sauvegarde
  (le DLC, les liens et `ini-edits` restent).

## Ce que l'outil ne touche pas

`settings.ini`, `[Hashes]`, `[CodeHashes]`, `[Keys.*]`, `[Profile]`, `[Profiles]`, les sauvegardes,
les mods : rien n'est modifié en dehors des sections `[PlayTime]` / `[LastPlayed]`, des `.toml` de
succès, et des zips écrits dans `backups\`.
