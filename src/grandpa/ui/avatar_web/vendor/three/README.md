three.js r169 (npm `three@0.169.0`, MIT, see LICENSE), vendored so the avatar
page loads nothing from the internet.

- `three.module.min.js` is `build/three.module.min.js`, unchanged.
- `GLTFLoader.js` and `BufferGeometryUtils.js` are from `examples/jsm/`; the only
  change is their import lines, which point at the files next to them instead
  of the bare `'three'` specifier (the page's CSP allows no import map).

`SHA256SUMS` pins all four; `tests/ui/test_avatar_character.py` checks them.
