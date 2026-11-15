"""Sharpen the front reference for projection: CodeFormer face restore + upscale.

Usage:  uv run --no-project --with gradio_client --with pillow python enhance_reference.py

The sheet's face is ~70 px wide, which made the avatar's face soft. CodeFormer
(sczhou/CodeFormer on Hugging Face, free) restores faces from low-res input;
fidelity 0.7 keeps the identity close to the reference.

Writes _reference/proj_front_hd.png at 4x (1720x3840): the whole view enhanced
2x then resized, with the head region restored at 4x pasted in. Same framing as
proj_front.png, so build_realistic picks it up automatically (it prefers *_hd.png).
Sends the front view to Hugging Face.
"""

from pathlib import Path

from gradio_client import Client, handle_file
from PIL import Image, ImageFilter

REF = Path(__file__).resolve().parent / "_reference"
HEAD_BOX = (140, 15, 300, 205)  # x0, y0, x1, y1 in proj_front.png
SCALE = 4


def restore(client, path, upscale, fidelity):
    out, _msg = client.predict(
        image=handle_file(str(path)),
        face_align=True,
        background_enhance=True,
        face_upsample=True,
        upscale=upscale,
        codeformer_fidelity=fidelity,
        api_name="/inference",
    )
    if isinstance(out, dict):
        out = out.get("path") or out.get("value")
    return Image.open(out).convert("RGB")


def main() -> int:
    client = Client("sczhou/CodeFormer")
    src = Image.open(REF / "proj_front.png").convert("RGB")
    w, h = src.size
    whole = restore(client, REF / "proj_front.png", 2, 0.7)
    canvas = whole.resize((w * SCALE, h * SCALE), Image.LANCZOS)

    head_path = REF / "_head_crop.png"
    src.crop(HEAD_BOX).save(head_path)
    head = restore(client, head_path, SCALE, 0.7)
    x0, y0, x1, y1 = HEAD_BOX
    head = head.resize(((x1 - x0) * SCALE, (y1 - y0) * SCALE), Image.LANCZOS)
    # feathered paste so the restored head blends into the enhanced body
    f = 6 * SCALE
    mask = Image.new("L", head.size, 0)
    mask.paste(
        Image.new("L", (head.size[0] - 2 * f, head.size[1] - 2 * f), 255), (f, f)
    )
    mask = mask.filter(ImageFilter.GaussianBlur(f / 2))
    canvas.paste(head, (x0 * SCALE, y0 * SCALE), mask)
    canvas.save(REF / "proj_front_hd.png")
    print("saved", REF / "proj_front_hd.png", canvas.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
