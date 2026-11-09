# Map Themes Evolved

<img src="map_themes_evolved/icon.png" width="64" align="right" alt="">

A QGIS plugin that turns the eye button in the Layers panel ("Manage Map Themes") into a searchable, folder-based theme browser. It stays fully compatible with native QGIS map themes.

Folders are just part of the theme name: `Debrecen/Land use/Residential` shows up as `Residential` in the folders `Debrecen ▸ Land use`. Nothing else is stored, so a project opened without the plugin behaves exactly as before. You just see the full names in the flat list.

## Using it

Click the **eye button** in the Layers panel.

- **Click a theme** to apply it, the same as the original menu. **Click a folder** to open or close it.
- **Type** to search. Words can be in any order, and case and accents are ignored (`viz telek` finds `Vizsgálat - Telekméretek`). Press **Enter** to apply the best match.
- The **status line** shows the active theme. If you changed layers since applying a theme, it says so and offers **Update** (overwrite that theme) and **Save as new…**.
- **Right-click** a theme or folder for everything else: update, rename, **Move to ▸**, duplicate, copy name, delete, and new theme or subfolder here.
- **Drag** themes or folders onto a folder to move them, or onto empty space to move them to the top level.
- **New theme** and **New folder** add a row you type the name into. Type `Area/Topic/Name` to create subfolders on the fly.
- Every change can be **undone**: use the message bar's *Undo*, the ↶ button, or *Plugins ▸ Map Themes Evolved*.
- **Open as panel** (window icon) docks the same browser beside the map, which is handy for longer organising sessions.
- The **Layers:** row holds QGIS's own Show All / Hide All / Show Selected… actions, unchanged.
- **Right-click the eye button**, or use *⋯ ▸ Classic QGIS map themes menu*, for the original menu.

| Key | Action |
|---|---|
| type | search |
| ↑ / ↓ | move through the list |
| Enter | apply theme and close |
| Ctrl+Enter, Ctrl+click, middle-click | apply theme and keep the list open (or use 📌) |
| F2 | rename in place |
| Del | delete (can be undone) |
| Esc | clear the search, then close |

You can assign a shortcut to *Browse Map Themes…* in *Settings ▸ Keyboard Shortcuts*.

## Compatibility

- Reads and writes only through QGIS's own map-theme API (`QgsMapThemeCollection`).
- Renames use `renameMapTheme`, so **print layouts that follow a theme are updated by QGIS itself**. Data-defined theme expressions are *not* updated by QGIS. Check those after renaming.
- Remembered folder open/closed state lives in your QGIS settings, never in the project file.
- Disabling the plugin restores the original eye-button menu immediately.

Tested on QGIS 3.44 (Qt5). It's written to also work on QGIS 4.x (Qt6), but that hasn't been tested yet.

## Install

From a release: download `map_themes_evolved-<version>.zip` from [Releases](https://github.com/danzig666/qgis-map-themes-evolved/releases). In QGIS, open *Plugins ▸ Manage and Install Plugins ▸ Install from ZIP*.

For development, link the plugin folder into your profile (PowerShell):

```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\map_themes_evolved" -Target "<repo>\map_themes_evolved"
```

## Tests

```bash
python -m pytest map_themes_evolved/test -q
```

## Layout

```
map_themes_evolved/
├── core/paths.py      pure-Python name/folder/sort/search logic (unit-tested)
├── core/service.py    the only code touching QgsMapThemeCollection
├── core/undo.py       undo stack
├── hook/eye_button.py find, hook and restore the Layers-panel eye button
├── ui/                tree model, browser widget, popup, dock, dialogs
├── icons/             plugin icons (generated from assets/icon_sheet.png)
└── plugin.py          wiring
```

See [PLAN.md](PLAN.md) for the design and roadmap.
