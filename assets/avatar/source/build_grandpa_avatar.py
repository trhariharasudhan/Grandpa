"""Build the 'Wise Grandpa' avatar for Grandpa (phase A3b) inside Blender.

Run in Blender's Python (Scripting tab, or via MCP). Everything it makes goes
into its own collection "Grandpa_Avatar"; nothing else in your scene is touched.

Stages (call one by one to watch it build, or build_all()):
    stage_body()       muscular base body (skin modifier -> baked mesh)
    stage_head()       head, eyes, lids, brows, nose, ears, lips, beard, moustache
    stage_hair()       long wavy grey hair (cap + clumps)
    stage_glasses()    round gold glasses with tinted lenses
    stage_dress()      black shorts with waistband (from the reference)
    stage_shape_keys() AA E I O U FV MBP smile think blink on Grandpa_Head
    export_glb(path)   glTF 2.0 binary, embedded, morph targets on

Rules come from PR #27 (src/grandpa/ui/avatar_character.py):
glTF 2.0 .glb, everything embedded, <= 30,000 triangles, <= 12 MB,
shape keys AA/E/I/O/U/FV/MBP/smile/think/blink.

Coordinates: metres, Z up, character faces -Y (Blender front view).
"""

import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

COLL = "Grandpa_Avatar"
SHAPE_KEYS = ("AA", "E", "I", "O", "U", "FV", "MBP", "smile", "think", "blink")
MAX_TRIANGLES = 30_000

# Head layout (shared by head, hair, glasses, shape keys)
HEAD_C = Vector((0.0, 0.0, 1.645))
HEAD_R = Vector((0.078, 0.095, 0.115))  # half extents x, y(depth), z
EYE_Z = 1.668
EYE_X = 0.032
EYE_R = 0.0125
MOUTH_Z = 1.588
NOSE_Z = 1.632


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def collection(reset=False):
    c = bpy.data.collections.get(COLL)
    if c is None:
        c = bpy.data.collections.new(COLL)
        bpy.context.scene.collection.children.link(c)
    if reset:
        for o in list(c.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    return c


def remove_obj(name):
    o = bpy.data.objects.get(name)
    if o is not None:
        bpy.data.objects.remove(o, do_unlink=True)


def material(name, rgb, metal=0.0, rough=0.6, alpha=1.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is None:
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = next(
            (n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None
        ) or nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(p.outputs[0], out.inputs[0])
    p.inputs["Base Color"].default_value = (*rgb, 1.0)
    p.inputs["Metallic"].default_value = metal
    p.inputs["Roughness"].default_value = rough
    p.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        for attr, val in (
            ("blend_method", "BLEND"),
            ("surface_render_method", "BLENDED"),
        ):
            try:
                setattr(m, attr, val)
            except Exception:
                pass
    m.use_backface_culling = False
    m.diffuse_color = (*rgb, alpha)
    return m


def mats():
    return {
        "skin": material("GP_Skin", (0.36, 0.17, 0.095), rough=0.5),
        "lip": material("GP_Lip", (0.30, 0.11, 0.08), rough=0.45),
        "mouth": material("GP_MouthInside", (0.06, 0.01, 0.01), rough=0.8),
        "eye": material("GP_EyeWhite", (0.78, 0.76, 0.72), rough=0.25),
        "iris": material("GP_Iris", (0.05, 0.025, 0.012), rough=0.2),
        "hair": material("GP_Hair", (0.27, 0.27, 0.28), rough=0.5),
        "beard": material("GP_Beard", (0.22, 0.22, 0.23), rough=0.6),
        "brow": material("GP_Brow", (0.26, 0.26, 0.27), rough=0.6),
        "gold": material("GP_Gold", (0.83, 0.56, 0.17), metal=1.0, rough=0.28),
        "lens": material("GP_Lens", (0.90, 0.62, 0.12), rough=0.05, alpha=0.32),
        "shorts": material("GP_Shorts", (0.012, 0.012, 0.014), rough=0.85),
    }


def new_object(name, mesh, mat_list, parent=None):
    remove_obj(name)
    ob = bpy.data.objects.new(name, mesh)
    collection().objects.link(ob)
    for m in mat_list:
        mesh.materials.append(m)
    for poly in mesh.polygons:
        poly.use_smooth = True
    root = bpy.data.objects.get("Grandpa")
    if parent is None and root is not None and ob is not root:
        ob.parent = root
    elif parent is not None:
        ob.parent = parent
    return ob


def ensure_root():
    root = bpy.data.objects.get("Grandpa")
    if root is None:
        root = bpy.data.objects.new("Grandpa", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.2
        collection().objects.link(root)
    return root


def bake(ob):
    """Evaluated mesh (modifiers applied) as a new mesh datablock."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(dg))


class Builder:
    """Collects parts into one bmesh with material slots and vertex groups."""

    def __init__(self, material_names, group_names=()):
        self.bm = bmesh.new()
        self.mat_index = {n: i for i, n in enumerate(material_names)}
        self.groups = list(group_names)
        self.deform = self.bm.verts.layers.deform.verify()

    def add(self, part_bm, mat, group=None):
        tmp = bpy.data.meshes.new("_tmp")
        part_bm.to_mesh(tmp)
        part_bm.free()
        nv, nf = len(self.bm.verts), len(self.bm.faces)
        self.bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        self.bm.verts.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        for f in self.bm.faces[nf:]:
            f.material_index = self.mat_index[mat]
        if group is not None:
            gi = self.groups.index(group)
            for v in self.bm.verts[nv:]:
                v[self.deform][gi] = 1.0

    def finish(self, name, mats_by_name):
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        ordered = sorted(self.mat_index, key=self.mat_index.get)
        ob = new_object(name, me, [mats_by_name[n] for n in ordered])
        for g in self.groups:
            ob.vertex_groups.new(name=g)
        return ob


def uv_sphere(center, radii, u=16, v=10, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1.0)
    m = Matrix.Diagonal((*radii, 1.0))
    if rot is not None:
        m = rot.to_4x4() @ m
    bmesh.ops.transform(bm, matrix=Matrix.Translation(center) @ m, verts=bm.verts)
    return bm


def torus(center, major, minor, seg=24, ring=8, scale=(1, 1, 1), rot=None):
    bm = bmesh.new()
    rows = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        row = []
        for j in range(ring):
            b = 2 * math.pi * j / ring
            r = major + minor * math.cos(b)
            row.append(
                bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b)))
            )
        rows.append(row)
    for i in range(seg):
        for j in range(ring):
            bm.faces.new(
                (
                    rows[i][j],
                    rows[(i + 1) % seg][j],
                    rows[(i + 1) % seg][(j + 1) % ring],
                    rows[i][(j + 1) % ring],
                )
            )
    m = Matrix.Diagonal((*scale, 1.0))
    if rot is not None:
        m = rot.to_4x4() @ m
    bmesh.ops.transform(bm, matrix=Matrix.Translation(center) @ m, verts=bm.verts)
    return bm


def tube(p0, p1, r0, r1, seg=8):
    bm = bmesh.new()
    d = Vector(p1) - Vector(p0)
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=seg, radius1=r0, radius2=r1, depth=d.length
    )
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    mid = (Vector(p0) + Vector(p1)) / 2
    bmesh.ops.transform(bm, matrix=Matrix.Translation(mid) @ rot, verts=bm.verts)
    return bm


def gauss(d2, s):
    return math.exp(-d2 / (2 * s * s))


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def head_front_y(x, z):
    """Y of the (undeformed) head ellipsoid's front surface."""
    k = 1 - (x / HEAD_R.x) ** 2 - ((z - HEAD_C.z) / HEAD_R.z) ** 2
    return HEAD_C.y - HEAD_R.y * math.sqrt(max(k, 0.0))


# --------------------------------------------------------------------------
# Stage 1: body
# --------------------------------------------------------------------------
BODY_TRIANGLES = 13_500  # share of the 30k budget; decimate keeps the detail
MUSCLE_GAIN = 2.0  # 1.0 = subtle, 2.0 = bodybuilder-ish like the reference


def _muscles(co, n):
    """Outward displacement (metres, along the normal) for one vertex.

    Each muscle is a soft 3D bump; grooves are negative. Masks use the normal
    so front muscles don't leak to the back. Left side only, mirrored by |x|.
    """
    x, y, z = co
    ax = abs(x)
    front = smoothstep(0.1, -0.45, n.y)
    back = smoothstep(-0.1, 0.45, n.y)
    side = smoothstep(0.2, 0.8, abs(n.x))

    def b(cx, cy, cz, sx, sy, sz):
        return math.exp(
            -(((ax - cx) / sx) ** 2 + ((y - cy) / sy) ** 2 + ((z - cz) / sz) ** 2) / 2
        )

    d = 0.0
    # --- chest: pectorals with a crisp lower edge, sternum groove, clavicles
    pec = (
        b(0.085, -0.13, 1.375, 0.055, 0.06, 0.042) * smoothstep(1.30, 1.335, z) * front
    )
    d += 0.020 * pec
    d -= (
        0.006
        * math.exp(-((x / 0.009) ** 2) / 2)
        * smoothstep(1.31, 1.34, z)
        * (1 - smoothstep(1.43, 1.46, z))
        * front
    )
    d += 0.005 * b(0.09, -0.10, 1.462, 0.06, 0.05, 0.008) * front
    # --- abs: three rows of blocks, linea alba, V-lines, obliques, serratus
    for row_z in (1.135, 1.195, 1.255):
        d += 0.009 * b(0.031, -0.12, row_z, 0.019, 0.08, 0.021) * front
    abs_zone = smoothstep(1.08, 1.11, z) * (1 - smoothstep(1.29, 1.32, z)) * front
    d -= 0.005 * math.exp(-((x / 0.0065) ** 2) / 2) * abs_zone
    t = max(0.0, min(1.0, (1.11 - z) / 0.13))  # inguinal V from hip bone to pubis
    vx = 0.115 - 0.075 * t
    d -= (
        0.006
        * math.exp(-(((ax - vx) / 0.008) ** 2) / 2)
        * smoothstep(0.96, 0.99, z)
        * (1 - smoothstep(1.10, 1.13, z))
        * front
    )
    d += 0.007 * b(0.125, -0.07, 1.16, 0.025, 0.06, 0.05) * (front + side) * 0.7
    for k in range(3):
        d += (
            0.004
            * b(0.15, -0.06, 1.23 + 0.03 * k, 0.012, 0.05, 0.010)
            * (front + side)
            * 0.7
        )
    # --- neck: sternocleidomastoid ridges, trapezius slope
    for k in range(5):
        tt = k / 4
        d += (
            0.005
            * b(
                0.045 - 0.03 * tt,
                -0.02 - 0.025 * tt,
                1.565 - 0.07 * tt,
                0.01,
                0.015,
                0.015,
            )
            * front
        )
    d += 0.016 * b(0.075, 0.03, 1.48, 0.06, 0.06, 0.035)
    # --- shoulders and arms
    d += 0.022 * b(0.245, 0.0, 1.415, 0.045, 0.065, 0.05)  # deltoid
    d += 0.004 * b(0.235, -0.04, 1.40, 0.02, 0.03, 0.04) * front  # front delt split
    d += 0.015 * b(0.255, -0.03, 1.30, 0.03, 0.03, 0.055) * front  # biceps
    d += 0.013 * b(0.265, 0.035, 1.32, 0.03, 0.03, 0.06) * back  # triceps
    d += 0.004 * b(0.24, 0.0, 1.27, 0.012, 0.06, 0.06) * side  # biceps/triceps split
    d += 0.010 * b(0.295, -0.015, 1.12, 0.022, 0.025, 0.045)  # brachioradialis
    d += 0.006 * b(0.29, 0.02, 1.08, 0.02, 0.02, 0.06) * back  # forearm extensors
    # --- back: lats (V-taper), spine groove, scapulae, lower-back erectors
    d += 0.026 * b(0.15, 0.07, 1.28, 0.04, 0.06, 0.07) * (back + side) * 0.8
    d -= (
        0.012
        * math.exp(-((x / 0.011) ** 2) / 2)
        * smoothstep(1.02, 1.06, z)
        * (1 - smoothstep(1.44, 1.47, z))
        * back
    )
    d += 0.014 * b(0.085, 0.11, 1.38, 0.035, 0.04, 0.04) * back
    d -= 0.006 * b(0.115, 0.12, 1.33, 0.012, 0.05, 0.05) * back  # scapula edge
    d += 0.016 * b(0.035, 0.10, 1.12, 0.018, 0.04, 0.06) * back
    # --- hips and legs
    d += 0.022 * b(0.085, 0.10, 0.90, 0.055, 0.05, 0.055) * back  # glutes
    d += 0.011 * b(0.10, -0.06, 0.74, 0.03, 0.04, 0.08) * front  # rectus femoris
    d += 0.010 * b(0.15, -0.01, 0.72, 0.03, 0.06, 0.08)  # vastus lateralis
    d += (
        0.014 * b(0.07, -0.04, 0.575, 0.025, 0.04, 0.04) * front
    )  # vastus medialis teardrop
    d += 0.009 * b(0.10, 0.05, 0.72, 0.04, 0.04, 0.08) * back  # hamstrings
    d += 0.007 * b(0.10, -0.06, 0.505, 0.02, 0.02, 0.022) * front  # kneecap
    d += 0.015 * b(0.085, 0.05, 0.40, 0.02, 0.03, 0.05) * back  # calf inner head
    d += 0.013 * b(0.118, 0.045, 0.41, 0.02, 0.03, 0.045) * back  # calf outer head
    d += 0.005 * b(0.115, -0.04, 0.30, 0.015, 0.02, 0.07) * front  # tibialis
    return d


def stage_body():
    collection()
    ensure_root()
    M = mats()
    # (name, position, radius(x, y), parent) -- left side only, mirrored below.
    # Radii are final-ish; subsurf shrinks the hull, the bulk factor makes up for it.
    centre = [
        ("pelvis", (0, 0.0, 0.97), (0.168, 0.125), None),
        ("waist", (0, 0.0, 1.07), (0.142, 0.105), "pelvis"),
        ("belly", (0, -0.005, 1.19), (0.165, 0.115), "waist"),
        ("chest", (0, -0.005, 1.32), (0.235, 0.15), "belly"),
        ("upchest", (0, 0.005, 1.415), (0.225, 0.135), "chest"),
        ("neck0", (0, 0.012, 1.485), (0.075, 0.075), "upchest"),
        ("neck1", (0, 0.012, 1.56), (0.07, 0.072), "neck0"),
    ]
    side = [
        ("shoulder", (0.215, 0.005, 1.415), (0.082, 0.092), "upchest"),
        ("bicep", (0.248, 0.005, 1.31), (0.074, 0.08), "shoulder"),
        ("elbow", (0.272, 0.01, 1.17), (0.050, 0.055), "bicep"),
        ("forearm", (0.29, 0.0, 1.075), (0.060, 0.058), "elbow"),
        ("wrist", (0.315, -0.005, 0.935), (0.032, 0.026), "forearm"),
        ("palm", (0.33, -0.008, 0.865), (0.019, 0.046), "wrist"),
        ("thumb0", (0.322, -0.042, 0.9), (0.013, 0.013), "wrist"),
        ("thumb1", (0.33, -0.062, 0.865), (0.010, 0.010), "thumb0"),
        ("thumb2", (0.334, -0.07, 0.835), (0.008, 0.008), "thumb1"),
        ("hip", (0.095, 0.0, 0.92), (0.108, 0.115), "pelvis"),
        ("thigh", (0.10, -0.005, 0.73), (0.098, 0.105), "hip"),
        ("knee", (0.10, -0.01, 0.51), (0.058, 0.062), "thigh"),
        ("calf", (0.10, 0.015, 0.39), (0.068, 0.074), "knee"),
        ("shin", (0.10, 0.005, 0.22), (0.044, 0.046), "calf"),
        ("ankle", (0.10, 0.01, 0.075), (0.033, 0.035), "shin"),
        ("heel", (0.10, 0.045, 0.03), (0.032, 0.028), "ankle"),
        ("ball", (0.105, -0.08, 0.025), (0.046, 0.022), "ankle"),
        ("toes", (0.11, -0.135, 0.02), (0.038, 0.016), "ball"),
    ]
    # four fingers: knuckle, middle, tip -- spread front-to-back (palm faces the thigh)
    for fi, (fy, ln) in enumerate(
        ((-0.030, 0.085), (-0.010, 0.095), (0.010, 0.09), (0.028, 0.075))
    ):
        k = ("fk%d" % fi, (0.336, fy, 0.828), (0.0095, 0.0095), "palm")
        m = ("fm%d" % fi, (0.34, fy * 1.05, 0.828 - ln * 0.5), (0.0085, 0.0085), k[0])
        t = ("ft%d" % fi, (0.336, fy * 1.08, 0.828 - ln), (0.007, 0.007), m[0])
        side += [k, m, t]
    pts, rad, edges, idx = [], [], [], {}

    def add(key, pos, r, parent):
        idx[key] = len(pts)
        pts.append(pos)
        rad.append(r)
        if parent is not None:
            edges.append((idx[parent], idx[key]))

    for n, p, r, par in centre:
        add(n, p, r, par)
    for s, sign in (("L", 1), ("R", -1)):
        for n, p, r, par in side:
            parent = par + s if (par + s) in idx else par
            add(n + s, (p[0] * sign, p[1], p[2]), r, parent)
    me = bpy.data.meshes.new("GP_BodySkeleton")
    me.from_pydata(pts, edges, [])
    tmp = bpy.data.objects.new("GP_BodySkeleton", me)
    collection().objects.link(tmp)
    sk = tmp.modifiers.new("Skin", "SKIN")
    sk.branch_smoothing = 0.5
    for i, r in enumerate(rad):
        me.skin_vertices[0].data[i].radius = r
    me.skin_vertices[0].data[idx["pelvis"]].use_root = True
    sub = tmp.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 3
    sub.render_levels = 3
    dense = bake(tmp)
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(me)

    # sculpt the muscles on the dense mesh, along the normals
    bm = bmesh.new()
    bm.from_mesh(dense)
    bm.normal_update()
    offs = [(v, _muscles(v.co, v.normal)) for v in bm.verts]
    for v, dd in offs:
        v.co += v.normal * dd * MUSCLE_GAIN
    bmesh.ops.smooth_vert(
        bm,
        verts=bm.verts,
        factor=0.08,
        use_axis_x=True,
        use_axis_y=True,
        use_axis_z=True,
    )
    bm.to_mesh(dense)
    bm.free()

    # decimate to the triangle share, detail stays where the curvature is
    old = bpy.data.meshes.get("GP_BodyDenseCache")
    if old is not None:
        bpy.data.meshes.remove(old)
    cache = dense.copy()
    cache.name = (
        "GP_BodyDenseCache"  # the shorts are cut from this (no object, never exported)
    )
    tmp = bpy.data.objects.new("GP_BodyDense", dense)
    collection().objects.link(tmp)
    tris = sum(len(p.vertices) - 2 for p in dense.polygons)
    dec = tmp.modifiers.new("Decimate", "DECIMATE")
    dec.ratio = min(1.0, BODY_TRIANGLES / max(tris, 1))
    body_me = bake(tmp)
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(dense)
    body_me.name = "Grandpa_Body"
    remove_obj("Grandpa_Body")
    ob = new_object("Grandpa_Body", body_me, [M["skin"]])
    return {"body_triangles": tri_count(ob)}


# --------------------------------------------------------------------------
# Stage 2: head
# --------------------------------------------------------------------------
GROUPS = ("lid_L", "lid_R", "brow_L", "brow_R", "eyes")


def stage_head():
    collection()
    ensure_root()
    M = mats()
    b = Builder(["skin", "lip", "mouth", "eye", "iris", "beard", "brow"], GROUPS)

    # skull/face
    head = uv_sphere(HEAD_C, HEAD_R, u=40, v=28)
    for v in head.verts:
        x, y, z = v.co
        dz = z - HEAD_C.z
        front = smoothstep(0.02, -0.06, y)
        # narrower jaw, stronger chin, flatter sides, back of skull rounder
        if dz < 0:
            v.co.x *= 1 - 0.18 * smoothstep(0.0, -0.1, dz)
        v.co.y -= (
            0.010 * gauss(x * x, 0.02) * gauss((z - 1.548) ** 2, 0.012) * front
        )  # chin
        # eye sockets in, brow ridge out, cheekbones out
        for sx in (-1, 1):
            sock = gauss((x - sx * EYE_X) ** 2 + (z - EYE_Z) ** 2, 0.013) * front
            v.co.y += 0.011 * sock
            brow = (
                gauss((x - sx * 0.034) ** 2, 0.018)
                * gauss((z - 1.687) ** 2, 0.006)
                * front
            )
            v.co.y -= 0.006 * brow
            cheek = gauss((x - sx * 0.05) ** 2 + (z - 1.628) ** 2, 0.018) * front
            v.co.y -= 0.004 * cheek
            v.co.x += sx * 0.003 * cheek
        # nose
        nose = gauss(x * x, 0.010) * gauss((z - NOSE_Z) ** 2, 0.022) * front
        tip = gauss(x * x, 0.011) * gauss((z - (NOSE_Z - 0.008)) ** 2, 0.008) * front
        v.co.y -= 0.016 * nose + 0.012 * tip
        # mouth area slightly in so lips sit on it
        v.co.y += 0.004 * gauss(x * x, 0.02) * gauss((z - MOUTH_Z) ** 2, 0.008) * front
    b.add(head, "skin")

    for sx, s in ((1, "L"), (-1, "R")):
        # ears
        b.add(
            uv_sphere((sx * 0.077, 0.006, 1.642), (0.010, 0.020, 0.030), u=12, v=8),
            "skin",
        )
        ec = Vector((sx * EYE_X, head_front_y(EYE_X, EYE_Z) + 0.0065, EYE_Z))
        b.add(uv_sphere(ec, (EYE_R,) * 3, u=16, v=12), "eye", "eyes")
        b.add(
            uv_sphere(
                ec + Vector((0, -EYE_R + 0.0012, 0)),
                (0.0062, 0.0022, 0.0062),
                u=12,
                v=8,
            ),
            "iris",
            "eyes",
        )
        # upper lid: front-top cap of a sphere just outside the eyeball
        lid = uv_sphere(ec, (0.0145,) * 3, u=16, v=12)
        bmesh.ops.delete(
            lid,
            geom=[
                v for v in lid.verts if v.co.z - ec.z < 0.004 or v.co.y - ec.y > 0.006
            ],
            context="VERTS",
        )
        b.add(lid, "skin", "lid_" + s)
        # bushy grey brow
        bc = Vector((sx * 0.034, head_front_y(0.034, 1.69) - 0.004, 1.69))
        b.add(
            uv_sphere(
                bc,
                (0.018, 0.006, 0.0045),
                u=12,
                v=8,
                rot=Matrix.Rotation(-sx * 0.12, 3, "Y"),
            ),
            "brow",
            "brow_" + s,
        )

    # lips + mouth cavity
    mfy = head_front_y(0, MOUTH_Z)
    b.add(
        torus(
            (0, mfy - 0.002, MOUTH_Z),
            0.019,
            0.0048,
            seg=28,
            ring=8,
            scale=(1.1, 0.26, 0.75),
            rot=Matrix.Rotation(math.pi / 2, 3, "X"),
        ),
        "lip",
    )
    b.add(
        uv_sphere((0, mfy + 0.004, MOUTH_Z), (0.019, 0.006, 0.0045), u=12, v=8), "mouth"
    )
    # close the lips at rest: pull the inner half of the lip ring onto the mouth line
    b.bm.verts.ensure_lookup_table()
    lip_idx = b.mat_index["lip"]
    lip_verts = {v for f in b.bm.faces if f.material_index == lip_idx for v in f.verts}
    for v in lip_verts:
        rr = math.hypot(v.co.x / 1.1, (v.co.z - MOUTH_Z) / 0.26)
        if rr < 0.019:
            v.co.z = MOUTH_Z + (v.co.z - MOUTH_Z) * 0.2

    # moustache: droopy at the corners
    mo = uv_sphere(
        (0, mfy - 0.006, MOUTH_Z + 0.013), (0.031, 0.009, 0.0065), u=20, v=10
    )
    for v in mo.verts:
        v.co.z -= 9.0 * v.co.x**2
        v.co.y += 3.0 * v.co.x**2
    b.add(mo, "beard")

    # beard: shell over chin/jaw/cheeks with a hole for the mouth
    beard = uv_sphere(HEAD_C, HEAD_R * 1.0, u=40, v=28)
    kill = []
    for v in beard.verts:
        x, y, z = v.co
        zcut = 1.582 + 0.06 * smoothstep(0.035, 0.07, abs(x))
        mouth_hole = (x / 0.032) ** 2 + ((z - MOUTH_Z) / 0.011) ** 2 < 1 and y < -0.04
        if z > zcut or y > 0.03 or mouth_hole:
            kill.append(v)
    bmesh.ops.delete(beard, geom=kill, context="VERTS")
    for v in beard.verts:
        x, y, z = v.co
        if z < HEAD_C.z:
            v.co.x *= 1 - 0.18 * smoothstep(0.0, -0.1, z - HEAD_C.z)
        n = (v.co - HEAD_C).normalized()
        thick = 0.009 + 0.012 * smoothstep(1.58, 1.53, z)
        v.co += n * thick
        # beard length: chin hangs lower, little wave
        v.co.z -= 0.035 * smoothstep(1.575, 1.535, z) * gauss(x * x, 0.04)
        v.co += n * 0.002 * math.sin(x * 260 + z * 180)
    b.add(beard, "beard")

    ob = b.finish("Grandpa_Head", M)
    return {"head_triangles": tri_count(ob)}


# --------------------------------------------------------------------------
# Stage 3: hair
# --------------------------------------------------------------------------
def stage_hair(seed=7):
    collection()
    ensure_root()
    M = mats()
    rnd = random.Random(seed)
    b = Builder(["hair"])

    cap_c = HEAD_C + Vector((0, 0.006, 0.004))
    cap_r = Vector((HEAD_R.x + 0.010, HEAD_R.y + 0.010, HEAD_R.z + 0.010))
    cap = uv_sphere(cap_c, cap_r, u=32, v=20)
    kill = []
    for v in cap.verts:
        x, y, z = v.co
        hairline = 1.712 - 0.06 * smoothstep(
            0.03, 0.075, abs(x)
        )  # high forehead, temples lower
        if z < 1.565 or (y < -0.02 and z < hairline):
            kill.append(v)
    bmesh.ops.delete(cap, geom=kill, context="VERTS")
    for v in cap.verts:
        n = (v.co - cap_c).normalized()
        v.co += n * 0.0035 * math.sin(math.atan2(v.co.x, v.co.y) * 14 + v.co.z * 60)
    b.add(cap, "hair")

    # back sheet: one wavy layer that gives the long hair its volume
    sheet = bmesh.new()
    cols, rows = 44, 16
    grid = []
    for j in range(rows):
        t = j / (rows - 1)
        row = []
        for i in range(cols):
            az = math.radians(-118 + 236 * i / (cols - 1))  # 0 = back (+Y)
            z = 1.668 - (1.668 - 1.355) * t**0.95 + 0.012 * math.cos(az * 2.2) * t
            # radius: hugs the skull, swells a little, then lies on the upper back
            sx = cap_r.x * (1.04 + 0.35 * t) + 0.012 * smoothstep(0.0, 0.3, t)
            sy = cap_r.y * (1.04 + 0.25 * t)
            wave = 0.010 * math.sin(az * 11 + t * 9) * smoothstep(0.05, 0.3, t)
            p = Vector(
                (math.sin(az) * (sx + wave), cap_c.y + math.cos(az) * (sy + wave), z)
            )
            if z < 1.50:
                p.y = max(p.y, 0.145 - 0.2 * max(0.0, abs(p.x) - 0.11))
            # ragged ends
            p.z += 0.025 * t**4 * math.sin(i * 1.7)
            row.append(sheet.verts.new(p))
        grid.append(row)
    for j in range(rows - 1):
        for i in range(cols - 1):
            sheet.faces.new(
                (grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i])
            )
    b.add(sheet, "hair")

    # clumps: tapered wavy locks on top of the sheet
    clumps = 26
    for i in range(clumps):
        az = math.radians(
            -145 + 290 * (i + 0.5) / clumps + rnd.uniform(-4, 4)
        )  # 0 = back (+Y)
        el = math.radians(rnd.uniform(5, 45))
        p0 = cap_c + Vector(
            (
                cap_r.x * math.cos(el) * math.sin(az),
                cap_r.y * math.cos(el) * math.cos(az),
                cap_r.z * math.sin(el),
            )
        )
        side = abs(math.sin(az))
        z_end = rnd.uniform(1.32, 1.40) + 0.05 * side
        y_end = 0.15 + rnd.uniform(-0.01, 0.02) - 0.03 * side
        x_end = p0.x * (1.2 + 0.6 * side) + rnd.uniform(-0.01, 0.01)
        phase = rnd.uniform(0, math.tau)
        pts = []
        steps = 8
        for k in range(steps):
            t = k / (steps - 1)
            pos = Vector(
                (
                    p0.x + (x_end - p0.x) * t,
                    p0.y + (y_end - p0.y) * smoothstep(0, 0.8, t),
                    p0.z + (z_end - p0.z) * t**0.9,
                )
            )
            wave = 0.011 * math.sin(phase + t * math.pi * 3.2) * smoothstep(0, 0.25, t)
            pos.x += wave * math.cos(az)
            pos.y -= wave * math.sin(az) * 0.5
            # keep outside the head and off the back/shoulders
            rel = Vector(
                (
                    (pos.x - cap_c.x) / cap_r.x,
                    (pos.y - cap_c.y) / cap_r.y,
                    (pos.z - cap_c.z) / cap_r.z,
                )
            )
            if rel.length < 1.06:
                pos = cap_c + Vector(
                    (rel.x * cap_r.x, rel.y * cap_r.y, rel.z * cap_r.z)
                ) * (1.06 / max(rel.length, 1e-6))
            if pos.z < 1.50:
                pos.y = max(pos.y, 0.14 - 0.25 * max(0.0, abs(pos.x) - 0.12))
            pts.append(pos)
        cu = bpy.data.curves.new("_clump", "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = rnd.uniform(0.014, 0.020)
        cu.bevel_resolution = 1
        cu.resolution_u = 2
        cu.use_fill_caps = True
        sp = cu.splines.new("NURBS")
        sp.points.add(len(pts) - 1)
        for k, p in enumerate(pts):
            sp.points[k].co = (*p, 1.0)
            sp.points[k].radius = 1.0 - 0.7 * (k / (len(pts) - 1)) ** 1.3
        sp.use_endpoint_u = True
        sp.order_u = 3
        tmp = bpy.data.objects.new("_clump", cu)
        collection().objects.link(tmp)
        me = bake(tmp)
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.curves.remove(cu)
        part = bmesh.new()
        part.from_mesh(me)
        bpy.data.meshes.remove(me)
        b.add(part, "hair")

    ob = b.finish("Grandpa_Hair", M)
    return {"hair_triangles": tri_count(ob)}


# --------------------------------------------------------------------------
# Stage 4: glasses
# --------------------------------------------------------------------------
def stage_glasses():
    collection()
    ensure_root()
    M = mats()
    b = Builder(["gold", "lens"])
    gy = head_front_y(EYE_X, EYE_Z) - 0.016
    rim_r = 0.0172
    face = Matrix.Rotation(math.pi / 2, 3, "X")
    for sx in (1, -1):
        c = Vector((sx * 0.033, gy, EYE_Z))
        b.add(torus(c, rim_r, 0.0011, seg=28, ring=5, rot=face), "gold")
        lens = bmesh.new()
        bmesh.ops.create_cone(
            lens, cap_ends=True, segments=28, radius1=rim_r, radius2=rim_r, depth=0.0006
        )
        bmesh.ops.transform(
            lens, matrix=Matrix.Translation(c) @ face.to_4x4(), verts=lens.verts
        )
        b.add(lens, "lens")
        # temple arm to the ear
        hinge = Vector((sx * (0.033 + rim_r), gy + 0.002, EYE_Z + 0.002))
        ear = Vector((sx * 0.084, 0.012, EYE_Z - 0.006))
        b.add(tube(hinge, ear, 0.0011, 0.0011, seg=6), "gold")
        b.add(tube(ear, ear + Vector((0, 0.02, -0.018)), 0.0011, 0.0011, seg=6), "gold")
    # arched bridge
    prev = None
    for k in range(7):
        t = k / 6
        x = -0.0158 + 0.0316 * t
        p = Vector((x, gy - 0.003, EYE_Z + 0.004 + 0.004 * math.sin(math.pi * t)))
        if prev is not None:
            b.add(tube(prev, p, 0.0011, 0.0011, seg=6), "gold")
        prev = p
    ob = b.finish("Grandpa_Glasses", M)
    return {"glasses_triangles": tri_count(ob)}


# --------------------------------------------------------------------------
# Stage 5: dress (black shorts, from the reference)
# --------------------------------------------------------------------------
SHORTS_TRIANGLES = 2_200


def stage_dress():
    """Black athletic shorts cut from the dense body, so the hem is clean."""
    collection()
    M = mats()
    dense = bpy.data.meshes.get("GP_BodyDenseCache")
    if dense is None:
        raise RuntimeError("build the body first (stage_body)")
    bm = bmesh.new()
    bm.from_mesh(dense)
    bm.normal_update()
    top, hem = 1.055, 0.64

    def inside(v):
        h = hem + 0.035 * smoothstep(
            0.13, 0.17, abs(v.co.x)
        )  # side split: hem rises at the outer thigh
        return h <= v.co.z <= top and abs(v.co.x) < 0.205

    bmesh.ops.delete(
        bm,
        geom=[f for f in bm.faces if not all(inside(v) for v in f.verts)],
        context="FACES",
    )
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    # snap open edges to clean lines: the hem (with side split) and the waist
    for e in bm.edges:
        if e.is_boundary:
            for v in e.verts:
                if v.co.z < 0.85:
                    v.co.z = hem + 0.035 * smoothstep(0.13, 0.17, abs(v.co.x))
                else:
                    v.co.z = top
    bm.normal_update()
    for v in bm.verts:
        loose = 0.008 + 0.012 * smoothstep(0.74, hem, v.co.z)  # flares at the hem
        v.co += v.normal * loose
    # waistband: a ring fitted to the top edge of the shorts
    ring = [v.co for v in bm.verts if v.co.z > top - 0.01]
    rx = max(abs(c.x) for c in ring) + 0.004
    ymin, ymax = min(c.y for c in ring), max(c.y for c in ring)
    cy, ry = (ymin + ymax) / 2, (ymax - ymin) / 2 + 0.004
    wb = Builder(["shorts"])
    wb.add(bm, "shorts")
    wb.add(torus((0, 0, 0), 1.0, 0.011, seg=48, ring=6, scale=(1, 1, 1)), "shorts")
    # scale only the waistband ring (last added verts) to the fitted ellipse
    wb.bm.verts.ensure_lookup_table()
    n_ring = 48 * 6
    for v in wb.bm.verts[-n_ring:]:
        rr = math.hypot(v.co.x, v.co.y)
        a = math.atan2(v.co.y, v.co.x)
        v.co.x = math.cos(a) * (rx + (rr - 1.0))
        v.co.y = cy + math.sin(a) * (ry + (rr - 1.0))
        v.co.z += top - 0.010
    # drawstring: two short cords at the front
    for sx in (-1, 1):
        a = Vector((sx * 0.012, ymin - 0.006, top - 0.014))
        wb.add(
            tube(a, a + Vector((sx * 0.006, -0.004, -0.07)), 0.0025, 0.002, seg=6),
            "shorts",
        )
    ob = wb.finish("Grandpa_Shorts", M)
    tris = tri_count(ob)
    if tris > SHORTS_TRIANGLES:
        dec = ob.modifiers.new("Decimate", "DECIMATE")
        dec.ratio = SHORTS_TRIANGLES / tris
        me = bake(ob)
        ob.modifiers.clear()
        old = ob.data
        ob.data = me
        me.name = "Grandpa_Shorts"
        bpy.data.meshes.remove(old)
    return {"shorts_triangles": tri_count(ob)}


# --------------------------------------------------------------------------
# Stage 6: shape keys on Grandpa_Head
# --------------------------------------------------------------------------
def _mouth_weights(co):
    x, y, z = co
    dz = z - MOUTH_Z
    front = smoothstep(0.03, -0.04, y)
    near = gauss(x * x, 0.028) * gauss(dz * dz, 0.022) * front
    # sharp hinge right at the (closed) lip line, then full weight below it
    jaw = (
        smoothstep(0.00005, -0.0012, dz)
        * gauss(x * x, 0.055)
        * front
        * (1 - smoothstep(1.50, 1.47, z) * 0.0)
    )
    corner = sum(gauss((x - s * 0.02) ** 2 + dz * dz, 0.007) for s in (-1, 1)) * front
    lower_lip = gauss(x * x, 0.02) * gauss((dz + 0.004) ** 2, 0.004) * front * (dz < 0)
    upper_lip = gauss(x * x, 0.02) * gauss((dz - 0.004) ** 2, 0.004) * front * (dz > 0)
    return near, jaw, corner, lower_lip, upper_lip


def _open(co, jaw, amount):
    return Vector((0, 0.18 * amount * jaw, -amount * jaw))


def _key_fn(name):
    def fn(co, groups):
        if "eyes" in groups or "lid_L" in groups or "lid_R" in groups:
            if name != "blink" and name != "smile":
                return co.copy()
        x = co.x
        near, jaw, corner, lo, up = _mouth_weights(co)
        sx = 1 if x >= 0 else -1
        d = Vector()
        if name == "AA":
            d += _open(co, jaw, 0.019)
            d.x -= 0.15 * x * near
        elif name == "E":
            d += _open(co, jaw, 0.006)
            d.x += sx * 0.006 * corner
            d.z += 0.001 * corner
        elif name == "I":
            d += _open(co, jaw, 0.004)
            d.x += sx * 0.009 * corner
            d.z += 0.002 * corner
        elif name == "O":
            d += _open(co, jaw, 0.012)
            d.x -= 0.35 * x * near
            d.y -= 0.006 * near
        elif name == "U":
            d += _open(co, jaw, 0.004)
            d.x -= 0.5 * x * near
            d.y -= 0.010 * near
        elif name == "FV":
            d += _open(co, jaw, 0.002)
            d.z += 0.005 * lo
            d.y += 0.005 * lo
        elif name == "MBP":
            d.z += 0.0025 * lo - 0.0015 * up
            d.y += 0.002 * near
        elif name == "smile":
            d.x += sx * 0.005 * corner
            d.z += 0.007 * corner
            d.y += 0.003 * corner
            for s in (-1, 1):
                cheek = gauss(
                    (x - s * 0.045) ** 2 + (co.z - 1.615) ** 2, 0.016
                ) * smoothstep(0.02, -0.05, co.y)
                d.z += 0.004 * cheek
                d.y -= 0.002 * cheek
            if "lid_L" in groups or "lid_R" in groups:
                d.z -= 0.0015  # slight squint
        elif name == "think":
            d.x += 0.004 * near
            d.z -= 0.002 * gauss((x + 0.02) ** 2 + (co.z - MOUTH_Z) ** 2, 0.007)
            if "brow_L" in groups:
                d.z += 0.006
            if "brow_R" in groups:
                d.z -= 0.002
            browskin = gauss((x - 0.034) ** 2 + (co.z - 1.69) ** 2, 0.012) * smoothstep(
                0.02, -0.05, co.y
            )
            d.z += 0.004 * browskin
        elif name == "blink":
            for s, g in ((1, "lid_L"), (-1, "lid_R")):
                if g in groups:
                    c = Vector((s * EYE_X, head_front_y(EYE_X, EYE_Z) + 0.0065, EYE_Z))
                    r = co - c
                    a = math.radians(72)
                    rot = Vector(
                        (
                            r.x,
                            r.y * math.cos(a) - r.z * math.sin(a),
                            r.y * math.sin(a) + r.z * math.cos(a),
                        )
                    )
                    return c + rot
        return co + d

    return fn


def stage_shape_keys():
    ob = bpy.data.objects.get("Grandpa_Head")
    if ob is None:
        raise RuntimeError("build the head first (stage_head)")
    me = ob.data
    if me.shape_keys:
        ob.shape_key_clear()
    names = {g.index: g.name for g in ob.vertex_groups}
    vgroups = [
        {names[g.group] for g in v.groups if g.weight > 0.5} for v in me.vertices
    ]
    base = [v.co.copy() for v in me.vertices]
    ob.shape_key_add(name="Basis", from_mix=False)
    for key in SHAPE_KEYS:
        fn = _key_fn(key)
        sk = ob.shape_key_add(name=key, from_mix=False)
        sk.value = 0.0  # Blender 5.x starts new keys at 1.0; the GLB must rest at 0
        sk.slider_min, sk.slider_max = 0.0, 1.0
        for i, co in enumerate(base):
            sk.data[i].co = fn(co, vgroups[i])
    return {"shape_keys": [k.name for k in me.shape_keys.key_blocks]}


# --------------------------------------------------------------------------
# export + checks
# --------------------------------------------------------------------------
def tri_count(ob):
    me = ob.data
    return sum(len(p.vertices) - 2 for p in me.polygons)


def report():
    c = collection()
    per = {o.name: tri_count(o) for o in c.objects if o.type == "MESH"}
    return {"triangles": per, "total": sum(per.values()), "budget": MAX_TRIANGLES}


def export_glb(path):
    rep = report()
    if rep["total"] > MAX_TRIANGLES:
        raise RuntimeError(f"{rep['total']} triangles > budget {MAX_TRIANGLES}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in collection().objects:
        o.select_set(True)
    kw = dict(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=False,  # meshes are already baked; keeps shape keys safe
        export_morph=True,
        export_morph_normal=False,
        export_animations=False,
        export_cameras=False,
        export_lights=False,
        export_yup=True,
    )
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        for k in ("export_animations", "export_morph_normal"):
            kw.pop(k, None)
        bpy.ops.export_scene.gltf(**kw)
    rep["path"] = path
    rep["bytes"] = os.path.getsize(path)
    return rep


def build_all():
    out = {}
    collection(reset=True)
    for st in (
        stage_body,
        stage_head,
        stage_hair,
        stage_glasses,
        stage_dress,
        stage_shape_keys,
    ):
        out.update(st())
    out.update(report())
    return out
