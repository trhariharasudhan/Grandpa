# Wise Grandpa avatar (A3b)

`grandpa.glb` is the character `grandpa avatar` shows (see PR #27,
`src/grandpa/ui/avatar_character.py`). It is built by code, not by hand, so it
can be rebuilt and tweaked:

| File | What |
|---|---|
| `grandpa.glb` | glTF 2.0 binary, everything embedded, 28,978 triangles (budget 30,000), ~1.6 MB with two 1024² textures |
| `source/build_grandpa_avatar.py` | Blender script that builds and exports it |
| `source/blender_bridge.py` | Runs the script in an open Blender through the "MCP for Blender" addon (port 9876) |

**What is in it:** muscular full body (pecs, abs, obliques, delts, biceps,
triceps, lats, quads, calves sculpted on a dense mesh, then decimated),
head with eyes, upper lids, brows, nose, ears, lips; grey beard and moustache;
long wavy grey hair; round gold glasses with tinted lenses; black shorts with
waistband, drawstring and side splits. The body carries a baked **normal map**
(detail from the ~60k-face sculpt) and **ambient occlusion** in its colour
texture, so the creases between muscles stay dark in the viewer, which has no AO.
Beard and hairline taper into the skin instead of ending in a hard edge.

**Shape keys** (on the `Grandpa_Head` mesh, all rest at 0):
`AA E I O U FV MBP` (visemes) and `smile think blink`.

## Rebuild

Blender 5.3 with the MCP for Blender addon connected, then from `D:\Grandpa`:

```powershell
python assets\avatar\source\blender_bridge.py "r=gp.build_all(); r.update(gp.export_glb(r'D:\Grandpa\assets\avatar\grandpa.glb')); print(json.dumps(r))"
uv run pytest tests/ui/test_avatar_asset.py -q
uv run python -m grandpa avatar
```

Or in Blender: Scripting tab → open `build_grandpa_avatar.py` → run, then call
`build_all()` and `export_glb(path)` from the console.

Tuning knobs at the top of the script: `MUSCLE_GAIN` (1.0 subtle, 2.0 now), `BAKE_SIZE`,
`BODY_TRIANGLES`, `SHORTS_TRIANGLES`, and the material colours in `mats()`.

## Known limits

- Stylized and procedural, not a photoreal sculpt: no skin-pore or face textures.
- No armature; the viewer does breathing and head tilt on the whole model.
- `character.js` frames head and chest when the model has a `Grandpa_Head`
  node (`BUST_BELOW_HEAD`); a head-only model is still fitted whole.
