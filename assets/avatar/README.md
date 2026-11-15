# Wise Grandpa avatar (A3b)

`grandpa.glb` is the character `grandpa avatar` shows (PR #27,
`src/grandpa/ui/avatar_character.py`): **realistic** muscular grandpa, built
from Captain's turnaround reference, **29,338 triangles** (budget 30,000),
~1.8 MB, everything embedded.

| Object | What |
|---|---|
| `Grandpa_Head` | head + hair + beard, 2048² colour + normal map (face restored with CodeFormer), a real mouth slit and cavity, the 10 shape keys `AA E I O U FV MBP smile think blink` (rest 0) |
| `Grandpa_Body` | body + shorts, 2048² colour + normal map |
| `Grandpa_Glasses` | round gold frames, light gold-tinted lenses |

## How it is made (realistic build)

```
turnaround.png ──prepare_reference.py──▶ _reference/{front,side,back}.png + proj_*.png
proj_front.png ──enhance_reference.py (CodeFormer, Hugging Face)──▶ _reference/proj_front_hd.png (4x, sharp face)
front.png ──hunyuan_shape.py (Hunyuan3D-2.1, Hugging Face)──▶ _reference/hunyuan_shape.glb (366k faces)
build_realistic.build(shape, _reference) in Blender:
    cut the floor disc, size to 1.78 m, decimate to budget, split the head,
    cut the mouth, UV unwrap, bake colour = reference views projected and blended
    by surface direction (aligned on the nose tip), bake normals from the 366k mesh,
    add glasses, add shape keys
build_grandpa_avatar.export_glb(path, image_format="JPEG")
```

`_reference/` (Captain's images and the generated mesh) is not committed.

Rebuild (Blender 5.3 with the MCP for Blender addon connected), from `D:\Grandpa`:

```powershell
python assets\avatar\source\prepare_reference.py <turnaround.png>
uv run --no-project --with gradio_client python assets\avatar\source\hunyuan_shape.py 1234
uv run --no-project --with gradio_client --with pillow python assets\avatar\source\enhance_reference.py
python assets\avatar\source\blender_bridge.py "import build_realistic as br, importlib; importlib.reload(br); r=br.build(r'D:\Grandpa\assets\avatar\source\_reference\hunyuan_shape.glb', r'D:\Grandpa\assets\avatar\source\_reference'); r.update(gp.export_glb(r'D:\Grandpa\assets\avatar\grandpa.glb', image_format='JPEG')); print(json.dumps(r, default=str))"
uv run --extra avatar --with pytest python -m pytest tests/ui/test_avatar_asset.py -q
uv run python -m grandpa avatar
```

## Stylized fallback (no cloud step)

`build_grandpa_avatar.build_all()` builds a fully procedural muscular grandpa
(skin-modifier body sculpted in code, baked normal + AO, procedural hair/beard)
with the same object names and shape keys. Use it if the generated shape is not
available.

## Licences and privacy

- The body shape comes from **Tencent Hunyuan3D-2.1** (Tencent Hunyuan 3D 2.1
  Community License). That licence does not cover use in the EU, the UK or
  South Korea; check it before shipping Grandpa there.
- `hunyuan_shape.py` and `enhance_reference.py` upload the front view to
  Hugging Face (CodeFormer: S-Lab License 1.0, non-commercial). Everything
  after that, and Grandpa at runtime, is local.

## Known limits

- The sheet's face is ~70 px wide; CodeFormer restores it to a sharp face
  (fidelity 0.7, so it stays the same man). Without `proj_front_hd.png` the
  build falls back to the soft original.
- Hands and the sides of the legs blend between views and are less exact than
  the front.
- No armature; the viewer does breathing and head tilt on the whole model.
- `character.js` frames head and chest using the `Grandpa_Head` node.
