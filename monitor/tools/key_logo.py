"""Cut a logo out of a baked-in checkerboard "transparency" background.

    pip install numpy scipy pillow
    python monitor/tools/key_logo.py source.png monitor/assets/logo.png preview.png

Not needed when the logo is already a transparent PNG: just replace monitor/assets/logo.png.

Foreground = the logo's own body: dark or gold pixels, grown by a few pixels for the
anti-aliased edge, with enclosed interiors filled (metallic shading inside letters) but
not regions that look like checkerboard (letter counters). Everything else, including
the drop shadow that darkened the checkerboard around the letters, is transparent.
"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

src, dst, preview = sys.argv[1:4]
im = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
H, W, _ = im.shape
gray = im.mean(axis=2)
chroma = im.max(axis=2) - im.min(axis=2)
top = gray[:12]
light = float(np.median(top[top > 160])); dark = float(np.median(top[top <= 160]))
dist = np.minimum(np.abs(gray - light), np.abs(gray - dark))
strict = (dist < 8) & (chroma < 12)
frac = ndimage.uniform_filter(strict.astype(np.float32), size=11)
checker_like = (frac > 0.4) & (chroma < 22)

core = (gray < 75) | (chroma >= 18)                      # black body and gold edges
core = ndimage.binary_opening(core, iterations=1)         # drop single-pixel noise
grown = ndimage.binary_dilation(core, iterations=3)
fg = (ndimage.binary_fill_holes(grown) | grown) & ~checker_like
lab, n = ndimage.label(fg)
sz = ndimage.sum(fg, lab, index=np.arange(1, n + 1))
fg &= np.isin(lab, np.flatnonzero(sz >= 300) + 1)        # keep only the lettering, not specks
ring = ndimage.binary_dilation(fg, iterations=1) & ~fg
alpha = np.where(fg, 1.0, 0.0).astype(np.float32)
alpha[ring] = 0.45
print(f"foreground {fg.mean()*100:.1f}% of pixels, {int((sz >= 300).sum())} pieces")
rgba = np.dstack([im.astype(np.uint8), (alpha * 255).round().astype(np.uint8)])
ys, xs = np.nonzero(alpha > 0.1)
y0, y1, x0, x1 = max(ys.min() - 6, 0), min(ys.max() + 7, H), max(xs.min() - 6, 0), min(xs.max() + 7, W)
out = Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")
out.save(dst, optimize=True)
print(f"saved {dst}: {out.size} (cropped from {W}x{H})")
bar = (0x17, 0x1a, 0x21)
canvas = Image.new("RGB", (900, 150), bar)
for h, y in ((34, 10), (68, 60)):
    s = out.resize((round(out.width * h / out.height), h), Image.LANCZOS)
    canvas.paste(s, (12, y), s)
canvas.save(preview)
full = Image.new("RGB", out.size, bar); full.paste(out, (0, 0), out)
full.resize((out.width // 2, out.height // 2), Image.LANCZOS).save(preview.replace('.png', '-full.png'))
