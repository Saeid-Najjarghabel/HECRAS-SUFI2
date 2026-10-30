"""Prepare installer artwork. If sufi2_gui/resources/uwl_logo.png exists, the installer
wizard images are generated from it; otherwise the app icon is used."""
import os
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(ROOT, "sufi2_gui", "resources")
OUT = os.path.join(ROOT, "packaging", "build_assets")
os.makedirs(OUT, exist_ok=True)

src = next((os.path.join(RES, n) for n in ("uwl_logo.png", "uwl_logo.jpg", "logo.png")
            if os.path.exists(os.path.join(RES, n))), os.path.join(RES, "app_icon.png"))
logo = Image.open(src).convert("RGBA")
print("Using artwork:", src)


def fit(img, w, h, pad=0.1, bg=(255, 255, 255)):
    canvas = Image.new("RGB", (w, h), bg)
    im = img.copy(); im.thumbnail((int(w * (1 - 2 * pad)), int(h * (1 - 2 * pad))), Image.LANCZOS)
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
    return canvas


# Inno Setup: small image (top-right of wizard pages) and large image (welcome page)
for scale, suffix in ((1, ""), (2, "@2x")):
    fit(logo, 55 * scale, 58 * scale, 0.06).save(os.path.join(OUT, f"wizard_small{suffix}.bmp"))
    large = Image.new("RGB", (164 * scale, 314 * scale), (19, 41, 75))
    panel = fit(logo, 144 * scale, 120 * scale, 0.08)
    large.paste(panel, (10 * scale, 40 * scale))
    large.save(os.path.join(OUT, f"wizard_large{suffix}.bmp"))
print("Wizard images written to", OUT)
