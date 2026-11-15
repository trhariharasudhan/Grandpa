"""Shape only: realistic Grandpa geometry from the front reference view.

Usage:  uv run --no-project --with gradio_client python hunyuan_shape.py [seed] [octree] [space]

Set HF_TOKEN (a free Hugging Face token) for more ZeroGPU quota than anonymous use.
Use tencent/Hunyuan3D-2.1: the older tencent/Hunyuan3D-2 at octree 512 fused the
figure with a large background blob in testing.

octree 512 is the space's maximum and gives the head the most triangles (the
figure itself is a small part of the output; most faces are the floor disc).

Uses the public Hugging Face space tencent/Hunyuan3D-2.1 (free ZeroGPU, no key).
Its texture step needs more GPU time than anonymous users get, so only the shape
is generated here; build_realistic.py textures it by projecting the reference.
This is the one step that sends an image (front view) to a cloud service.
Model licence: Tencent Hunyuan 3D 2.1 Community License (see assets/avatar/README.md).
"""

import shutil
import sys
import time
from pathlib import Path

from gradio_client import Client, handle_file

REF = Path(__file__).resolve().parent / "_reference"


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
    octree = int(sys.argv[2]) if len(sys.argv) > 2 else 512
    space = sys.argv[3] if len(sys.argv) > 3 else "tencent/Hunyuan3D-2.1"
    # the 2.1 queue can take minutes to answer; gradio's default read timeout is too short
    client = Client(space, httpx_kwargs={"timeout": 180})
    t0 = time.time()
    out_file, _html, stats, used_seed = client.predict(
        image=handle_file(str(REF / "front.png")),
        mv_image_front=None,
        mv_image_back=None,
        mv_image_left=None,
        mv_image_right=None,
        steps=30,
        guidance_scale=5.0,
        seed=seed,
        octree_resolution=octree,
        check_box_rembg=True,
        num_chunks=8000,
        randomize_seed=False,
        api_name="/shape_generation",
    )
    if isinstance(out_file, dict):
        out_file = out_file.get("value") or out_file.get("path")
    dst = REF / "hunyuan_shape.glb"
    shutil.copyfile(out_file, dst)
    print(f"done in {int(time.time() - t0)}s  seed={used_seed}  stats={stats}")
    print("saved", dst, dst.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
