"""Draws the Padsight app icon (VSCView/padsight.ico): a controller pill with two sticks, cyan on navy.

Original artwork, drawn here so the repo needs no external assets. Usage: python gen_app_icon.py
"""
import os
from PIL import Image, ImageDraw

NAVY = (7, 11, 22, 255)
CYAN = (58, 214, 255, 255)
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(size):
    ss = 8 if size <= 64 else 4  # supersample, then downscale for clean edges
    s = size * ss
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 28.0  # the logo is designed on a 28x28 grid (same as the panel's SVG)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=6 * u, fill=NAVY)
    stroke = max(2.0, 2.2 * u)
    d.rounded_rectangle([2 * u, 7 * u, 26 * u, 21 * u], radius=7 * u, outline=CYAN, width=round(stroke))
    r = 2.9 * u
    d.ellipse([9 * u - r, 14 * u - r, 9 * u + r, 14 * u + r], fill=CYAN)
    d.ellipse([19 * u - r, 14 * u - r, 19 * u + r, 14 * u + r], outline=CYAN, width=round(max(1.5, 1.7 * u)))
    return img.resize((size, size), Image.LANCZOS)


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'VSCView'))
    images = [draw(n) for n in SIZES]
    out = os.path.join(root, 'padsight.ico')
    images[-1].save(out, format='ICO', sizes=[(n, n) for n in SIZES], append_images=images[:-1])
    print('wrote', out)


if __name__ == '__main__':
    main()
