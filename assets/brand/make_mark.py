"""Build Grandpa's emblem: the outer sail shape and three tapered cuts."""
import math

def bez(p0, p1, p2, p3, t):
    u = 1 - t
    return tuple(u**3*a + 3*u*u*t*b + 3*u*t*t*c + t**3*d for a, b, c, d in zip(p0, p1, p2, p3))

def tapered(points, width):
    """Points along a centre line + width(t) -> a closed filled path."""
    n = len(points)
    left, right = [], []
    for i, (x, y) in enumerate(points):
        a = points[max(i - 1, 0)]; b = points[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        w = width(i / (n - 1)) / 2
        left.append((x + nx * w, y + ny * w)); right.append((x - nx * w, y - ny * w))
    ring = left + right[::-1]
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in ring) + " Z"

N = 48
junction = (392, 468)
# left cut: a curve, thickest in the middle, sharp at both ends
curve = [bez((138, 676), (226, 572), (316, 500), junction, i / N) for i in range(N + 1)]
cut1 = tapered(curve, lambda t: 2 + 15 * math.sin(math.pi * min(1, t * 1.08)) ** 0.8)
# up-right cut: from the junction to a sharp point near the top
up = [(junction[0] + (530 - junction[0]) * i / N, junction[1] + (262 - junction[1]) * i / N) for i in range(N + 1)]
cut2 = tapered(up, lambda t: 2 + 13 * (1 - t) ** 0.7)
# down-right cut: from the junction to a sharp point at the bottom
down = [(junction[0] + (594 - junction[0]) * i / N, junction[1] + (724 - junction[1]) * i / N) for i in range(N + 1)]
cut3 = tapered(down, lambda t: 2 + 15 * (1 - t) ** 0.6)

OUTER = ("M48 912 C 120 560, 380 222, 776 52 C 600 300, 548 610, 756 892 "
         "C 610 770, 480 660, 352 612 C 238 700, 130 800, 48 912 Z")

def mark_svg(fill, size=None, background=None, pad=0, radius=0):
    vb_w, vb_h = 800, 960
    if background:
        side = 1120
        ox, oy = (side - vb_w) / 2, (side - vb_h) / 2
        bg = f'<rect width="{side}" height="{side}" rx="{radius}" fill="{background}"/>'
        body = f'<g transform="translate({ox:.0f} {oy:.0f})">{shape(fill)}</g>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" role="img" aria-label="Grandpa">'
                f'<title>Grandpa</title>{bg}{body}</svg>\n')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" role="img" aria-label="Grandpa">'
            f'<title>Grandpa</title>{shape(fill)}</svg>\n')

def shape(fill):
    # The cuts are holes (a mask), so the mark works on any background; the
    # mask unions the three cuts, so where they meet stays cut.
    return ('<defs><mask id="grandpa-cuts" maskUnits="userSpaceOnUse" x="0" y="0" width="800" height="960">'
            '<rect width="800" height="960" fill="#fff"/>'
            f'<path fill="#000" d="{cut1} {cut2} {cut3}"/>'
            '<circle cx="392" cy="468" r="7.5" fill="#000"/></mask></defs>'
            f'<path fill="{fill}" mask="url(#grandpa-cuts)" d="{OUTER}"/>')

GOLD, BRIGHT, INK, SNOW = "#C9A618", "#FFD21F", "#0b0c0c", "#f8f9fa"
files = {
    "grandpa-mark.svg": mark_svg(GOLD),
    "grandpa-mark-bright.svg": mark_svg(BRIGHT),
    "grandpa-mark-black.svg": mark_svg(INK),
    "grandpa-mark-white.svg": mark_svg(SNOW),
    "grandpa-app-icon.svg": mark_svg(BRIGHT, background=INK, radius=248),
}
for name, text in files.items():
    open(name, "w").write(text)
# lockup: mark + wordmark
lock = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3180 960" role="img" aria-label="Grandpa">'
        f'<title>Grandpa</title>{shape(GOLD)}'
        f'<text x="900" y="640" font-family="Segoe UI, Inter, Helvetica, Arial, sans-serif" font-size="400" '
        f'font-weight="700" letter-spacing="24" fill="{INK}">GRANDPA</text></svg>\n')
open("grandpa-lockup.svg", "w").write(lock)
open("grandpa-lockup-dark.svg", "w").write(lock.replace(f'fill="{INK}">GRANDPA', f'fill="{SNOW}">GRANDPA').replace(GOLD, BRIGHT))
print(cut1[:80])
