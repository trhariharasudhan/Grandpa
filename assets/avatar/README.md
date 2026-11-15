# Wise Grandpa avatar (A3b)

`grandpa.glb` is the character `grandpa avatar` shows (see PR #27,
`src/grandpa/ui/avatar_character.py`). It is built by code, not by hand, so it
can be rebuilt and tweaked:

| File | What |
|---|---|
| `grandpa.glb` | glTF 2.0 binary, everything embedded, 28,510 triangles (budget 30,000), ~0.8 MB |
| `source/build_grandpa_avatar.py` | Blender script that builds and exports it |
| `source/blender_bridge.py` | Runs the script in an open Blender through the "MCP for Blender" addon (port 9876) |

**What is in it:** muscular full body (pecs, abs, obliques, delts, biceps,
triceps, lats, quads, calves sculpted on a dense mesh, then decimated),
head with eyes, upper lids, brows, nose, ears, lips; grey beard and moustache;
long wavy grey hair; round gold glasses with tinted lenses; black shorts with
waistband, drawstring and side splits.

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

Tuning knobs at the top of the script: `MUSCLE_GAIN` (1.0 subtle, 2.0 now),
`BODY_TRIANGLES`, `SHORTS_TRIANGLES`, and the material colours in `mats()`.

## Known limits

- Stylized and procedural, not a photoreal sculpt: no textures or normal maps yet.
- No armature; the viewer does breathing and head tilt on the whole model.
- Full body: `character.js` fits the whole model into the window, so the face
  is small. Framing on the `Grandpa_Head` node is the follow-up.
