// A2: Grandpa's ring as a WebGL shader.
//
// One quad, one fragment shader: a glowing ring drawn from its distance field,
// with a soft halo, a slow travelling highlight, a shimmer, and per-state
// motion. Raw WebGL rather than Three.js on purpose -- a single quad needs no
// scene graph, and the budget is <= 15% of a Ryzen 5 7520U's integrated GPU
// while Ollama is also using the machine. Three.js arrives with the 3D head
// (A3), which does need it.
//
// Budget rules, all enforced here:
//   * at most 30 frames per second (FRAME_MS), 20 in a resting state;
//   * nothing is drawn while the page is hidden (minimised or covered), and
//     with prefers-reduced-motion nothing once the colour has settled;
//   * the canvas is the ring's own size, at most 2x device pixels.
//
// window.GrandpaRing.create(canvas) returns { setState(msg), destroy(), stats }
// or null when WebGL is unavailable -- the CSS ring stays in that case.
"use strict";

(function () {
  const FRAME_MS = 1000 / 30;
  // Resting states breathe slowly; 20 fps is indistinguishable there and
  // a third cheaper for the hours the ring just sits on screen.
  const RESTING_FRAME_MS = 1000 / 20;
  const RESTING = new Set(["idle", "done", "error"]);
  const MAX_DPR = 2;

  // How each state moves. pulse: breathing amount; speed: how fast the
  // highlight travels; segments: a dashed ring that turns (working);
  // flicker: the quick waver of speech.
  const MOTION = {
    idle:      { pulse: 0.07, speed: 0.95, segments: 0, flicker: 0.0 },  // a visible, slow breath
    listening: { pulse: 0.06,  speed: 0.9,  segments: 0, flicker: 0.0 },
    thinking:  { pulse: 0.05,  speed: 1.4,  segments: 0, flicker: 0.0 },
    speaking:  { pulse: 0.03,  speed: 0.6,  segments: 0, flicker: 1.0 },
    working:   { pulse: 0.02,  speed: 0.5,  segments: 8, flicker: 0.0 },
    done:      { pulse: 0.02,  speed: 0.3,  segments: 0, flicker: 0.0 },
    error:     { pulse: 0.04,  speed: 0.2,  segments: 0, flicker: 0.0 },
    confirm:   { pulse: 0.07,  speed: 0.4,  segments: 0, flicker: 0.0 },
  };

  const VERTEX = `
    attribute vec2 aPos;
    varying vec2 vUv;
    void main() { vUv = aPos; gl_Position = vec4(aPos, 0.0, 1.0); }
  `;

  const FRAGMENT = `
    precision mediump float;
    varying vec2 vUv;
    uniform float uTime;
    uniform vec3  uColor;
    uniform float uPulse;
    uniform float uPhase;
    uniform float uSegments;
    uniform float uFlicker;
    uniform float uLevel;

    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    float noise(vec2 p) {
      vec2 i = floor(p); vec2 f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
                 mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
    }

    void main() {
      vec2 p = vUv;
      float r = length(p);
      float a = atan(p.y, p.x);

      float breathe = 1.0 + uPulse * sin(uTime * 1.6);
      float flick = uFlicker * (0.5 + 0.5 * sin(uTime * 23.0)) * 0.04;
      float radius = 0.66 * breathe + flick + uLevel * 0.05;
      float width = 0.075 + uLevel * 0.04;

      // shimmer: the edge wavers a little, slowly. Sampled on the unit circle,
      // not on the angle, so there is no seam where the angle wraps.
      vec2 dir = p / max(r, 1e-4);
      float wobble = (noise(dir * 2.2 + vec2(uTime * 0.6)) - 0.5) * 0.012;
      float d = abs(r - radius - wobble);

      float core = smoothstep(width, width * 0.35, d);
      float halo = exp(-d * 9.0) * 0.55;

      // a highlight that travels around the ring
      float travel = 0.5 + 0.5 * cos(a - uPhase);
      float highlight = pow(travel, 6.0) * 0.6;

      // working: a dashed ring that turns
      float dash = 1.0;
      if (uSegments > 0.5) {
        float s = fract((a + uPhase * 0.8) / 6.28318 * uSegments);
        dash = mix(0.25, 1.0, smoothstep(0.15, 0.25, s) * smoothstep(0.85, 0.75, s));
      }

      float glow = (core * (0.75 + highlight) * dash + halo * (0.6 + 0.4 * dash));
      vec3 colour = uColor * glow + vec3(1.0) * core * highlight * 0.35;
      float alpha = clamp(glow, 0.0, 1.0);
      gl_FragColor = vec4(colour * alpha, alpha);
    }
  `;

  function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return [0.9, 0.91, 0.92];
    const n = parseInt(m[1], 16);
    return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
  }

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error("ring shader: " + log);
    }
    return shader;
  }

  function create(canvas) {
    let gl = null;
    try {
      gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: "low-power" });
    } catch (_) { gl = null; }
    if (!gl) return null;

    let program;
    try {
      program = gl.createProgram();
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    } catch (_) {
      return null;
    }
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    const u = {};
    for (const name of ["uTime", "uColor", "uPulse", "uPhase", "uSegments", "uFlicker", "uLevel"]) {
      u[name] = gl.getUniformLocation(program, name);
    }

    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const stats = { frames: 0, running: false };
    const target = { colour: [0.9, 0.91, 0.92], motion: MOTION.idle, state: "idle" };
    const current = { colour: target.colour.slice(), pulse: 0.025, speed: 0.25, segments: 0, flicker: 0 };
    let phase = 0;
    let started = performance.now();
    let last = 0;
    let lastTick = started;
    let raf = 0;
    let destroyed = false;
    let paused = false; // A3: the character is showing instead of the ring

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w; canvas.height = h;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function approach(from, to, k) { return from + (to - from) * k; }

    function draw(now) {
      const dt = Math.min((now - lastTick) / 1000, 0.1);
      lastTick = now;
      const k = 1 - Math.pow(0.001, dt); // ~ settles in a second
      for (let i = 0; i < 3; i++) current.colour[i] = approach(current.colour[i], target.colour[i], k);
      current.pulse = approach(current.pulse, target.motion.pulse, k);
      current.speed = approach(current.speed, target.motion.speed, k);
      current.flicker = approach(current.flicker, target.motion.flicker, k);
      current.segments = target.motion.segments; // a dash count does not blend
      phase += current.speed * dt * (reduceMotion ? 0 : 1);

      resize();
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(u.uTime, reduceMotion ? 0 : (now - started) / 1000);
      gl.uniform3fv(u.uColor, current.colour);
      gl.uniform1f(u.uPulse, reduceMotion ? 0 : current.pulse);
      gl.uniform1f(u.uPhase, phase);
      gl.uniform1f(u.uSegments, current.segments);
      gl.uniform1f(u.uFlicker, reduceMotion ? 0 : current.flicker);
      gl.uniform1f(u.uLevel, 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      stats.frames += 1;
    }

    function settled() {
      for (let i = 0; i < 3; i++) if (Math.abs(current.colour[i] - target.colour[i]) > 0.002) return false;
      return true;
    }

    function loop(now) {
      raf = 0;
      if (destroyed || paused || document.hidden) { stats.running = false; return; }
      const budget = RESTING.has(target.state) ? RESTING_FRAME_MS : FRAME_MS;
      if (now - last >= budget - 1) {
        last = now;
        draw(now);
      }
      if (reduceMotion && settled()) { stats.running = false; return; }
      raf = requestAnimationFrame(loop);
      stats.running = true;
    }

    function start() {
      if (destroyed || paused || raf || document.hidden) return;
      lastTick = performance.now();
      raf = requestAnimationFrame(loop);
      stats.running = true;
    }

    function onVisibility() {
      if (document.hidden) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        stats.running = false;
      } else {
        start();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); destroy(); });

    function setState(msg) {
      target.colour = hexToRgb(msg && msg.colour);
      const state = (msg && msg.state) || "idle";
      target.state = MOTION[state] ? state : "idle";
      target.motion = MOTION[target.state];
      start();
    }

    function destroy() {
      destroyed = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      stats.running = false;
      document.removeEventListener("visibilitychange", onVisibility);
    }

    start();
    // A3: while the character is on screen the ring draws nothing at all.
    function setPaused(value) {
      paused = Boolean(value);
      if (paused) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        stats.running = false;
      } else {
        start();
      }
    }

    return { setState, setPaused, destroy, stats };
  }

  window.GrandpaRing = { create, FRAME_MS, RESTING_FRAME_MS, MOTION };
})();
