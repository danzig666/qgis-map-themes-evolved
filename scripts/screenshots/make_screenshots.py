"""Render README screenshots of the plugin UI from a fake, in-memory demo project.

Run inside QGIS (Python console):

    MTE_ROOT = r"<path to repository>"
    exec(open(MTE_ROOT + r"/scripts/screenshots/make_screenshots.py", encoding="utf-8").read())

then, outside QGIS:  python scripts/screenshots/compose_shots.py docs/screenshots

Runs inside QGIS. Nothing touches the user's open project: the
demo uses its own QgsProject, the popup is rendered off-screen, notices are
silenced and no settings are written.
"""
import os
import sys
import time

from qgis.PyQt.QtCore import QCoreApplication, QItemSelectionModel, QPoint, Qt
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QAbstractItemView, QApplication, QLineEdit
from qgis.core import QgsLayerTreeModel, QgsProject, QgsVectorLayer

# repository root: set MTE_ROOT before exec(), or run from the repository root
ROOT = globals().get("MTE_ROOT") or os.getcwd()
OUT = os.path.join(ROOT, "docs", "screenshots", "raw")
os.makedirs(OUT, exist_ok=True)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from map_themes_evolved.core.history import VisibilityHistory  # noqa: E402
from map_themes_evolved.core.service import ThemeService  # noqa: E402
from map_themes_evolved.core.undo import UndoStack  # noqa: E402
from map_themes_evolved.ui.common import Notifier  # noqa: E402
from map_themes_evolved.ui.model import folder_to_key  # noqa: E402
from map_themes_evolved.ui.popup import ThemePopup  # noqa: E402


def wait(ms=150):
    t = time.time()
    while time.time() - t < ms / 1000:
        QCoreApplication.processEvents()


class QuietNotifier(Notifier):
    def done(self, text, op_id=None):
        self._notify_listeners()

    def error(self, text):
        print("   (notice)", text)

    def info(self, text):
        pass


# ---------------------------------------------------------------- demo project
project = QgsProject()
root = project.layerTreeRoot()
GROUPS = {
    "Base map": ["Orthophoto 2025", "Contours", "Parcels", "Buildings"],
    "Transport": ["Roads", "Railways", "Bus stops"],
    "Water": ["Rivers", "Lakes", "Flood zones"],
    "Planning": ["Land use", "Zoning plan", "Protected areas", "Water pipes", "Power lines"],
}
layers = {}
for group_name, names in GROUPS.items():
    g = root.addGroup(group_name)
    for n in names:
        lyr = QgsVectorLayer("Point?crs=EPSG:3857", n, "memory")
        project.addMapLayer(lyr, False)
        g.addLayer(lyr)
        layers[n] = lyr
tree_model = QgsLayerTreeModel(root)


def show_only(*names):
    for n, lyr in layers.items():
        root.findLayer(lyr.id()).setItemVisibilityChecked(n in names)


svc = ThemeService(project, lambda: tree_model)
THEMES = {
    "Riverton/Land use/Residential": ("Buildings", "Parcels", "Land use", "Roads"),
    "Riverton/Land use/Industrial": ("Buildings", "Land use", "Railways"),
    "Riverton/Land use/Mixed use": ("Buildings", "Land use", "Roads", "Bus stops"),
    "Riverton/Transport/Road network": ("Roads", "Contours"),
    "Riverton/Transport/Rail and bus": ("Railways", "Bus stops", "Roads"),
    "Riverton/Utilities/Water supply": ("Water pipes", "Rivers", "Parcels"),
    "Riverton/Utilities/Power grid": ("Power lines", "Parcels"),
    "Riverton/Zoning plan 2026": ("Zoning plan", "Parcels", "Roads"),
    "Lakeside/Overview": ("Orthophoto 2025", "Lakes", "Rivers"),
    "Lakeside/Protected areas": ("Protected areas", "Lakes", "Contours"),
    "Lakeside/Flood zones 2025": ("Flood zones", "Rivers", "Lakes", "Buildings"),
    "Base map": ("Orthophoto 2025", "Roads", "Buildings"),
    "Overview 1:50 000": ("Contours", "Roads", "Rivers", "Lakes"),
    "Print – A3 cover": ("Orthophoto 2025", "Land use"),
    "Print – A4 report": ("Zoning plan", "Roads"),
}
for name, vis in THEMES.items():
    show_only(*vis)
    svc.add_from_current(name)

undo = UndoStack()
notifier = QuietNotifier(iface, undo)
history = VisibilityHistory(svc, delay_ms=20)

# ---------------------------------------------------------------- off-screen popup
popup = ThemePopup(svc, undo, notifier, iface, classic_menu=None, history=history)
popup.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
popup._save = lambda: None             # never write the demo geometry to QGIS settings
popup.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
pal = popup.palette()
for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.HighlightedText):
    pal.setColor(QPalette.ColorGroup.Inactive, role, pal.color(QPalette.ColorGroup.Active, role))
popup.setPalette(pal)
popup.resize(430, 480)
popup.move(QApplication.primaryScreen().availableGeometry().topLeft() + QPoint(40, 40))
br = popup.browser
br._save_expanded = lambda: None          # don't write demo state to QGIS settings
br._load_expanded = lambda: None
br._expanded = {folder_to_key(("Riverton",)), folder_to_key(("Riverton", "Land use")),
                folder_to_key(("Lakeside",))}
br.pin_button.blockSignals(True)
br.pin_button.setChecked(False)
br.pin_button.blockSignals(False)


def shot(name, widget=None):
    wait(200)
    pix = (widget or popup).grab()
    path = os.path.join(OUT, name)
    pix.save(path)
    print("saved", os.path.basename(path), pix.width(), "x", pix.height(), "dpr", pix.devicePixelRatio())
    return pix


def key_pos(key):
    item = br.model.items_by_key[key]
    idx = item.index()
    br.tree.scrollTo(idx)
    return br.tree.visualRect(idx).center()


# 1. overview: active theme, folders, status line
svc.apply("Riverton/Land use/Residential")
wait(200)
history.flush()
popup.show()
br.search.blockSignals(True)
br.search.clear()
br.search.blockSignals(False)
br.refresh(select_current=True)
br.tree.scrollToTop()
shot("01_overview.png")

# 2. search, words in any order, accents/case ignored
br.search.setText("flood lake")
wait(200)
shot("02_search.png")
br.search.setText("tra riv")
wait(200)
shot("02b_search.png")
br.search.clear()
wait(100)

# 3. layers changed since a theme -> Update / Save as new + visibility history
for n in ("Orthophoto 2025", "Bus stops"):
    root.findLayer(layers[n].id()).setItemVisibilityChecked(True)
    wait(120)
    history.flush()
root.findLayer(layers["Roads"].id()).setItemVisibilityChecked(False)
wait(120)
history.flush()
br.refresh(select_current=True)
br.tree.scrollToTop()
shot("03_changed.png")
br._fill_history_menu()
hm = br.history_menu
hm.adjustSize()
acts = [a for a in hm.actions() if a.isEnabled() and a.text() and not a.isSeparator()]
if len(acts) > 1:
    hm.setActiveAction(acts[1])
shot("03_history_menu.png", hm)
anchor = br.btn_vis_undo.mapTo(popup, QPoint(0, br.btn_vis_undo.height()))
print("history anchor", anchor.x(), anchor.y())

# 4. right-click menu with "Move to" submenu
svc.apply("Lakeside/Overview")
wait(150)
br.refresh(select_current=True)
pos = key_pos(("theme", "Lakeside/Overview"))
menu = br.build_context_menu(pos)
menu.adjustSize()
move = next(a for a in menu.actions() if a.menu() is not None)
menu.setActiveAction(move)
shot("04_context_menu.png")  # popup with the row selected
shot("04_menu.png", menu)
sub = move.menu()
sub.adjustSize()
target = next((a for a in sub.actions() if a.text() == "Riverton"), None)
if target is not None:
    sub.setActiveAction(target)
shot("04_submenu.png", sub)
print("context anchor", br.tree.viewport().mapTo(popup, pos).x(), br.tree.viewport().mapTo(popup, pos).y())
print("move action rect", menu.actionGeometry(move).getRect())

# 5. multi-select + Group: the new folder is typed in place
sm = br.tree.selectionModel()
sm.clearSelection()
for k in (("theme", "Print – A3 cover"), ("theme", "Print – A4 report")):
    item = br.model.items_by_key[k]
    sm.select(item.index(), QItemSelectionModel.SelectionFlag.Select)
br.tree.setCurrentIndex(br.model.items_by_key[("theme", "Print – A3 cover")].index())
sm.select(br.model.items_by_key[("theme", "Print – A4 report")].index(), QItemSelectionModel.SelectionFlag.Select)
wait(100)
br.tree.scrollToBottom()
shot("05a_multiselect.png")
br.group_selected()
wait(300)
editors = [e for e in br.tree.findChildren(QLineEdit) if e.isVisible()]
if editors:
    editors[0].setText("Print layouts")
    editors[0].setCursorPosition(len("Print layouts"))
br.tree.scrollToBottom()
shot("05b_group_typing.png")
if br.tree.state() == QAbstractItemView.State.EditingState:
    br.cancel_editing()
wait(100)

popup.hide()
popup.deleteLater()
history.shutdown()
svc.shutdown()
print("done")
