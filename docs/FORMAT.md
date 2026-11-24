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

## Ce que l'outil ne touche pas

`settings.ini`, `[Hashes]`, `[CodeHashes]`, `[Keys.*]`, `[Profile]`, les sauvegardes, les mods : rien
n'est modifié en dehors des sections `[PlayTime]` / `[LastPlayed]` et des `.toml` de succès.
