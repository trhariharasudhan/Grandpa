// A3: Grandpa's character -- the 3D head that replaces the ring while he is
// thinking, speaking, working or asking. The ring stays for idle, listening,
// done and error. (A5 makes the swap a morph; this is a plain swap.)
//
// Two sources, one pipeline:
//   * a placeholder head built here from a few low-poly shapes (an original
//     wise old grandpa: white hair and beard, round glasses), so the window
//     always has a character;
//   * Captain's assets/avatar/grandpa.glb, when he has made one. Python checks
//     it (glTF 2.0, <= 30k triangles, embedded, size) and sends it over the
//     page's own WebSocket; avatar.js hands it over as "grandpa:character".
// Both breathe and blink. A .glb blinks with its "blink" shape key when it has
// one; smile and think are for A6.
//
// A4, lip-sync: a "speaking" state carries a mouth track from Python
// ({t: ms, v: viseme, w: 0..1}) and speech_start_ms, when playback starts by
// this PC's clock. The mouth follows Date.now() - speech_start_ms, so the
// socket's delay does not shift it. A .glb moves its AA/E/I/O/U/FV/MBP shape
// keys; the placeholder opens, widens and rounds its own mouth.
//
// Budget, as for the ring (Ryzen 5 7520U iGPU, shared with Ollama):
//   * at most 30 frames per second, 20 while waiting for a yes/no;
//   * nothing drawn while the character is not on screen or the page is hidden;
//   * canvas at most 2x device pixels, low-power context, no antialiasing.
//
// If WebGL or three.js fails, nothing changes: the ring keeps showing.
import * as THREE from "./vendor/three/three.module.min.js";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";

const FRAME_MS = 1000 / 30;
const WAITING_FRAME_MS = 1000 / 20;
const MAX_DPR = 2;
const MAX_TRIANGLES = 30000;
const SHOW_IN = new Set(["thinking", "speaking", "working", "confirm"]);
const BLINK_MS = 150;
const VISEMES = ["AA", "E", "I", "O", "U", "FV", "MBP"];
const MAX_TRACK = 2000;
const MOUTH_EASE = 0.6; // per frame at 30 fps: about one frame behind the sound

// The placeholder's mouth per viseme: [open, wide] at full weight.
const MOUTH = {
  AA: [1.0, 0.8], E: [0.5, 1.0], I: [0.35, 1.1], O: [0.8, 0.55],
  U: [0.4, 0.45], FV: [0.12, 0.9], MBP: [0.0, 0.8], rest: [0.0, 0.8],
};

// Python's track, checked: only known shapes, numeric times, in order.
function cleanTrack(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const entry of raw.slice(0, MAX_TRACK)) {
    if (!entry || typeof entry !== "object") continue;
    const t = Number(entry.t), w = Number(entry.w);
    const v = entry.v === "rest" || VISEMES.includes(entry.v) ? entry.v : null;
    if (!v || !Number.isFinite(t) || !Number.isFinite(w)) continue;
    if (out.length && t < out[out.length - 1].t) continue;
    out.push({ t, v, w: Math.max(0, Math.min(1, w)) });
  }
  return out;
}

// How the head holds itself per state: [tilt (z), nod (x)] in radians.
const POSE = {
  thinking: [0.10, -0.10],
  speaking: [0.0, 0.0],
  working:  [0.0, 0.12],
  confirm:  [-0.06, 0.0],
};

const app = document.getElementById("app");
const canvas = document.getElementById("char-gl");

function countTriangles(root) {
  let total = 0;
  root.traverse((node) => {
    if (!node.isMesh || !node.geometry) return;
    const g = node.geometry;
    const n = g.index ? g.index.count : (g.attributes.position ? g.attributes.position.count : 0);
    total += Math.floor(n / 3);
  });
  return total;
}

// --- the placeholder head ---------------------------------------------------

function buildPlaceholder() {
  const head = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0xd8a585, roughness: 0.85, flatShading: true });
  const white = new THREE.MeshStandardMaterial({ color: 0xeceae4, roughness: 1.0, flatShading: true });
  const dark = new THREE.MeshStandardMaterial({ color: 0x2a2320, roughness: 0.5, flatShading: true });
  const gold = new THREE.MeshStandardMaterial({ color: 0xc9a54a, roughness: 0.35, metalness: 0.8, flatShading: true });

  const skull = new THREE.Mesh(new THREE.IcosahedronGeometry(1, 2), skin);
  skull.scale.set(0.84, 1.0, 0.9);
  head.add(skull);

  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.32, 5), skin);
  nose.rotation.x = Math.PI / 2;
  nose.position.set(0, -0.05, 0.92);
  head.add(nose);

  for (const side of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.IcosahedronGeometry(0.16, 0), skin);
    ear.scale.set(0.5, 1, 0.8);
    ear.position.set(side * 0.84, 0.0, 0.0);
    head.add(ear);

    // white hair at the temples and back: bald on top, as grandpas are
    const tuft = new THREE.Mesh(new THREE.IcosahedronGeometry(0.34, 0), white);
    tuft.scale.set(0.7, 1.0, 1.2);
    tuft.position.set(side * 0.74, 0.28, -0.2);
    head.add(tuft);

    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.07, 0.08), white);
    brow.position.set(side * 0.3, 0.33, 0.83);
    brow.rotation.z = side * -0.12;
    head.add(brow);
  }
  const back = new THREE.Mesh(new THREE.IcosahedronGeometry(0.6, 0), white);
  back.scale.set(1.3, 0.8, 0.6);
  back.position.set(0, 0.05, -0.62);
  head.add(back);

  const beard = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62, 1), white);
  beard.scale.set(1.15, 0.95, 0.75);
  beard.position.set(0, -0.72, 0.38);
  head.add(beard);
  const moustache = new THREE.Mesh(new THREE.IcosahedronGeometry(0.2, 0), white);
  moustache.scale.set(2.0, 0.55, 0.7);
  moustache.position.set(0, -0.3, 0.86);
  head.add(moustache);
  // the mouth, under the moustache: a dark lens that opens with the words
  const mouth = new THREE.Mesh(new THREE.SphereGeometry(0.12, 10, 6), dark);
  mouth.position.set(0, -0.46, 0.84);
  mouth.scale.set(1.0, 0.06, 0.45);
  head.add(mouth);

  // eyes (they blink by squashing), behind round gold glasses
  const eyes = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.075, 8, 6), dark);
    eye.position.set(side * 0.3, 0.14, 0.86);
    head.add(eye);
    eyes.push(eye);

    const rim = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.025, 4, 14), gold);
    rim.position.set(side * 0.3, 0.14, 0.95);
    head.add(rim);

    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.85), gold);
    arm.position.set(side * 0.5, 0.16, 0.52);
    head.add(arm);
  }
  const bridge = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.025, 0.025), gold);
  bridge.position.set(0, 0.18, 0.97);
  head.add(bridge);

  head.position.y = 0.12;
  return {
    root: head,
    kind: "placeholder",
    setBlink(closed) { for (const eye of eyes) eye.scale.y = 1 - 0.9 * closed; },
    setMouth(weights) {
      let open = 0, wide = 0, total = 0;
      for (const [name, w] of Object.entries(weights)) {
        const shape = MOUTH[name];
        if (!shape || w <= 0) continue;
        open += shape[0] * w; wide += shape[1] * w; total += w;
      }
      const width = total > 0 ? wide / total : MOUTH.rest[1];
      mouth.scale.set(0.55 + 0.6 * width, 0.06 + 0.9 * Math.min(1, open), 0.45);
    },
  };
}

// --- Captain's .glb ---------------------------------------------------------

const FRAME_NODE = "Grandpa_Head";
const BUST_BELOW_HEAD = 0.7; // chest kept below the head, in head heights (the camera shows ~1.5x the box)

function frameBox(root) {
  const whole = new THREE.Box3().setFromObject(root);
  const head = root.getObjectByName(FRAME_NODE);
  if (!head) return whole;
  const hb = new THREE.Box3().setFromObject(head);
  const h = hb.max.y - hb.min.y;
  if (!(h > 0) || h > 0.6 * (whole.max.y - whole.min.y)) return whole; // a head-only model
  const bottom = hb.min.y - BUST_BELOW_HEAD * h;
  const c = hb.getCenter(new THREE.Vector3());
  const half = (hb.max.y - bottom) / 2;
  return new THREE.Box3(
    new THREE.Vector3(c.x - half, bottom, c.z - half),
    new THREE.Vector3(c.x + half, hb.max.y, c.z + half),
  );
}

function fromGltf(gltf) {
  const root = gltf.scene || (gltf.scenes && gltf.scenes[0]);
  if (!root) throw new Error("no scene");
  const triangles = countTriangles(root);
  if (triangles === 0 || triangles > MAX_TRIANGLES) throw new Error("triangle budget");

  // fit it into the same space as the placeholder: about 2.3 units tall, centred.
  // A full-body model with a head node is framed head-and-chest instead (A3b),
  // or the face would be a few pixels in the small window.
  root.updateMatrixWorld(true);
  const box = frameBox(root);
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const scale = 2.3 / Math.max(size.x, size.y, size.z, 1e-6);
  const holder = new THREE.Group();
  root.position.sub(centre);
  holder.add(root);
  holder.scale.setScalar(scale);

  const blinkers = [];
  const mouthKeys = []; // [node, index, viseme]
  root.traverse((node) => {
    if (!node.isMesh || !node.morphTargetDictionary || !node.morphTargetInfluences) return;
    for (const [name, index] of Object.entries(node.morphTargetDictionary)) {
      if (name.toLowerCase() === "blink") blinkers.push([node, index]);
      const viseme = VISEMES.find((v) => v.toLowerCase() === name.toLowerCase());
      if (viseme) mouthKeys.push([node, index, viseme]);
    }
  });
  return {
    root: holder,
    kind: "glb",
    setBlink(closed) { for (const [node, index] of blinkers) node.morphTargetInfluences[index] = closed; },
    setMouth(weights) {
      for (const [node, index, viseme] of mouthKeys) node.morphTargetInfluences[index] = weights[viseme] || 0;
    },
  };
}

// --- the renderer -------------------------------------------------------------

function create() {
  if (!canvas || !app) return null;
  const renderer = new THREE.WebGLRenderer({
    canvas, alpha: true, antialias: false, powerPreference: "low-power", premultipliedAlpha: true,
  });
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  camera.position.set(0, 0, 6.4);
  scene.add(new THREE.HemisphereLight(0xfff4e8, 0x30344a, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(1.5, 2, 3);
  scene.add(key);
  // the state colour lights him from behind, so he glows like the ring
  const rim = new THREE.DirectionalLight(0xe5e7eb, 1.4);
  rim.position.set(-1.5, 1, -2.5);
  scene.add(rim);

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const stats = {
    frames: 0, running: false, kind: "placeholder", triangles: 0, shown: false,
    viseme: "rest", mouthOpen: 0, speechMs: -1,
  };
  let character = null;
  let speech = null; // { track, start, i }
  const mouth = {}; // eased weights per viseme
  let state = "idle";
  let shown = false;
  let raf = 0;
  let last = 0;
  const started = performance.now();
  let nextBlink = started + 1500;
  const pose = { tilt: 0, nod: 0 };
  const rimTarget = new THREE.Color(0xe5e7eb);

  function use(next) {
    if (character) {
      scene.remove(character.root);
      character.root.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) [].concat(node.material).forEach((m) => m.dispose());
      });
    }
    character = next;
    scene.add(character.root);
    stats.kind = character.kind;
    stats.triangles = countTriangles(character.root);
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(dpr);
    const size = renderer.getSize(new THREE.Vector2());
    if (size.x !== w || size.y !== h) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }

  function draw(now) {
    const t = (now - started) / 1000;
    const k = 0.12;
    const target = POSE[state] || [0, 0];
    pose.tilt += (target[0] - pose.tilt) * k;
    pose.nod += (target[1] - pose.nod) * k;
    rim.color.lerp(rimTarget, k);

    const root = character.root;
    const breathe = reduceMotion ? 0 : Math.sin(t * 1.6);
    root.position.y = (character.kind === "placeholder" ? 0.12 : 0) + breathe * 0.02;
    root.rotation.set(pose.nod, reduceMotion ? 0 : Math.sin(t * 0.35) * 0.12, pose.tilt);

    let closed = 0;
    if (now >= nextBlink) {
      const p = (now - nextBlink) / BLINK_MS;
      if (p >= 1) nextBlink = now + 2500 + Math.random() * 3500;
      else closed = p < 0.5 ? p * 2 : (1 - p) * 2;
    }
    character.setBlink(closed);
    speak();

    resize();
    renderer.render(scene, camera);
    stats.frames += 1;
  }

  // Where the mouth should be now, from the track and this PC's clock.
  function speak() {
    let target = "rest", weight = 0;
    stats.speechMs = -1;
    if (speech && state === "speaking") {
      const elapsed = Date.now() - speech.start;
      const track = speech.track;
      stats.speechMs = elapsed;
      if (elapsed >= 0 && track.length) {
        while (speech.i + 1 < track.length && track[speech.i + 1].t <= elapsed) speech.i += 1;
        if (elapsed < track[track.length - 1].t) {
          target = track[speech.i].v;
          weight = track[speech.i].w;
        }
      }
    }
    for (const v of VISEMES) {
      const goal = v === target ? weight : 0;
      mouth[v] = (mouth[v] || 0) + (goal - (mouth[v] || 0)) * MOUTH_EASE;
    }
    character.setMouth(mouth);
    stats.viseme = weight > 0 ? target : "rest";
    stats.mouthOpen = VISEMES.reduce((sum, v) => sum + mouth[v] * (MOUTH[v][0]), 0);
  }

  function loop(now) {
    raf = 0;
    if (!shown || document.hidden) { stats.running = false; return; }
    const budget = state === "confirm" ? WAITING_FRAME_MS : FRAME_MS;
    if (now - last >= budget - 1) {
      last = now;
      draw(now);
      if (reduceMotion) { stats.running = false; return; } // one still frame
    }
    raf = requestAnimationFrame(loop);
    stats.running = true;
  }

  function start() {
    if (raf || !shown || document.hidden) return;
    raf = requestAnimationFrame(loop);
    stats.running = true;
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    stats.running = false;
  }

  function show(value) {
    if (value === shown) { if (shown) start(); return; }
    shown = value;
    stats.shown = value;
    app.classList.toggle("char", value);
    const ring = window.__grandpaRing;
    if (ring && ring.setPaused) ring.setPaused(value);
    if (value) start(); else stop();
  }

  function setState(msg) {
    state = (msg && msg.state) || "idle";
    if (state === "speaking") {
      const start = Number(msg.speech_start_ms);
      speech = { track: cleanTrack(msg.visemes), start: Number.isFinite(start) && start > 0 ? start : Date.now(), i: 0 };
    } else {
      speech = null;
    }
    if (msg && /^#[0-9a-f]{6}$/i.test(msg.colour || "")) rimTarget.set(msg.colour);
    show(SHOW_IN.has(state));
  }

  function load(buffer) {
    if (!(buffer instanceof ArrayBuffer)) return;
    new GLTFLoader().parse(buffer, "", (gltf) => {
      try { use(fromGltf(gltf)); start(); } catch (_) { /* keep the placeholder */ }
    }, () => { /* keep the placeholder */ });
  }

  function destroy() {
    show(false);
    renderer.dispose();
  }

  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); else start(); });
  canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); destroy(); });

  use(buildPlaceholder());
  return { setState, load, destroy, stats };
}

let api = null;
try { api = create(); } catch (_) { api = null; }
window.__grandpaCharacter = api; // read by the page tests, never by Python
if (api) {
  document.addEventListener("grandpa:state", (event) => api.setState(event.detail));
  document.addEventListener("grandpa:character", (event) => api.load(event.detail));
  if (window.__grandpaGlb) api.load(window.__grandpaGlb);
  if (window.__grandpaState) api.setState(window.__grandpaState);
}
