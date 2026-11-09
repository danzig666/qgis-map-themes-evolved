"""Compose README screenshots: popup + open menus, with soft shadows."""
import pathlib
import sys

from PIL import Image, ImageFilter

base = pathlib.Path(sys.argv[1])
raw = base / "raw"
DPR = 1.75
PAD = 28


def shadowed(layers, size):
    """layers: list of (image, (x, y)) in canvas px; returns RGBA canvas with shadows."""
    w, h = size
    canvas = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    for img, (x, y) in layers:
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        box = Image.new("RGBA", img.size, (0, 0, 0, 70))
        shadow.paste(box, (x + PAD + 4, y + PAD + 6))
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        canvas = Image.alpha_composite(canvas, shadow)
        canvas.alpha_composite(img.convert("RGBA"), (x + PAD, y + PAD))
    return canvas


def save(img, name, max_width=900):
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    img.save(base / name, optimize=True)
    print(name, img.size)


def single(src, name):
    p = Image.open(raw / src)
    save(shadowed([(p, (0, 0))], p.size), name)


single("01_overview.png", "overview.png")
single("02b_search.png", "search.png")
single("05b_group_typing.png", "group.png")

# history menu dropping from the undo button
pop = Image.open(raw / "03_changed.png")
hm = Image.open(raw / "03_history_menu.png")
ax, ay = round(356 * DPR), round(78 * DPR)
mx = min(ax, pop.width - hm.width // 2)
w = max(pop.width, mx + hm.width)
save(shadowed([(pop, (0, 0)), (hm, (mx, ay))], (w, max(pop.height, ay + hm.height))), "history.png")

# right-click menu with Move to submenu
pop = Image.open(raw / "04_context_menu.png")
menu = Image.open(raw / "04_menu.png")
sub = Image.open(raw / "04_submenu.png")
mx, my = round(234 * DPR), round(130 * DPR)
sx, sy = mx + menu.width - round(4 * DPR), my + round(90 * DPR) - round(4 * DPR)
w = max(pop.width, sx + sub.width)
h = max(pop.height, my + menu.height, sy + sub.height)
save(shadowed([(pop, (0, 0)), (menu, (mx, my)), (sub, (sx, sy))], (w, h)), "context-menu.png")
