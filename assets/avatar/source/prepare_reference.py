"""Prepare the turnaround sheet for projection onto the generated body.

Usage:  python prepare_reference.py <turnaround.png> [out_dir]     (needs Pillow + numpy)

1. Crops the four views (front, 3/4, side, back) from a 1536x1024 turnaround sheet.
2. Fills the grey studio background with the nearest character colours, so the
   projection never paints background grey onto the skin at the silhouette edge.
3. Replaces the eyepatch over the character's right eye with his mirrored left eye
   (the sheet's "glasses" are an eyepatch; build_realistic adds real glasses).

Writes front/three_quarter/side/back.png (Hunyuan input), proj_*.png (projection,
background filled with the nearest body colour) and mask_*.png (silhouettes:
build_realistic only lets a view paint where that view actually sees the body).
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


def body_mask(rgb: np.ndarray, sole_row: int = 957) -> np.ndarray:
    """Silhouette of the character: largest piece, holes filled, no floor shadow."""
    from scipy import ndimage

    edges = [
        rgb[:15].reshape(-1, 3),
        rgb[:, :8].reshape(-1, 3),
        rgb[:, -8:].reshape(-1, 3),
    ]
    bg = np.median(np.concatenate(edges), axis=0)
    mask = np.abs(rgb - bg).sum(axis=2) > 38
    mask = (
        np.asarray(
            Image.fromarray((mask * 255).astype(np.uint8)).filter(
                ImageFilter.MedianFilter(5)
            )
        )
        > 128
    )
    # feet zone: the floor shadow is grey, the feet are warm skin
    feet = np.zeros_like(mask)
    feet[int(sole_row * 0.93) :] = True
    warm = (rgb[..., 0] - rgb[..., 2]) > 15
    mask &= ~feet | warm
    mask[sole_row + 2 :] = False
    labels, n = ndimage.label(mask)
    if n:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        mask = labels == (int(np.argmax(sizes)) + 1)
    mask = ndimage.binary_fill_holes(mask)
    return ndimage.binary_erosion(mask, iterations=2)


def fill_outside(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Every pixel outside the mask takes the colour of the nearest body pixel."""
    from scipy import ndimage

    _d, (iy, ix) = ndimage.distance_transform_edt(~mask, return_indices=True)
    return rgb[iy, ix]


def fill_background(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = body_mask(rgb)
    return fill_outside(rgb, mask), mask


# the side view also shows the eyepatch (over the eye, towards the temple)
SIDE_PATCH = (170, 207, 88, 119)  # x0, x1, y0, y1 in side.png


def fix_side_eyepatch(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    x0, x1, y0, y1 = SIDE_PATCH
    known = mask.copy()
    known[y0:y1, x0:x1] = False
    filled = fill_outside(rgb, known)
    out = rgb.copy()
    out[y0:y1, x0:x1] = filled[y0:y1, x0:x1]
    soft = Image.fromarray(out.astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))
    out[y0:y1, x0:x1] = np.asarray(soft).astype(np.float32)[y0:y1, x0:x1]
    return out


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
        filled, mask = fill_background(np.asarray(crop).astype(np.float32))
        if name == "front":
            filled = fix_eyepatch(filled)
        if name == "side":
            filled = fix_side_eyepatch(filled, mask)
        Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8)).save(
            out / f"proj_{name}.png"
        )
        Image.fromarray((mask * 255).astype(np.uint8)).save(out / f"mask_{name}.png")
        print("wrote", out / f"proj_{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
