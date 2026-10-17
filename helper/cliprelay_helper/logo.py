"""The ClipRelay mark (the website's logo: a white play sign on a violet tile), drawn for the tray and the program icon."""

from PIL import Image, ImageDraw

TOP, BOTTOM = (139, 124, 247), (91, 75, 217)  # the website's brand-mark gradient (#8b7cf7 → #5b4bd9)
DOTS = {"ok": (34, 197, 94), "work": (255, 255, 255), "warn": (245, 158, 11), "bad": (239, 68, 68)}

# The same mark as SVG, for the helper's window (tab icon and header).
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
       '<stop offset="0" stop-color="#8b7cf7"/><stop offset="1" stop-color="#5b4bd9"/></linearGradient></defs>'
       '<rect width="64" height="64" rx="18" fill="url(#g)"/><path d="M25 19l20 13-20 13z" fill="#fff"/></svg>')


def mark(size: int = 256, dot: str | None = None) -> Image.Image:
    scale = 4  # drawn large and shrunk, for smooth edges
    big = size * scale
    small = Image.new("RGBA", (64, 64))
    pixels = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            pixels[x, y] = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
    gradient = small.resize((big, big), Image.BILINEAR)  # a smooth diagonal blend, made quickly
    tile = Image.new("L", (big, big), 0)
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.28), fill=255)
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    image.paste(gradient, (0, 0), tile)
    draw = ImageDraw.Draw(image)
    u = big / 64
    draw.polygon([(25 * u, 19 * u), (45 * u, 32 * u), (25 * u, 45 * u)], fill="white")
    if dot:
        r = big * 0.15
        cx, cy = big - r - big * 0.02, big - r - big * 0.02
        draw.ellipse((cx - r - big * 0.04, cy - r - big * 0.04, cx + r + big * 0.04, cy + r + big * 0.04), fill=(17, 20, 27, 255))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=DOTS[dot] + (255,))
    return image.resize((size, size), Image.LANCZOS)


def save_icons(folder: str) -> tuple[str, str]:
    """icon.ico (Windows) and icon.png (Mac; PyInstaller turns it into .icns) for the built program."""
    import os

    big = mark(512)
    ico, png = os.path.join(folder, "icon.ico"), os.path.join(folder, "icon.png")
    big.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(png)
    return ico, png
