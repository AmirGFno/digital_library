"""Generate the application icon (PNG + multi-size ICO)."""
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Rounded app tile with a subtle vertical gradient.
tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
tdraw = ImageDraw.Draw(tile)
top = (32, 35, 43)
bottom = (16, 18, 22)
for y in range(S):
    t = y / S
    colour = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    tdraw.line([(0, y), (S, y)], fill=colour)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([16, 16, S - 16, S - 16], radius=190, fill=255)
img.paste(tile, (0, 0), mask)

# Inner border
draw.rounded_rectangle(
    [34, 34, S - 34, S - 34], radius=176, outline=(58, 64, 75, 255), width=6
)


def cover(size, radius, colour, angle):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=colour)
    # page edge highlight
    d.rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius,
        outline=(255, 255, 255, 60), width=6,
    )
    return layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)


# Back covers (purple, teal) peeking out
purple = cover(560, 60, (124, 77, 255, 255), 14)
teal = cover(560, 60, (47, 168, 160, 255), -10)
img.alpha_composite(purple, (150, 190))
img.alpha_composite(teal, (300, 170))

# Front cover (comic orange)
front = cover(600, 62, (232, 85, 45, 255), -3)
img.alpha_composite(front, (210, 250))

# Comic starburst + title lines on the front cover
star_layer = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
sd = ImageDraw.Draw(star_layer)
cx, cy = 300, 260
import math
points = []
for i in range(16):
    radius = 150 if i % 2 == 0 else 62
    angle = math.pi * 2 * i / 16 - math.pi / 2
    points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
sd.polygon(points, fill=(255, 255, 255, 235))

# small inner star cut-out effect
inner = []
for i in range(10):
    radius = 66 if i % 2 == 0 else 28
    angle = math.pi * 2 * i / 10 - math.pi / 2
    inner.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
sd.polygon(inner, fill=(232, 85, 45, 255))

# title bars
for i, width in enumerate((300, 240)):
    y = 430 + i * 46
    sd.rounded_rectangle([150, y, 150 + width, y + 24], radius=12, fill=(255, 255, 255, 220))

star_rotated = star_layer.rotate(-3, resample=Image.Resampling.BICUBIC, center=(300, 300))
img.alpha_composite(star_rotated, (210, 250))

# A soft outer glow/shadow
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    [60, 80, S - 60, S - 40], radius=150, fill=(0, 0, 0, 140)
)
shadow = shadow.filter(ImageFilter.GaussianBlur(30))
base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
base.alpha_composite(shadow)
base.alpha_composite(img)

out = Path(__file__).resolve().parents[1] / "assets"
out.mkdir(parents=True, exist_ok=True)
icon512 = base.resize((512, 512), Image.Resampling.LANCZOS)
icon512.save(out / "icon.png")

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
base.resize((256, 256), Image.Resampling.LANCZOS).save(
    out / "icon.ico", format="ICO", sizes=sizes
)
print("icon written")
