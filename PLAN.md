# Map Themes Evolved — Plan

A QGIS plugin that replaces the eye-icon "Manage Map Themes" menu with a searchable, folder-based theme browser. QGIS's own map-theme collection stays the only source of truth, so a project opened without the plugin works exactly as before.

---

## 1. Goals and non-goals

**Goals**
1. Find any theme in under 2 seconds: open the eye menu, type a few letters, press Enter.
2. Organise themes in nested folders using only theme names (`Riverton/Land use/Residential`).
3. 100 % compatible with native QGIS: same project file, same theme records, same behaviour when the plugin is off.
4. Keep every native function (show/hide layer actions, Add, Replace, Rename, Remove, apply). Native actions stay one click away, not buried.
5. Degrade gracefully: if a future QGIS changes the eye button, the plugin still works through its dock panel and locator. It never breaks QGIS.

**Non-goals (for now)**
- Changing the flat theme combo boxes in Layout map properties, extra map views or 3D views. Those are C++ widgets. Slash names still sort into readable groups there.
- Storing theme data anywhere except `QgsMapThemeCollection`.
- Theme import/export between projects (other plugins do this; maybe later).

---

## 2. Changes from the original idea (and why)

| Original idea | Changed to | Why |
|---|---|---|
| New `QMenu` with the whole native menu nested as an "Original QGIS controls" submenu | A **popup panel** with the native actions (Show All, Hide All, Add, …) in a compact row and a "Classic menu" entry | A submenu adds a click to every native action and hides them. Reusing the *same* native `QAction` objects keeps identical behaviour and shortcuts. |
| Tree inside a `QMenu` via `QWidgetAction` | A frameless `Qt.Popup` widget (`QFrame`) shown under the eye button | `QMenu` grabs arrow keys and Enter, so a tree and line edit inside it behave badly. A real popup gives proper focus, keyboard navigation and resizing. |
| Escape convention for literal `/` | **Per-project separator setting** (`/` by default; can be `\`, `»`, `::`, `|` or *off*) | Escapes look ugly in every native combo box. A project that already uses `/` literally (e.g. `Roads/Rails`) just picks another separator or turns folders off. |
| Plugin must update layout references after rename | Always rename with `renameMapTheme()`. Core then updates layout maps and canvases itself through the `mapThemeRenamed` signal. The plugin **audits** whatever core can't update. | Avoids reimplementing core logic. Removing and re-inserting a theme would break those links, so it's banned. |
| Only the eye-button UI | Eye popup **+ dock panel + Locator filter** sharing one model | The eye button is an undocumented hook. A dock covers heavy editing (drag and drop, multi-select). The Locator (Ctrl+K) gives instant keyboard switching. |
| Empty folders impossible | Empty folders live for the session only (until a theme is placed in them) | Lets you do "New folder → drag themes in" without hidden metadata that could drift out of sync with the real themes. |
| — | **Undo** for delete, rename and move (message-bar "Undo" button) | Native theme edits are not on any undo stack. Batch folder operations make that risky. |
| — | Search by **layer** as well as theme name (`layer:roads`) | "Which themes show this layer?" is a frequent question QGIS can't answer today. |

---

## 3. Compatibility contract (hard rules)

1. **Single source of truth:** read and write only through `QgsProject.instance().mapThemeCollection()`. The tree is a view rebuilt from `mapThemes()`.
2. **Names are only changed when you rename or move something.** Opening, browsing or searching never writes.
3. **Rename and move go through `renameMapTheme(old, new)`.** Never remove + insert.
4. **Replace goes through `update(name, record)`**, using `QgsMapThemeCollection.createThemeFromCurrentState(root, model)` exactly like native.
5. **Project file:** the plugin writes only its own project custom properties (`QgsProject.writeEntry("MapThemesEvolved", …)`): the custom folder/theme order and the separator choice. QGIS ignores these entries. Expanded folders and window geometry go to QgsSettings.
6. **Live sync:** themes changed by native UI, scripts or other plugins show up immediately (via `mapThemesChanged`, `mapThemeRenamed`, `mapThemeChanged`, `QgsProject.readProject` and `cleared`).
7. **Clean unload:** restore the original menu and popup mode on the eye button. Disconnect every signal. Hook and unhook can safely run more than once (Plugin Reloader safe).
8. **Native menu always reachable:** "Classic menu…" entry in the popup, plus an optional setting: right-click on the eye button opens the native menu.

---

## 4. Naming model

```
Riverton/Land use/Residential   →  Riverton ▸ Land use ▸ Residential
Riverton / Transport / Roads    →  Riverton ▸ Transport ▸ Roads   (spaces around separator tolerated)
Overview                        →  Overview (root)
```

- **Parsing:** split on the separator and trim each segment. Ignore empty segments for display (`A//B` shows as `A ▸ B`) but keep the real full name for every operation.
- **Writing:** the plugin writes `Folder/Sub/Name` by default. A per-project "spaced separators" option writes `Folder / Sub / Name` (easier to read in native combos). When a project already has themes, the default follows whichever style most of them use.
- **Theme and folder with the same name** (`A` and `A/B`): show folder `A` and a theme leaf `A` side by side. Each has its own icon and both work normally.
- **Sorting:** natural, case-insensitive, locale-aware (`QCollator` with numeric mode), folders first (configurable). Native `mapThemes()` sorts by raw code point. In a real project this gives `MTrT-1, MTrT-10, MTrT-11 … MTrT-2`, puts `Átnézeti` after `xWork`, and puts `Vizsgálat - önkormányzati…` after `Vizsgálat - Tulajdoni…`. The plugin's sort fixes all three. To force an order, prefix with numbers (`01 Overview`); a setting can hide those prefixes in the display.
- **Validation for new names:** no empty segments, no leading or trailing separator, no duplicate full name. Case-only clashes produce a warning. Problems show inline in the dialog, not as an error popup afterwards.

---

## 5. User interface

### 5.1 Eye-button popup (main entry point)

```
┌──────────────────────────────────────────┐
│ 🔍 Search themes…              [⚙]      │  ← focused on open
├──────────────────────────────────────────┤
│ ▾ 📁 Riverton                            │
│    ▾ 📁 Land use                         │
│        ● Residential          ← current  │
│          Industrial                      │
│    ▸ 📁 Transport                        │
│ ▸ 📁 Lakeside                            │
│   Overview                               │
├──────────────────────────────────────────┤
│ [+ Add] [⟳ Replace] [✎ Rename] [🗑]      │  ← act on selection / current
│ [👁 All] [⊘ None] [Selected…▾]           │  ← native QActions, reused
│ Classic menu…            Open panel ⇱    │
└──────────────────────────────────────────┘
```

- **Opening:** clicking the eye opens the popup. It remembers its size, keeps folders expanded as you left them and scrolls to the current theme.
- **Search:** filters as you type over the *full path*. Words can be in any order (`riv res` matches `Riverton/Land use/Residential`). Matches are highlighted and their parents expanded. Matches in the theme's own name rank above matches in folder names only. Prefix `layer:` searches for themes where a matching layer is visible.
- **Keyboard:** ↑/↓ move through results while focus stays in the search box. Enter applies the theme (top match if nothing is selected). Ctrl+Enter applies and keeps the popup open. Esc clears the search first, then closes. F2 renames, Del deletes.
- **Mouse:** a single click applies the theme and closes the popup (like native). A setting can change this to double-click. A middle-click or the pin icon applies without closing, for flipping through themes.
- **Current theme:** marked with ● when the layer tree matches the theme exactly (same comparison native uses). A folder shows a small dot when it contains the current theme.
- **Tooltip:** full name, number of visible layers, list of the first 10 visible layers.
- **Context menu on a theme:** Apply · Replace with current layers · Rename… · Move to folder… · Duplicate · Delete · Copy name.
- **Context menu on a folder:** New theme here (from current layers) · New subfolder · Rename folder… (renames every theme inside) · Move folder… · Delete folder… (confirmation lists how many themes) · Expand/collapse all.

### 5.2 Dock panel "Map Themes"
Same widget, docked (`QgsDockWidget`), opened from View ▸ Panels or the popup's "Open panel" button. Adds:
- multi-select (Shift/Ctrl) for batch move and delete
- drag and drop of themes and folders between folders (each drop becomes a series of renames, undone as one step)
- stays open while you work

### 5.3 Locator filter
In the Ctrl+K Locator bar, prefix `th` (configurable) lists matching themes. Enter applies one. Gives keyboard-only theme switching without touching the layer panel.

### 5.4 Dialogs
- **Add / Duplicate theme:** name field plus a folder combo with autocomplete over existing folders. The folder is pre-filled from the current selection. You can also type a full path straight into the name field. Validation shows inline.
- **Rename / Move:** a single path field, pre-filled. Folder rename shows a preview ("12 themes will be renamed").
- **Reference audit** (before rename or delete, only when needed): lists layouts, map views and data-defined expressions that reference the theme. Each one says whether core updates it automatically or you need to fix it.

### 5.5 Undo
Every destructive or batch action (delete, rename, move, folder ops) shows a QGIS message-bar notice ("Deleted 5 themes — **Undo**"). Undo for delete re-inserts the saved `MapThemeRecord`s; undo for rename/move renames back. There is a session-level stack of the last 20 operations.

### 5.6 Settings
Global (QgsSettings): click-to-apply vs double-click, folders first, hide numeric prefixes, right-click opens classic menu, Locator prefix.
Per project (custom properties): separator, spaced separators, folders turned off.

---

## 6. Architecture

```
map_themes_evolved/
├── metadata.txt            # qgisMinimumVersion=3.34, qgisMaximumVersion=4.99, supportsQt6=True
├── __init__.py             # classFactory
├── plugin.py               # lifecycle: initGui/unload, wiring, actions
├── core/
│   ├── paths.py            # pure Python: split/join/validate/natural sort (no QGIS import → fast unit tests)
│   ├── service.py          # ThemeService: wraps QgsMapThemeCollection (apply, add, replace, rename, move,
│   │                       #   duplicate, delete, batch ops, current-theme detection, signals)
│   ├── undo.py             # operation stack with message-bar integration
│   └── references.py       # finds layout / canvas / data-defined references to a theme name
├── ui/
│   ├── model.py            # ThemeTreeModel (QStandardItemModel or custom QAbstractItemModel)
│   ├── filter_proxy.py     # token search, ranking, layer: mode
│   ├── browser_widget.py   # search box + tree + action rows (used by popup AND dock)
│   ├── popup.py            # Qt.Popup frame anchored to the eye button
│   ├── dock.py             # QgsDockWidget host
│   ├── dialogs.py          # add/rename/move/audit dialogs
│   └── settings_page.py    # QgsOptionsWidgetFactory page
├── hook/
│   └── eye_button.py       # find/hook/unhook the Layers-panel button
├── locator.py              # QgsLocatorFilter
├── i18n/                   # .ts/.qm — English + Hungarian
└── test/
```

**Key design decisions**
- **One `ThemeService` and one model per project**, shared by the popup, dock and Locator. The model rebuilds (with a debounce) when collection signals fire, keeping expanded folders and the selection across rebuilds.
- **Current-theme detection** runs only when the popup or dock is shown, or after the layer tree changes (debounced). It compares `createThemeFromCurrentState(root, layerTreeModel)` against each `mapThemeState(name)`.
- **Qt5/Qt6:** import only from `qgis.PyQt`; use fully scoped enums (`Qt.ItemDataRole.UserRole`, `QAbstractItemView.SelectionMode.ExtendedSelection`), which work on both PyQt5 5.15 and PyQt6. Avoid `exec_()`.

### 6.1 Eye-button hook (`hook/eye_button.py`)
1. **Find the button by structure, not text:** a `QToolButton` in the main window whose `menu()` contains `iface.actionShowAllLayers()`. Exactly one match is required. Fallback: the button's menu's `objectName` or tooltip. If nothing is found, log to the message log, skip the hook and keep the dock and Locator.
2. **Hook:** store the original `menu()` and `popupMode()` on the button as dynamic properties (`mte_original_menu`, `mte_hooked`) so a reload never mistakes our state for the original. Then call `setMenu(None)` and `setPopupMode(DelayedPopup)`, connect `clicked` to show the popup, and optionally install an event filter for right-click → `original_menu.exec(globalPos)`.
3. **Native actions:** collect the original menu's own `QAction`s (show/hide set, Add Theme…) and add those same objects to the popup's action row. Let the native menu keep rebuilding its theme list on `aboutToShow` for "Classic menu…".
4. **Unhook:** disconnect, remove the event filter, restore `setMenu(original)` and `setPopupMode(original_mode)`, clear the properties.
5. **Self-check:** a hidden "Diagnostics" item in settings reports QGIS version, whether the hook worked, and which native actions were found.

---

## 7. Roadmap

### Phase 0 — Spike ✅ done on 3.44 · ⏳ still to repeat on 4.x
See §10 for findings. Repeat the same three console scripts on QGIS 4.x (Qt6) before Phase 1 is released. If the hook fails there, 4.x gets the dock + Locator only.

### Phase 1 — MVP (v0.1) ✅ built 2026-11-09, tested live on 3.44.9
Differences from the original MVP list:
- Duplicate and "Move to folder…" moved up from Phase 2. They were cheap to add.
- Expanded folders are remembered in QgsSettings (keyed by project path), not in the project file, so expanding a folder never marks the project as changed.
- Ranked search keeps the tree layout, all expanded; the best match is preselected so Enter applies it. Highlighting matched text is left for Phase 3.
- A setting for single- vs double-click to apply is still missing; single click applies for now.

Original MVP list:
- `paths.py` with full unit tests (separator, trimming, validation, natural sort)
- `ThemeService`: apply, add, replace, rename, delete, current-theme detection, live sync
- tree model + search proxy (token search, highlight, auto-expand)
- eye-button popup with keyboard navigation and reused native actions
- context menus for themes and folders (including folder rename and delete)
- add/rename dialogs with folder autocomplete and inline validation
- undo via the message bar
- clean unload and reload

### Usability rework (released as v0.2.0, 2026-11-09)
Feedback from using the MVP: clicking applies a theme and closes the popup, so the buttons that acted on "the selected theme" couldn't really be used with a mouse, and dialogs made the popup flicker. Changes:
- The **status line** shows the active theme, or "Layers changed since X" with **Update** / **Save as new…**.
- **Inline editing** for new theme, new folder and rename. The rename dialog is gone; only "Move to ▸ New folder…" still uses a dialog.
- Per-row **right-click menu** with a **Move to ▸** folder submenu. The selection-based toolbar is gone.
- **Drag and drop** themes and folders into folders, as one undoable step.
- **Dock panel** ("Open as panel"), pulled forward from Phase 2.
- **Custom icons** for theme-specific actions, generated as one consistent sheet (`assets/icon_sheet.png`). Native QGIS icons are kept wherever the function is identical.
- Fixed a crash when loading another project (the old theme collection had already been deleted).

### Phase 2 — Power features (v0.3)
Dock panel and drag and drop are done (see above). Still open:
- dock panel with multi-select and drag and drop
- Locator filter
- `layer:` search mode and layer-list tooltips
- reference audit before rename or delete (data-defined overrides, other map views)
- settings page (global and per-project)
- "Move to folder…" and "Duplicate"

### Phase 3 — Polish and release (v0.3 → 1.0)
- **"Organise existing themes" wizard:** turn existing naming into folders, with a preview table of old → new names, applied as one undoable rename batch. Real projects already group with ` - ` (`Vizsgálat - Telekméretek`, `Tervezési terület - Lakeside`) while codes contain a bare `-` (`MTrT-1`, `OTrT-10`). So the wizard must split only on the *spaced* form ` - `. It should also offer "group by common prefix" (`MTrT-*` → `MTrT/…`, `2025 *` → `2025/…`). Move this wizard to **v0.2**: it's the fastest way to get value from an existing project.
- hide numeric prefixes and folders-first options
- Hungarian translation, docs, screenshots, GIF
- publish to plugins.qgis.org (flag Qt6 support)

---

## 8. Testing

- **Unit tests (no QGIS):** `paths.py` — parsing, round-trips, validation, sorting, edge cases (`A//B`, `/A`, `A/`, unicode `Árvízvédelem`, case clashes).
- **Integration tests (`qgis.testing`):** the service against a real project: add, rename and move keep records identical; layout maps follow renames; undo restores records byte-for-byte; signals refresh the model.
- **CI matrix:** Docker images `qgis/qgis:3.44` (Qt5) and `qgis/qgis:latest` (Qt6) via GitHub Actions.
- **Manual checklist per release:**
  - open a project with 300+ themes (popup opens in < 150 ms)
  - change themes with the native menu while the popup is closed → the plugin reflects them
  - disable the plugin → the native eye menu is back and works
  - save, then reopen without the plugin → nothing changed except custom properties
  - check every native action from both the popup and the classic menu

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| A QGIS update changes the eye-button internals | Structural detection, graceful fallback to dock + Locator, diagnostics, CI on the latest QGIS |
| Users already use `/` literally in names | Per-project separator setting or folders turned off; the wizard previews before changing anything |
| Data-defined theme expressions break on rename | Reference audit warns before the rename and lists exact locations |
| Batch rename collides with existing names | Pre-validate the whole batch; apply all or nothing; one undo step |
| Large projects get slow | Debounced rebuilds; current-theme check only when visible; lazy tooltips |
| Plugin crash takes QGIS UI down with it | All hook code wrapped in try/except with a log message; unhook always runs |

---

## 10. Phase 0 findings — QGIS 3.44.9 (Qt 5.15.13, PyQt 5.15.11), 2026-11-09

Checked live in QGIS through MCP. Rename tests ran in a separate in-memory `QgsProject()`; the open project was not modified. The eye button was hooked and restored straight away.

**Eye button**
- Detection by structure (`menu()` contains `iface.actionShowAllLayers()`) finds **exactly one** button: tooltip "Manage Map Themes", no `objectName`, popup mode `InstantPopup` (2). It sits in the toolbar of the `Layers` dock (`QgsDockWidget 'Layers'`).
- Hook works: `setMenu(None)` + `DelayedPopup` + `clicked` reaches the plugin. Restore gives back the **same** menu object, mode 2, and an unchanged action count (81).
- The native menu's `aboutToShow` rebuild only replaces its own theme actions. A foreign action inserted into the menu survives.

**Native menu layout (order)**
1. 7 layer-visibility actions with stable `objectName`s that can be reused directly: `mActionShowAllLayers`, `mActionHideAllLayers`, `mActionShowSelectedLayers`, `mActionHideSelectedLayers`, `mActionToggleSelectedLayers`, `mActionToggleSelectedLayersIndependently`, `mActionHideDeselectedLayers`
2. separator · `Replace Theme` (submenu) · `Rename Current Theme…` · `Add Theme…`. These have **no** `objectName`, and their text is translated. The plugin re-implements them through the API instead of looking them up.
3. one checkable action per theme (flat) · separator · `Remove Current Theme`

**Theme collection API**
- Names with `/` are accepted and listed as-is.
- `MapThemeRecord ==` works from Python, so current-theme detection via `createThemeFromCurrentState(root, model)` is reliable.
- `renameMapTheme()` keeps the record unchanged and emits `mapThemeRenamed(old, new)`. It **refuses to overwrite** an existing name (returns `False`). It emits `mapThemesChanged` **twice**, so model rebuilds must be debounced.
- Layout map items following a theme are **updated automatically** on rename (`currentMapThemeRenamed` slot). `QgsMapCanvas` has a matching `mapThemeRenamed` slot as well.
- Data-defined overrides (`QgsLayoutObject.MapStylePreset` expressions) are **not** updated: `'Grp/ThemeA'` stayed stale after the rename. That confirms the reference audit is needed.

**From a real production project (68 themes)**
Everything is flat today. Names already form groups using ` - ` and shared prefixes (`MTrT-…` 21×, `OTrT-…` 12×, `Vizsgálat - …` 7×, `2025 …` 7×). The native code-point sort scatters them, which is good evidence for natural sorting and the organise wizard.
