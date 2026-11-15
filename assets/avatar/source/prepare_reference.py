"""Prepare the turnaround sheet for projection onto the generated body.

Usage:  python prepare_reference.py <turnaround.png> [out_dir]     (needs Pillow + numpy)

1. Crops the four views (front, 3/4, side, back) from a 1536x1024 turnaround sheet.
2. Fills the grey studio background with the nearest character colours, so the
   projection never paints background grey onto the skin at the silhouette edge.
3. Replaces the eyepatch over the character's right eye with his mirrored left eye
   (the sheet's "glasses" are an eyepatch; build_realistic adds real glasses).

Writes front/three_quarter/side/back.png (Hunyuan input) and proj_*.png (projection).
The pixel landmarks used by build_realistic.REF were measured on these crops.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

BOXES = {
    "front": (20, 0, 450, 960),
    "three_quarter": (470, 0, 820, 960),
    "side": (840, 0, 1140, 960),
    "back": (1160, 0, 1520, 960),
}
FACE_CENTRE_X = 219.0  # front crop, nose bridge
# (x0, x1, y0, y1, source column shift or None = mirror about FACE_CENTRE_X, feather px)
EYEPATCH_FIXES = [
    (172, 218, 76, 122, None, 6.0),
    (203, 219, 68, 96, None, 4.0),
    (210, 221, 84, 104, 9, 3.0),
]


def fill_background(rgb: np.ndarray, iterations: int = 60) -> np.ndarray:
    bg = np.median(
        np.concatenate(
            [
                rgb[:15].reshape(-1, 3),
                rgb[:, :8].reshape(-1, 3),
                rgb[:, -8:].reshape(-1, 3),
            ]
        ),
        axis=0,
    )
    mask = np.abs(rgb - bg).sum(axis=2) > 38
    mask = (
        np.asarray(
            Image.fromarray((mask * 255).astype(np.uint8)).filter(
                ImageFilter.MedianFilter(5)
            )
        )
        > 128
    )
    col, known = rgb.copy(), mask.copy()
    for _ in range(iterations):
        if known.all():
            break
        acc, cnt = np.zeros_like(col), np.zeros(known.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(col, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        new = (~known) & (cnt > 0)
        col[new] = acc[new] / cnt[new][:, None]
        known |= new
    return col


def fix_eyepatch(a: np.ndarray) -> np.ndarray:
    for x0, x1, y0, y1, shift, feather in EYEPATCH_FIXES:
        yy, xx = np.mgrid[y0:y1, x0:x1]
        src_x = (2 * FACE_CENTRE_X - xx).astype(int) if shift is None else xx + shift
        patch = a[yy, src_x].copy()
        d = np.minimum.reduce([xx - x0, x1 - 1 - xx, yy - y0, y1 - 1 - yy]).astype(
            np.float32
        )
        w = np.clip((d + 1) / feather, 0, 1)[..., None]
        a[y0:y1, x0:x1] = patch * w + a[y0:y1, x0:x1] * (1 - w)
    return a


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sheet = Image.open(sys.argv[1]).convert("RGB")
    out = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path(__file__).resolve().parent / "_reference"
    )
    out.mkdir(parents=True, exist_ok=True)
    for name, box in BOXES.items():
        crop = sheet.crop(box)
        crop.save(out / f"{name}.png")
        filled = fill_background(np.asarray(crop).astype(np.float32))
        if name == "front":
            filled = fix_eyepatch(filled)
        Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8)).save(
            out / f"proj_{name}.png"
        )
        print("wrote", out / f"proj_{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
