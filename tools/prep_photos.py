"""Turn your own produce photos into web-ready ones for Soko Digital.

1. Put photos in a folder, named after the produce: potatoes.jpg, maize.jpg, tomatoes.jpg, kale.jpg,
   onions.jpg, beans.jpg, bananas.jpg, avocados.jpg   (singular names like tomato.jpg also work;
   .jpg .jpeg .png .webp are fine)
2. Run:   python tools/prep_photos.py path/to/your/folder
3. Resized, centre-cropped (4:3, 900x675) copies are written to static/images/produce/ and show up
   on the site automatically. Produce without a photo keeps its illustration.
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

OUT = Path(__file__).resolve().parent.parent / "static" / "images" / "produce"
SLUGS = {"potatoes", "maize", "tomatoes", "kale", "onions", "beans", "bananas", "avocados"}
# singular / alternative file names are accepted too
ALIASES = {"potato": "potatoes", "tomato": "tomatoes", "onion": "onions", "bean": "beans", "banana": "bananas",
           "avocado": "avocados", "corn": "maize", "sukuma": "kale", "sukuma-wiki": "kale"}
# Optional: where the subject sits, as (x, y, fraction_of_width_to_keep). Use for photos where the produce is
# small or off-centre (e.g. a single cob in a whole maize plant). Anything not listed is centre-cropped.
FOCUS = {"maize": (0.45, 0.53, 0.65)}
W, H = 900, 675


def main(folder):
    src = Path(folder)
    if not src.is_dir():
        sys.exit(f"Folder not found: {src}")
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    for f in sorted(src.iterdir()):
        slug = ALIASES.get(f.stem.lower(), f.stem.lower())
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} or slug not in SLUGS:
            continue
        img = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        if slug in FOCUS:
            cx, cy, frac = FOCUS[slug]
            cw = min(img.width * frac, img.height / (H / W))
            ch = cw * H / W
            x0 = min(max(cx * img.width - cw / 2, 0), img.width - cw)
            y0 = min(max(cy * img.height - ch / 2, 0), img.height - ch)
            img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
        img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
        target = OUT / f"{slug}.jpg"
        img.save(target, "JPEG", quality=82, optimize=True, progressive=True)
        done.append(f"{target.name} ({target.stat().st_size // 1024} KB)")
    print("Prepared:", ", ".join(done) if done else "nothing. Check the file names match the produce names.")
    missing = sorted(s for s in SLUGS if not (OUT / f"{s}.jpg").exists())
    if missing:
        print("Still using illustrations for:", ", ".join(missing))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
