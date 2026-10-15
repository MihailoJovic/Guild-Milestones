"""Draws the temporary GM icon (until the Canva one is ready). Needs Pillow: python -m pip install --user pillow
Writes assets/gm.ico (app, exe, tray), assets/gm.png and GuildMilestones/Media/icon.tga (in game)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GOLD, GOLD_DARK, BG, BG2 = (242, 184, 75), (150, 104, 30), (14, 16, 21), (31, 35, 48)


def font(size):
    for name in ("georgiab.ttf", "timesbd.ttf", "seguisb.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw(size=512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 6
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=BG)
    m = size // 22                                             # double gold frame, like a WoW plate
    d.rounded_rectangle((m, m, size - 1 - m, size - 1 - m), radius=r - m, outline=GOLD, width=max(2, size // 40))
    m2 = m + size // 18
    d.rounded_rectangle((m2, m2, size - 1 - m2, size - 1 - m2), radius=max(2, r - m2), outline=GOLD_DARK, width=max(1, size // 120))
    c = size // 2                                              # small diamond on top, a crest touch
    k = size // 16
    d.polygon([(c, m - k // 2), (c + k, m + k // 2), (c, m + k + k // 2), (c - k, m + k // 2)], fill=GOLD)
    f = font(int(size * 0.42))
    box = d.textbbox((0, 0), "GM", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    pos = ((size - w) // 2 - box[0], (size - h) // 2 - box[1] + size // 40)
    d.text((pos[0] + size // 120, pos[1] + size // 120), "GM", font=f, fill=GOLD_DARK)
    d.text(pos, "GM", font=f, fill=GOLD)
    return img


if __name__ == "__main__":
    big = draw(512)
    (ROOT / "assets").mkdir(exist_ok=True)
    big.save(ROOT / "assets" / "gm.png")
    big.save(ROOT / "assets" / "gm.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    media = ROOT / "GuildMilestones" / "Media"
    media.mkdir(exist_ok=True)
    big.resize((64, 64), Image.LANCZOS).save(media / "icon.tga")
    print("icons written")
