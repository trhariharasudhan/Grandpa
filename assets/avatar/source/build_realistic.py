"""Realistic Grandpa: AI-generated body shape + the reference images projected on it.

Pipeline (run inside Blender 5.x; `blender_bridge.py` can drive it):

    1. hunyuan_shape.py   -> _reference/hunyuan_shape.glb (Hunyuan3D-2.1 shape, 366k faces)
    2. build(...) here    -> cleans it (cuts off the floor disc), sizes it to 1.78 m,
                             decimates to the A3 budget, splits off the head, cuts a
                             real mouth slit, unwraps UVs, then BAKES:
                               colour  = the reference views (front/side/back) projected
                                         onto the mesh, blended by surface direction
                               normal  = detail from the 366k-face original
                             adds 3D round gold glasses and the 10 shape keys.
    3. build_grandpa_avatar.export_glb(path)

Reference images (_reference/proj_front.png, proj_side.png, proj_back.png) are the
turnaround views with the background filled in and the eyepatch replaced by the
mirrored left eye. Their landmarks are in REF below (pixels).

Everything goes into the "Grandpa_Avatar" collection, like the procedural build.
"""

import math
from pathlib import Path

import bmesh
import bpy
import build_grandpa_avatar as gp
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HEIGHT = 1.78
HEAD_TRIANGLES = 9_000
BODY_TRIANGLES = 18_500
HEAD_TEX = 1024
BODY_TEX = 2048
SHAPE_KEYS = gp.SHAPE_KEYS

# Reference landmarks, in pixels of the cropped views (all crops share one scale:
# hair top at row 25, soles at row 957). cx = body centre column at the chest.
REF = {
    "top": 25.0,
    "sole": 957.0,
    "front": {"file": "proj_front.png", "w": 430, "h": 960, "cx": 214.5},
    "side": {"file": "proj_side.png", "w": 300, "h": 960, "cx": 139.0},
    "back": {"file": "proj_back.png", "w": 360, "h": 960, "cx": 179.5},
    # face, front view
    "eye_r": (200.0, 101.0),  # character's right eye (image left)
    "eye_l": (238.0, 101.0),
    "mouth": (221.0, 137.0),
    "mouth_half_width_px": 15.0,
    "brow_y": 90.0,
    "chin_y": 180.0,
    # nose tip: the alignment anchor between each image and the generated geometry
    "nose_front": (222.0, 123.0),
    "nose_side": (209.0, 120.0),
}


def _align_views_on_nose(high_me):
    """Shift the front/side image centres so the painted nose lands on the 3D nose.

    The torso-silhouette centres are a few pixels off (neighbouring panels leak
    into the crops); the nose tip is a sharp landmark in both images and the mesh.
    """
    s = _px_per_m()
    nose_z = HEIGHT - (REF["nose_front"][1] - REF["top"]) / s
    cands = [
        v.co
        for v in high_me.vertices
        if abs(v.co.z - nose_z) < 0.008 and abs(v.co.x) < 0.04
    ]
    if not cands:
        return None
    nose = min(cands, key=lambda c: c.y)  # the most forward point (faces -Y)
    REF["front"]["cx"] = REF["nose_front"][0] - nose.x * s
    REF["side"]["cx"] = REF["nose_side"][0] + nose.y * s
    return nose


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def _import_shape(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    src = next(o for o in new if o.type == "MESH")
    me = src.data.copy()
    me.transform(src.matrix_world)
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    return me


def _clean_and_size(me):
    """Cut the floor disc off under the soles, keep the figure, scale to HEIGHT."""
    bm = bmesh.new()
    bm.from_mesh(me)
    co = [v.co for v in bm.verts]
    far = [c.z for c in co if math.hypot(c.x, c.y) > 0.35]
    floor_top = max(far) if far else min(c.z for c in co)
    bmesh.ops.bisect_plane(
        bm,
        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
        plane_co=(0, 0, floor_top + 0.0015),
        plane_no=(0, 0, 1),
        clear_inner=True,
    )
    # keep the biggest connected piece (the figure)
    bm.verts.ensure_lookup_table()
    seen, best = set(), []
    for v in bm.verts:
        if v in seen:
            continue
        comp, stack = [], [v]
        seen.add(v)
        while stack:
            a = stack.pop()
            comp.append(a)
            for e in a.link_edges:
                b = e.other_vert(a)
                if b not in seen:
                    seen.add(b)
                    stack.append(b)
        if len(comp) > len(best):
            best = comp
    keep = set(best)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    zs = [v.co.z for v in bm.verts]
    z0, z1 = min(zs), max(zs)
    s = HEIGHT / (z1 - z0)
    chest_z = z0 + 0.72 * (z1 - z0)
    band = [v.co for v in bm.verts if abs(v.co.z - chest_z) < 0.02 * (z1 - z0)]
    cx = (min(c.x for c in band) + max(c.x for c in band)) / 2
    cy = (min(c.y for c in band) + max(c.y for c in band)) / 2
    bmesh.ops.transform(
        bm,
        matrix=Matrix.Diagonal((s, s, s, 1)) @ Matrix.Translation((-cx, -cy, -z0)),
        verts=bm.verts,
    )
    bm.to_mesh(me)
    bm.free()
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    return me


def _decimated(me, triangles):
    ob = bpy.data.objects.new("_dec", me.copy())
    gp.collection().objects.link(ob)
    tris = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    mod = ob.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = min(1.0, triangles / max(tris, 1))
    low = gp.bake(ob)
    old = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(old)
    return low


# --------------------------------------------------------------------------
# reference mapping (pixels <-> metres)
# --------------------------------------------------------------------------
def _px_per_m():
    return (REF["sole"] - REF["top"]) / HEIGHT


def front_px_to_xz(px, py):
    s = _px_per_m()
    return (px - REF["front"]["cx"]) / s, HEIGHT - (py - REF["top"]) / s


def _surface_point(bvh, x, z, from_front=True):
    origin = Vector((x, -2.0 if from_front else 2.0, z))
    hit, normal, _i, _d = bvh.ray_cast(origin, Vector((0, 1 if from_front else -1, 0)))
    return hit, normal


# --------------------------------------------------------------------------
# projection bake: reference views -> UV colour texture
# --------------------------------------------------------------------------
def _projection_material(ref_dir, size, target_img):
    mat = bpy.data.materials.new("_GP_Projection")
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(emit.outputs[0], out.inputs[0])
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    pos = nt.nodes.new("ShaderNodeSeparateXYZ")
    nrm = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], pos.inputs[0])
    nt.links.new(geo.outputs["Normal"], nrm.inputs[0])
    s = _px_per_m()

    def math_node(op, a, b=None, c=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    def view(name, horiz, sign, weight_axis, weight_sign, bias=1.0):
        info = REF[name]
        w, h = info["w"], info["h"]
        # u = (cx + sign*s*horiz)/w ; v = 1 - (top + (HEIGHT - z)*s)/h
        u = math_node("MULTIPLY_ADD", horiz, sign * s / w, info["cx"] / w)
        v = math_node(
            "MULTIPLY_ADD", pos.outputs["Z"], s / h, 1 - (REF["top"] + HEIGHT * s) / h
        )
        uv = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(u, uv.inputs[0])
        nt.links.new(v, uv.inputs[1])
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(
            str(Path(ref_dir) / info["file"]), check_existing=True
        )
        tex.extension = "EXTEND"
        nt.links.new(uv.outputs[0], tex.inputs[0])
        dot = math_node("MULTIPLY", nrm.outputs[weight_axis], weight_sign)
        wgt = math_node("POWER", math_node("MAXIMUM", dot, 0.0), 8.0)
        # + a small floor on the front view: faces no view sees (under the chin,
        # pointing straight down) would otherwise get zero weight and bake black
        wgt = math_node("MULTIPLY_ADD", wgt, bias, 0.03 if name == "front" else 0.0)
        return tex.outputs["Color"], wgt

    views = [
        view(
            "front", pos.outputs["X"], 1.0, "Y", -1.0, 2.0
        ),  # camera at -Y: image right = +X
        view(
            "back", pos.outputs["X"], -1.0, "Y", 1.0
        ),  # camera at +Y: image right = -X
        view(
            "side", pos.outputs["Y"], -1.0, "X", -1.0
        ),  # right side: image right = front (-Y)
        view(
            "side", pos.outputs["Y"], -1.0, "X", 1.0
        ),  # left side: the same view mirrored
    ]
    total = None
    acc = None
    for col, wgt in views:
        sc = nt.nodes.new("ShaderNodeVectorMath")
        sc.operation = "SCALE"
        nt.links.new(col, sc.inputs[0])
        nt.links.new(wgt, sc.inputs["Scale"])
        if acc is None:
            acc, total = sc.outputs[0], wgt
        else:
            add = nt.nodes.new("ShaderNodeVectorMath")
            add.operation = "ADD"
            nt.links.new(acc, add.inputs[0])
            nt.links.new(sc.outputs[0], add.inputs[1])
            acc = add.outputs[0]
            total = math_node("ADD", total, wgt)
    inv = math_node("DIVIDE", 1.0, math_node("MAXIMUM", total, 1e-4))
    norm = nt.nodes.new("ShaderNodeVectorMath")
    norm.operation = "SCALE"
    nt.links.new(acc, norm.inputs[0])
    nt.links.new(inv, norm.inputs["Scale"])
    nt.links.new(norm.outputs[0], emit.inputs["Color"])
    target = nt.nodes.new("ShaderNodeTexImage")
    target.image = target_img
    nt.nodes.active = target
    return mat


def _bake_textures(low_ob, high_ob, ref_dir, size, prefix):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.device = "CPU"
    except Exception:
        pass
    col_img = gp._image(prefix + "_Color", size, non_color=False)
    nrm_img = gp._image(prefix + "_Normal", size, non_color=True)

    # 1) colour: emission of the projected references, baked on the low mesh itself
    proj = _projection_material(ref_dir, size, col_img)
    keep = list(low_ob.data.materials)
    low_ob.data.materials.clear()
    low_ob.data.materials.append(proj)
    scene.cycles.samples = 4
    gp._select_only([low_ob], low_ob)
    bpy.ops.object.bake(
        type="EMIT", margin=48
    )  # wide: mipmaps must not reach the black

    # 2) normal: detail from the original high-res shape
    low_ob.data.materials.clear()
    tmp = bpy.data.materials.new("_GP_NormalTarget")
    try:
        tmp.use_nodes = True
    except Exception:
        pass
    tn = tmp.node_tree.nodes.new("ShaderNodeTexImage")
    tn.image = nrm_img
    tmp.node_tree.nodes.active = tn
    low_ob.data.materials.append(tmp)
    scene.cycles.samples = 8
    gp._select_only([high_ob, low_ob], low_ob)
    bpy.ops.object.bake(
        type="NORMAL",
        normal_space="TANGENT",
        use_selected_to_active=True,
        cage_extrusion=0.01,
        max_ray_distance=0.02,
        margin=48,
    )
    low_ob.data.materials.clear()
    for m in keep:
        low_ob.data.materials.append(m)
    bpy.data.materials.remove(proj)
    bpy.data.materials.remove(tmp)
    for img in (col_img, nrm_img):
        img.pack()
    return col_img, nrm_img


def _textured_material(name, col_img, nrm_img, rough=0.55):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = rough
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    c = nt.nodes.new("ShaderNodeTexImage")
    c.image = col_img
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = nrm_img
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(c.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(n.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# --------------------------------------------------------------------------
# head: split, mouth slit, cavity, shape keys
# --------------------------------------------------------------------------
def _copy_normals(src_me, dst_me):
    """Give dst the smooth normals of src (nearest vertex), so the head/body cut
    shades as one surface instead of showing a seam at the neck."""
    from mathutils.kdtree import KDTree

    kd = KDTree(len(src_me.vertices))
    for v in src_me.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    normals = [src_me.vertices[kd.find(v.co)[1]].normal.copy() for v in dst_me.vertices]
    dst_me.normals_split_custom_set_from_vertices(normals)


def _split_head(low_me, neck_z):
    """Two meshes: everything above the neck cut (head) and below (body)."""
    bm = bmesh.new()
    bm.from_mesh(low_me)
    bmesh.ops.bisect_plane(
        bm,
        geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
        plane_co=(0, 0, neck_z),
        plane_no=(0, 0, 1),
    )
    head_bm = bm.copy()
    bmesh.ops.delete(
        bm,
        geom=[f for f in bm.faces if f.calc_center_median().z > neck_z],
        context="FACES",
    )
    bmesh.ops.delete(
        head_bm,
        geom=[f for f in head_bm.faces if f.calc_center_median().z <= neck_z],
        context="FACES",
    )
    for b in (bm, head_bm):
        bmesh.ops.delete(
            b, geom=[v for v in b.verts if not v.link_faces], context="VERTS"
        )
    body_me = bpy.data.meshes.new("Grandpa_Body")
    head_me = bpy.data.meshes.new("Grandpa_Head")
    bm.to_mesh(body_me)
    head_bm.to_mesh(head_me)
    bm.free()
    head_bm.free()
    for m in (body_me, head_me):
        for p in m.polygons:
            p.use_smooth = True
        _copy_normals(low_me, m)
    return body_me, head_me


def _cut_mouth(head_me, mouth, half_width):
    """Open a slit along the lip line so the jaw can really open."""
    bm = bmesh.new()
    bm.from_mesh(head_me)
    region = [
        f
        for f in bm.faces
        if abs(f.calc_center_median().x - mouth.x) < half_width + 0.006
        and abs(f.calc_center_median().z - mouth.z) < 0.008
        and f.calc_center_median().y < mouth.y + 0.012
        and f.normal.y < 0
    ]
    res = bmesh.ops.bisect_plane(
        bm,
        geom=region
        + list({e for f in region for e in f.edges})
        + list({v for f in region for v in f.verts}),
        plane_co=mouth,
        plane_no=(0, 0, 1),
    )
    cut = [
        e
        for e in res["geom_cut"]
        if isinstance(e, bmesh.types.BMEdge)
        and all(abs(v.co.x - mouth.x) < half_width for v in e.verts)
    ]
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(head_me)
    bm.free()
    return len(cut)


def _add_cavity(head_me, mouth, half_width, material_index):
    bm = bmesh.new()
    bm.from_mesh(head_me)
    cav = gp.uv_sphere(
        mouth + Vector((0, 0.03, -0.006)), (half_width * 0.55, 0.012, 0.009), u=16, v=10
    )
    tmp = bpy.data.meshes.new("_cav")
    cav.to_mesh(tmp)
    cav.free()
    n = len(bm.faces)
    bm.from_mesh(tmp)
    bpy.data.meshes.remove(tmp)
    bm.faces.ensure_lookup_table()
    for f in bm.faces[n:]:
        f.material_index = material_index
        f.smooth = True
    bm.to_mesh(head_me)
    bm.free()


def _shape_keys(head_ob, lm):
    me = head_ob.data
    if me.shape_keys:
        head_ob.shape_key_clear()
    M, EL, ER, B = lm["mouth"], lm["eye_l"], lm["eye_r"], lm["brow_z"]
    hw = lm["mouth_hw"]
    base = [v.co.copy() for v in me.vertices]
    # which side of the slit each vertex is on: by its faces
    below = [False] * len(base)
    for p in me.polygons:
        if p.center.z < M.z:
            for i in p.vertices:
                below[i] = True
    above = [False] * len(base)
    for p in me.polygons:
        if p.center.z >= M.z:
            for i in p.vertices:
                above[i] = True
    g, ss = gp.gauss, gp.smoothstep

    def weights(i, c):
        x, y, z = c - M
        front = ss(0.03, -0.01, c.y - M.y)
        near = g(x * x, hw * 1.3) * g(z * z, 0.016) * front
        lower = below[i] and not above[i]
        jaw = (
            (1.0 if lower else ss(0.0005, -0.006, z))
            * g(x * x, 0.05)
            * front
            * ss(-0.075, -0.05, z)
        )
        corner = sum(g((x - s * hw) ** 2 + z * z, 0.007) for s in (-1, 1)) * front
        return near, jaw, corner, lower

    def lid(c, eye):
        r = c - eye
        return (
            g(r.x * r.x, 0.014)
            * ss(-0.006, 0.002, r.z)
            * (1 - ss(0.016, 0.026, r.z))
            * ss(0.025, 0.0, c.y - eye.y)
        )

    head_ob.shape_key_add(name="Basis", from_mix=False)
    for name in SHAPE_KEYS:
        sk = head_ob.shape_key_add(name=name, from_mix=False)
        sk.value = 0.0
        sk.slider_min, sk.slider_max = 0.0, 1.0
        for i, c in enumerate(base):
            near, jaw, corner, lower = weights(i, c)
            sx = 1 if c.x >= M.x else -1
            d = Vector()
            if name == "AA":
                d += Vector((0, 0.18, -1)) * 0.016 * jaw
            elif name == "E":
                d += Vector((0, 0.18, -1)) * 0.005 * jaw
                d.x += sx * 0.005 * corner
            elif name == "I":
                d += Vector((0, 0.18, -1)) * 0.003 * jaw
                d.x += sx * 0.007 * corner
                d.z += 0.0015 * corner
            elif name == "O":
                d += Vector((0, 0.18, -1)) * 0.010 * jaw
                d.x -= 0.3 * (c.x - M.x) * near
                d.y -= 0.005 * near
            elif name == "U":
                d += Vector((0, 0.18, -1)) * 0.004 * jaw
                d.x -= 0.45 * (c.x - M.x) * near
                d.y -= 0.008 * near
            elif name == "FV":
                d += Vector((0, 0.18, -1)) * 0.002 * jaw
                if lower:
                    d.z += 0.002 * near
                    d.y += 0.003 * near
            elif name == "MBP":
                d.y += 0.0015 * near
                d.z += (0.001 if lower else -0.0008) * near
            elif name == "smile":
                d.x += sx * 0.004 * corner
                d.z += 0.0055 * corner
                d.y += 0.002 * corner
                for e in (EL, ER):
                    cheek = g((c.x - e.x) ** 2 + (c.z - (e.z - 0.03)) ** 2, 0.014) * ss(
                        0.03, 0.0, c.y - e.y
                    )
                    d.z += 0.003 * cheek
            elif name == "think":
                d.x += 0.003 * near
                brow_l = (
                    g((c.x - EL.x) ** 2, 0.016)
                    * g((c.z - B) ** 2, 0.008)
                    * ss(0.03, 0.0, c.y - EL.y)
                )
                d.z += 0.006 * brow_l
            elif name == "blink":
                for e in (EL, ER):
                    w = lid(c, e)
                    d.z -= w * max(
                        0.0, (c.z - e.z) + 0.006
                    )  # upper lid skin slides down over the eye
                    d.y -= 0.002 * w
                    low = (
                        g((c.x - e.x) ** 2, 0.012)
                        * g((c.z - (e.z - 0.008)) ** 2, 0.004)
                        * ss(0.025, 0.0, c.y - e.y)
                    )
                    d.z += 0.004 * low  # lower lid comes up a little
            sk.data[i].co = c + d


# --------------------------------------------------------------------------
# glasses
# --------------------------------------------------------------------------
def _glasses(lm, head_bvh):
    M = dict(gp.mats())
    # lighter tint than the stylized build: the eyes (and the blink) must show through
    M["lens"] = gp.material("GP_LensClear", (0.95, 0.72, 0.25), rough=0.02, alpha=0.14)
    b = gp.Builder(["gold", "lens"])
    EL, ER = lm["eye_l"], lm["eye_r"]
    spacing = (EL - ER).length
    rim_r = min(0.022, 0.31 * spacing)  # ~4.4 cm lenses, like real round frames
    gy = min(EL.y, ER.y) - 0.014
    face = Matrix.Rotation(math.pi / 2, 3, "X")
    ez = (EL.z + ER.z) / 2
    # head half-width at eye height, for the temple arms
    hit_l, _n = head_bvh.ray_cast(Vector((0.4, 0.0, ez)), Vector((-1, 0, 0)))[:2]
    half = (hit_l.x if hit_l is not None else 0.075) + 0.006
    for e, sx in ((EL, 1), (ER, -1)):
        c = Vector((e.x, gy, ez))
        b.add(gp.torus(c, rim_r, 0.0012, seg=28, ring=6, rot=face), "gold")
        lens = bmesh.new()
        bmesh.ops.create_cone(
            lens, cap_ends=True, segments=28, radius1=rim_r, radius2=rim_r, depth=0.0006
        )
        bmesh.ops.transform(
            lens, matrix=Matrix.Translation(c) @ face.to_4x4(), verts=lens.verts
        )
        b.add(lens, "lens")
        hinge = Vector((e.x + sx * rim_r, gy + 0.002, ez + 0.002))
        ear = Vector(
            (sx * (half - 0.012), gy + 0.07, ez - 0.004)
        )  # ends inside the hair
        b.add(gp.tube(hinge, ear, 0.0012, 0.0012, seg=6), "gold")
    mid = (EL + ER) / 2
    prev = None
    for k in range(7):
        t = k / 6
        x = mid.x - (spacing / 2 - rim_r) + 2 * (spacing / 2 - rim_r) * t
        p = Vector((x, gy - 0.003, ez + 0.004 + 0.004 * math.sin(math.pi * t)))
        if prev is not None:
            b.add(gp.tube(prev, p, 0.0012, 0.0012, seg=6), "gold")
        prev = p
    return b.finish("Grandpa_Glasses", M)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def build(shape_glb, ref_dir):
    gp.collection(reset=True)
    root = gp.ensure_root()
    high_me = _clean_and_size(_import_shape(shape_glb))
    high_me.name = "GP_RealHigh"
    high = bpy.data.objects.new("GP_RealHigh", high_me)
    gp.collection().objects.link(high)

    nose = _align_views_on_nose(high_me)

    # landmarks from the front view, put on the surface by ray casting
    bvh = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    lm = {}
    for key in ("eye_l", "eye_r", "mouth"):
        x, z = front_px_to_xz(*REF[key])
        hit, _n = _surface_point(bvh, x, z)
        lm[key] = hit if hit is not None else Vector((x, -0.1, z))
    s = _px_per_m()
    lm["mouth_hw"] = REF["mouth_half_width_px"] / s
    lm["brow_z"] = HEIGHT - (REF["brow_y"] - REF["top"]) / s
    neck_z = HEIGHT - (REF["chin_y"] - REF["top"]) / s - 0.035

    low_me = _decimated(high_me, HEAD_TRIANGLES + BODY_TRIANGLES)
    body_me, head_me = _split_head(low_me, neck_z)
    bpy.data.meshes.remove(low_me)
    slit = _cut_mouth(head_me, lm["mouth"], lm["mouth_hw"])

    body = bpy.data.objects.new("Grandpa_Body", body_me)
    head = bpy.data.objects.new("Grandpa_Head", head_me)
    for o in (body, head):
        gp.collection().objects.link(o)
        o.parent = root
        gp._uv_unwrap(o)

    bcol, bnrm = _bake_textures(body, high, ref_dir, BODY_TEX, "GP_RealBody")
    hcol, hnrm = _bake_textures(head, high, ref_dir, HEAD_TEX, "GP_RealHead")
    body.data.materials.clear()
    body.data.materials.append(_textured_material("GP_RealBody", bcol, bnrm))
    head.data.materials.clear()
    head.data.materials.append(_textured_material("GP_RealHead", hcol, hnrm))
    head.data.materials.append(gp.mats()["mouth"])
    _add_cavity(head.data, lm["mouth"], lm["mouth_hw"], material_index=1)
    _shape_keys(head, lm)

    glasses = _glasses(
        lm, BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())
    )
    glasses.parent = root
    bpy.data.objects.remove(high, do_unlink=True)
    bpy.data.meshes.remove(high_me)
    rep = gp.report()
    rep.update(
        {
            "nose": [round(c, 4) for c in nose] if nose else None,
            "front_cx": round(REF["front"]["cx"], 1),
            "side_cx": round(REF["side"]["cx"], 1),
            "mouth_slit_edges": slit,
            "landmarks": {
                k: [round(c, 4) for c in v]
                for k, v in lm.items()
                if isinstance(v, Vector)
            },
        }
    )
    return rep
