"""Makes the app and addon icons from assets/gm_source.jpg (the Canva design).
Needs Pillow: python -m pip install --user pillow
Writes assets/gm.ico (app, exe, tray), assets/gm.png and GuildMilestones/Media/icon.tga (in game)."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    src = Image.open(ROOT / "assets" / "gm_source.jpg").convert("RGBA")
    side = min(src.size)                                     # square crop from the centre
    left, top = (src.width - side) // 2, (src.height - side) // 2
    big = src.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
    big.save(ROOT / "assets" / "gm.png")
    big.save(ROOT / "assets" / "gm.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    media = ROOT / "GuildMilestones" / "Media"
    media.mkdir(exist_ok=True)
    big.resize((64, 64), Image.LANCZOS).save(media / "icon.tga")
    print("icons written")
