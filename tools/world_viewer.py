#!/usr/bin/env python3
"""Build a self-contained interactive 3D viewer (single .html) from a world's layered map.

Performance design (targets the "10 fps + hitch on key press" problem):
  * the canvas is allocated ONCE; no per-frame resize, so pressing keys never reallocates
  * the scene renders into an FBO at a fixed internal scale, then a cheap blit upscales it
  * quality is a uniform (march step count), not a resolution change -> zero reallocation
  * HUD prints the real WebGL renderer string, so a software fallback (SwiftShader) is obvious

Layers stay separate: ground drives geometry, water is a plane per column, canopy only tints.

Usage:
  python world_viewer.py "<world-dir>" --region r.0.0 --out preview/viewer.html
"""
from __future__ import annotations

import argparse
import base64
import io
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402
from terrain_metrics import compute as compute_metrics, summary_line  # noqa: E402

HMIN, HSCALE = -64.0, 384.0


def atlas_image() -> Image.Image:
    """256x256 atlas, 16x16 tiles: slot = id*2 (top) and id*2+1 (side).

    Each tile is rescaled so its average matches the palette colour, which keeps the flat
    (far) and textured (near) versions consistent, and lets grayscale grass tiles pick up
    the biome tint that was baked into the palette.
    """
    import json
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from block_palette import BLOCKS, SIDE

    base = Path(__file__).parent.parent
    data = json.loads((base / "_palette" / "palette.json").read_text(encoding="utf-8"))
    cols, sides = data["colors"], data.get("side", {})
    names = sorted(cols)
    cache = base / "_palette"

    atlas = np.zeros((256, 256, 4), dtype=np.uint8)

    def load_tile(name: str, want_side: bool):
        path = SIDE.get(name) if want_side else None
        if not path:
            path = BLOCKS.get(name, (None, None))[0]
        if not path:
            return None
        f = cache / Path(path).name
        if not f.exists():
            return None
        im = Image.open(f).convert("RGBA")
        if im.width > im.height:                        # animated strip -> first frame
            im = im.crop((0, 0, im.height, im.height))
        if im.size != (16, 16):
            im = im.resize((16, 16), Image.NEAREST)
        return np.asarray(im).astype(np.float32) / 255.0

    for i, name in enumerate(names):
        for want_side in (False, True):
            tile = load_tile(name, want_side)
            target = np.array((sides.get(name, cols[name]) if want_side else cols[name])[:3],
                              dtype=np.float32)
            if tile is None:
                tile = np.zeros((16, 16, 4), dtype=np.float32)
                tile[..., 3] = 1.0
            rgb, alpha = tile[..., :3], tile[..., 3:4]
            avg = (rgb * alpha).sum(axis=(0, 1)) / max(float(alpha.sum()), 1e-6)
            scale = np.clip(target / np.maximum(avg, 1e-3), 0.35, 2.5)
            rgb = np.clip(rgb * scale, 0.0, 1.0)
            tile = np.concatenate([rgb, alpha], axis=2)
            slot = i * 2 + (1 if want_side else 0)
            sx, sy = (slot % 16) * 16, (slot // 16) * 16
            atlas[sy : sy + 16, sx : sx + 16] = (tile * 255).astype(np.uint8)
    return Image.fromarray(atlas, "RGBA")


def palette_image() -> Image.Image:
    """256x1 RGBA: id -> albedo (real texture colours), unknown = neutral grey."""
    import json
    path = Path(__file__).parent.parent / "_palette" / "palette.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cols = data["colors"]
    unknown = data.get("unknown", [0.35, 0.35, 0.36])
    side = data.get("side", {})
    buf = np.zeros((2, 256, 4), dtype=np.uint8)      # row 0 = top faces, row 1 = sides
    for i, name in enumerate(sorted(cols)):
        if i >= 255:
            break
        r, g, b = cols[name][:3]
        buf[0, i] = [int(r * 255), int(g * 255), int(b * 255), 255]
        sr, sg, sb = side.get(name, cols[name])[:3]
        buf[1, i] = [int(sr * 255), int(sg * 255), int(sb * 255), 255]
    fallback = [int(unknown[0] * 255), int(unknown[1] * 255), int(unknown[2] * 255), 255]
    for i in range(len(cols), 255):
        buf[0, i] = fallback
        buf[1, i] = fallback
    buf[0, 255] = fallback
    buf[1, 255] = fallback
    return Image.fromarray(buf, "RGBA")


def encode_id(sid) -> Image.Image:
    """R = block id (0..255), opaque."""
    r = sid.astype(np.uint8)
    zeros = np.zeros_like(r)
    full = np.full_like(r, 255)
    return Image.fromarray(np.stack([r, zeros, zeros, full], axis=2), "RGBA")


def encode(ground, water, flags) -> Image.Image:
    """R,G = 14-bit height + 2-bit class | B = water height | A = 255 (opaque)."""
    v = np.round(np.clip((ground - HMIN) / HSCALE, 0, 1) * 16383).astype(np.uint16)
    cls = np.zeros_like(v, dtype=np.uint16)
    cls[(flags & 4) > 0] = 3            # canopy
    cls[(flags & 2) > 0] = 2            # ice wins over canopy
    cls[(flags & 1) > 0] = 1            # snow wins over both
    r = ((v >> 6) & 0xFF).astype(np.uint8)
    g = (((v & 0x3F) << 2) | cls).astype(np.uint8)
    valid = water > -1000
    b = np.where(valid, np.round(np.clip((water - HMIN) / HSCALE, 0, 1) * 255), 0).astype(np.uint8)
    a = np.full_like(r, 255)
    rgba = np.stack([r, g, b, a], axis=2).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def half(a: np.ndarray) -> np.ndarray:
    """2x2 box downsample; sizes must be even."""
    h, w = a.shape
    return a[: h - h % 2, : w - w % 2].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))


def mip_pyramid(ground, water, canopy, min_size: int = 1):
    """Decoded-layer mip chain. Encoding each level separately keeps the 16-bit height valid
    (averaging the packed R/G bytes independently would corrupt it)."""
    levels = []
    g, w, c = ground, water, canopy
    while True:
        levels.append((g, w, c))
        if min(g.shape) <= min_size:      # WebGL1 needs the chain down to 1x1
            break
        g, w, c = half(g), half(w), half(c)
    return levels


def to_pot(a: np.ndarray) -> np.ndarray:
    """WebGL1 mipmaps need power-of-two dimensions."""
    h, w = a.shape
    ph = 1 << (h - 1).bit_length()
    pw = 1 << (w - 1).bit_length()
    if ph == h and pw == w:
        return a
    out = np.full((ph, pw), float(a.min()), dtype=np.float32)
    out[:h, :w] = a
    return out


def best_view(ground, water):
    hh, ww = ground.shape
    k = 9
    pad = np.pad(ground, k // 2, mode="edge")
    blur = np.zeros_like(ground)
    for dz in range(k):
        for dx in range(k):
            blur += pad[dz : dz + hh, dx : dx + ww]
    blur /= k * k
    margin = max(16, min(hh, ww) // 5)
    inner = np.zeros_like(ground, dtype=bool)
    inner[margin : hh - margin, margin : ww - margin] = True
    score = np.where(inner, blur, -1e9).ravel()
    cand = np.argsort(score)[-40:][::-1]

    rs = np.arange(2.0, min(1400.0, min(hh, ww) * 0.9), 3.0)
    best = (-1e9, ww // 2, hh // 2, 0.0)
    for idx in cand:
        z, x = divmod(int(idx), ww)
        eye_y = ground[z, x] + 2.0
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            xs = np.clip((x + math.sin(rad) * rs).astype(np.int32), 0, ww - 2)
            zs = np.clip((z + math.cos(rad) * rs).astype(np.int32), 0, hh - 2)
            prof = ground[zs, xs]
            blocked = prof > (eye_y + np.tan(math.radians(3.0)) * rs)
            dist = float(rs[np.argmax(blocked)]) if blocked.any() else float(rs[-1])
            if dist > best[0]:
                best = (dist, x, z, float(deg))
    return best[1], best[2], best[3]


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>地形查看器 — __NAME__</title>
<style>
 html,body{margin:0;height:100%;background:#0b0b0c;overflow:hidden;font:13px/1.5 system-ui,sans-serif;color:#ddd}
 canvas{display:block;width:100vw;height:100vh;cursor:grab}
 canvas.drag{cursor:grabbing}
 #hud{position:fixed;left:12px;top:12px;background:rgba(12,12,14,.72);padding:10px 12px;border-radius:8px;
      pointer-events:none;line-height:1.6;font-variant-numeric:tabular-nums;max-width:min(660px,70vw)}
 #hud b{color:#8fd3ff;font-weight:600}
 #hud .gpu{color:#9cc;font-size:11px;display:block;max-width:360px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 #tip{position:fixed;left:12px;bottom:12px;background:rgba(12,12,14,.72);padding:8px 12px;border-radius:8px;
      pointer-events:none;color:#9aa}
 kbd{background:#222;border:1px solid #333;border-radius:4px;padding:0 4px;font-size:11px}
 #ctl{position:fixed;right:12px;bottom:12px;background:rgba(12,12,14,.78);padding:9px 12px;border-radius:8px;
      display:flex;align-items:center;gap:9px;font-size:12px;color:#bbb}
 #ctl input[type=range]{width:150px;accent-color:#6cf}
 #ctl b{color:#8fd3ff;font-variant-numeric:tabular-nums;min-width:34px;display:inline-block;text-align:right}
</style></head><body>
<canvas id="c" class="drag"></canvas>
<div id="hud"></div>
<div id="ctl"><span>速度</span><input id="spd" type="range" min="1" max="120" step="1" value="26"><b id="spdv">26</b><span>格/秒</span></div>
<div id="tip">拖拽=转视角 · 滚轮=缩放 · <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd>移动 · <kbd>空格</kbd>升 <kbd>Shift</kbd>降 · <kbd>F</kbd>自由飞行 · <kbd>R</kbd>最佳机位 · <kbd>[</kbd><kbd>]</kbd>调速</div>
<script>
const TEXW = __NW__, TEXH = __NH__;               // map extent (= texture size)
const MAPW = __MAPW__, MAPH = __MAPH__;           // real map extent in blocks
const METRICS = "__METRICS__";
const HOME = {x:__EX__, z:__EZ__, y:__EY__, yaw:__YAW__, pitch:-12};
function loadTex(b64){
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = "data:image/png;base64," + b64;
  });
}
let IMG = null, IMG_ID = null, IMG_PAL = null, IMG_ATL = null;
Promise.all([
  loadTex("__B64__"), loadTex("__IDB64__"), loadTex("__PALB64__"), loadTex("__ATLB64__")
]).then(([a, b, c, d]) => { IMG = a; IMG_ID = b; IMG_PAL = c; IMG_ATL = d; fillHeights(); start(); })
  .catch(() => { document.getElementById('hud').innerHTML = '<b>纹理加载失败</b>'; });

const c = document.getElementById('c');
const gl = c.getContext('webgl', {antialias:false, preserveDrawingBuffer:false, powerPreference:'high-performance'});
if(!gl){ document.body.innerHTML = '<p style="padding:20px">这个浏览器没有 WebGL 支持。</p>'; }

let GPU = 'unknown';
try {
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  if(ext) GPU = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL));
} catch(e) {}

const VS = "attribute vec2 a; void main(){ gl_Position = vec4(a,0.0,1.0); }";

const SCENE_FS = `
precision highp float;
uniform sampler2D uTex;
uniform sampler2D uId;
uniform sampler2D uPal;
uniform sampler2D uAtlas;
uniform float uDetailDist;
uniform vec2 uRes;
uniform vec3 uEye;
uniform float uYaw, uPitch, uFov, uSnow, uNoWater, uDbg, uFade, uBelow, uDbgId;
uniform vec2 uMapSize;

const float HMIN=-64.0, HSCALE=384.0;
const vec2 TSIZE = vec2(__NW__.0, __NH__.0);
const vec3 SUN = normalize(vec3(0.45,0.55,-0.70));

float groundH(vec2 uv){
  vec4 t = texture2D(uTex, uv);
  float v = floor(t.r*255.0 + 0.5)*64.0 + floor(t.g*255.0/4.0 + 0.5);
  return v/16383.0*HSCALE + HMIN;
}
float clsOf(vec4 t){ return mod(floor(t.g*255.0 + 0.5), 4.0); }
vec4 sampleShade(vec2 uv){ return texture2D(uTex, uv); }

void main(){
  vec2 uv = gl_FragCoord.xy/uRes;
  vec2 p = uv*2.0-1.0;
  float asp = uRes.x/uRes.y;
  float tf = tan(radians(uFov)*0.5);
  vec3 fwd = vec3(cos(uPitch)*sin(uYaw), sin(uPitch), cos(uPitch)*cos(uYaw));
  vec3 right = normalize(cross(fwd, vec3(0.0,1.0,0.0)));
  vec3 up = cross(right, fwd);
  vec3 dir = normalize(fwd + p.x*tf*asp*right + p.y*tf*up);

  float hz = clamp(1.0 - uv.y, 0.0, 1.0);
  vec3 sky = mix(vec3(0.42,0.58,0.80), vec3(0.80,0.87,0.93), hz);
  sky += pow(max(dot(dir, SUN), 0.0), 8.0)*vec3(0.50,0.40,0.20);
  sky = mix(sky, vec3(0.88,0.89,0.88), pow(hz,6.0)*0.55);

  // per-pixel dither breaks any residual periodicity in the sample positions
  float jitter = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898,78.233)))*43758.5453);
  float t = 0.6;
  float prevT = t;
  float hitT = -1.0, hitH = 0.0;
  vec2 hitUV = vec2(0.0);
  float horiz = max(length(dir.xz), 0.02);
  for(int i=0;i<220;i++){
    vec3 pos = uEye + dir*t;
    if(pos.x<0.0||pos.x>uMapSize.x||pos.z<0.0||pos.z>uMapSize.y){ break; }
    vec2 q = pos.xz/TSIZE;
    float g = groundH(q);
    float d = pos.y - g;                       // vertical clearance to the surface
    if(d < 0.0 && g > -63.0){ hitT = t; hitH = g; hitUV = q; break; }
    prevT = t;
    // a heightfield can rise at most SLOPE per horizontal unit, so the ray can
    // safely advance d/(SLOPE*horiz) before it could possibly touch the surface
    float stepLen = clamp(0.9 * d / (9.0 * horiz), 0.25, 220.0);
    stepLen = max(stepLen, t * 0.015);   // keep far-field cost bounded
    t += stepLen;
    if(t > 2800.0){ break; }
  }
  if(hitT>0.0){
    float a = prevT, b = hitT;
    for(int i=0;i<6;i++){
      float m = 0.5*(a+b);
      vec3 pos = uEye + dir*m;
      float g = groundH(pos.xz/TSIZE);
      bool ins2 = (uBelow > 0.5) ? (pos.y > g) : (pos.y < g);
      if(ins2 && g > -63.0){ b = m; } else { a = m; }
    }
    hitT = b;
    vec3 hitPos = uEye + dir*hitT;
    hitUV = hitPos.xz/TSIZE;
    hitH = groundH(hitUV);
  }

  vec4 tex = hitT>0.0 ? sampleShade(hitUV) : vec4(0.0);
  float waterH = tex.b > 0.001 ? tex.b*HSCALE + HMIN : -1e4;
  float cls = clsOf(tex);
  bool onSnow = cls > 0.5 && cls < 1.5;
  bool onIce  = cls > 1.5 && cls < 2.5;
  bool onCano = cls > 2.5;

  float waterT = -1.0;
  if(uNoWater < 0.5 && hitT>0.0 && waterH > hitH + 0.5 && waterH < hitH + 64.0 && dir.y < -1e-4){
    float tw = (waterH - uEye.y)/dir.y;
    if(tw > 0.0 && tw < hitT){ waterT = tw; }
  }

  vec3 col = sky;
  if(waterT>0.0){
    float fres = pow(1.0 - max(dir.y, 0.0), 3.0);
    vec3 wcol = onIce ? vec3(0.70,0.83,0.92) : vec3(0.10,0.22,0.30);
    col = wcol*0.80 + sky*fres*0.55;
    col = mix(col, sky, clamp(1.0 - exp(-waterT*0.00035), 0.0, 0.88));
  } else if(hitT>0.0){
    vec2 e2 = 2.0/TSIZE;
    float gx = groundH(hitUV+vec2(e2.x,0.0)) - groundH(hitUV-vec2(e2.x,0.0));
    float gz = groundH(hitUV+vec2(0.0,e2.y)) - groundH(hitUV-vec2(0.0,e2.y));
    vec3 nrm = normalize(vec3(-gx, 2.0*e2.x, -gz));
    float lam = max(dot(nrm, SUN), 0.0);
    float slope = clamp((1.0 - nrm.y)*2.4, 0.0, 1.0);
    float snow = clamp((hitH - uSnow)/45.0, 0.0, 1.0);
    float idraw = floor(texture2D(uId, hitUV).r * 255.0 + 0.5);
    float isEdge = (idraw > 127.5 && idraw < 254.5) ? 1.0 : 0.0;
    float idb = idraw - isEdge * 128.0;     // 255 stays 255 -> palette fallback (grey)
    float row = nrm.y > 0.72 ? 0.25 : 0.75;          // top faces vs side faces
    vec3 albedo = texture2D(uPal, vec2((idb + 0.5) / 256.0, row)).rgb;
    float detail = clamp(1.0 - (hitT - 500.0) / 1400.0, 0.15, 1.0);   // kill far-field id aliasing
    albedo = mix(vec3(0.52, 0.52, 0.54), albedo, detail);
    // near field: real 16x16 texels; far field: flat palette colour (no mipping needed)
    if(hitT < uDetailDist){
      vec3 hp = uEye + dir*hitT;
      float slot = idb*2.0 + (row > 0.5 ? 1.0 : 0.0);
      vec2 faceUV = (row > 0.5) ? fract(vec2(hp.x + hp.z, -hp.y)) : fract(hp.xz);
      faceUV = clamp(faceUV, 0.04, 0.96);                 // keep off the tile border
      vec2 cell = vec2(mod(slot, 16.0), floor(slot / 16.0));
      vec2 auv = (cell + faceUV) / 16.0;
      vec4 texel = texture2D(uAtlas, auv);
      if(texel.a > 0.5){ albedo = texel.rgb; }
    }
    vec3 base = mix(albedo, albedo * 0.75, slope * 0.5);
    if(uBelow > 0.5){ base *= 0.35; }        // underside: dark, reads as solid ground above
    if(onCano){ base = mix(base, vec3(0.20,0.34,0.16), 0.55); }   // forest tint, no speckle
    col = base*(0.40+0.80*lam);
    if(idraw > 254.5){
      vec2 wp = hitUV * TSIZE;
      float chk = mod(floor(wp.x) + floor(wp.y), 2.0);
      col = mix(vec3(0.06, 0.0, 0.09), vec3(0.95, 0.0, 0.95), chk);
    }
    vec2 uv01 = hitUV;                       // outer border of the whole map
    float toEdge = min(min(uv01.x, 1.0 - uv01.x), min(uv01.y, 1.0 - uv01.y));
    float border = smoothstep(0.0, 0.016, toEdge);
    col = mix(sky, col, border * (1.0 - isEdge * 0.85 * uFade));
    col = mix(col, sky, clamp(1.0 - exp(-hitT*0.00035), 0.0, 0.88));
  }
  if(uDbg > 2.5){                    // test which palette row v=0.25 / v=0.75 hits
    float vv = (gl_FragCoord.x/uRes.x < 0.5) ? 0.25 : 0.75;
    gl_FragColor = vec4(texture2D(uPal, vec2((uDbgId + 0.5)/256.0, vv)).rgb, 1.0);
    return;
  }
  if(uDbg > 0.5){
    // debug: red = terrain hit depth, green = water depth, black = sky
    vec3 dbg = (hitT > 0.0) ? vec3(clamp(hitT/2800.0, 0.0, 1.0), 0.0, 0.0) : vec3(0.0);
    if(waterT > 0.0) dbg = vec3(0.0, clamp(waterT/2800.0, 0.0, 1.0), 0.0);
    gl_FragColor = vec4(dbg, 1.0);
    return;
  }
  gl_FragColor = vec4(pow(clamp(col,0.0,1.0), vec3(1.0/1.08)), 1.0);
}`;

const BLIT_FS = `
precision mediump float;
uniform sampler2D uFB;
uniform vec2 uRes;
void main(){ gl_FragColor = texture2D(uFB, gl_FragCoord.xy/uRes); }`;

function compile(type, src){
  const s = gl.createShader(type);
  gl.shaderSource(s, src); gl.compileShader(s);
  if(!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error('shader:', gl.getShaderInfoLog(s));
  return s;
}
function program(fs){
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl.VERTEX_SHADER, VS));
  gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if(!gl.getProgramParameter(p, gl.LINK_STATUS)) console.error('link:', gl.getProgramInfoLog(p));
  return p;
}

let sceneP, blitP, u, ub, fbo, fboTex, tex, idTex, palTex, atlTex, heightArr;
const cam = {x:0,z:0,y:120,yaw:0,pitch:-12,fov:72};
const STEPS_FIXED = 128;
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v === null ? d : v; } catch(e){ return d; } },
  set(k, v){ try { localStorage.setItem(k, v); } catch(e){} },
};
const spdEl = document.getElementById('spd');
const spdVEl = document.getElementById('spdv');
let moveSpeed = +(store.get('mspeed', spdEl.value));
spdEl.value = moveSpeed; spdVEl.textContent = Math.round(moveSpeed);
spdEl.addEventListener('input', () => {
  moveSpeed = +spdEl.value;
  spdVEl.textContent = Math.round(moveSpeed);
  store.set('mspeed', moveSpeed);
});
let lastNow = performance.now();
const perf = {steps:96, fw:640, fh:360, fboOK:true, frames:0, t0:performance.now(), fps:0, lastInput:-1e9};
const keys = {};
let collide = true;
const buf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);

function start(){
  try {
  sceneP = program(SCENE_FS);
  blitP = program(BLIT_FS);
  u = {
    tex: gl.getUniformLocation(sceneP,'uTex'), res: gl.getUniformLocation(sceneP,'uRes'),
    eye: gl.getUniformLocation(sceneP,'uEye'), yaw: gl.getUniformLocation(sceneP,'uYaw'),
    pitch: gl.getUniformLocation(sceneP,'uPitch'), fov: gl.getUniformLocation(sceneP,'uFov'),
    snow: gl.getUniformLocation(sceneP,'uSnow'), nowater: gl.getUniformLocation(sceneP,'uNoWater'),
    dbg: gl.getUniformLocation(sceneP,'uDbg'), fade: gl.getUniformLocation(sceneP,'uFade'), id: gl.getUniformLocation(sceneP,'uId'),
    pal: gl.getUniformLocation(sceneP,'uPal'), atl: gl.getUniformLocation(sceneP,'uAtlas'),
    detailDist: gl.getUniformLocation(sceneP,'uDetailDist'), below: gl.getUniformLocation(sceneP,'uBelow'),
    dbgId: gl.getUniformLocation(sceneP,'uDbgId'), mapSize: gl.getUniformLocation(sceneP,'uMapSize'),
  };
  ub = { fb: gl.getUniformLocation(blitP,'uFB'), res: gl.getUniformLocation(blitP,'uRes') };

  tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  idTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, idTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_ID);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  atlTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, atlTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_ATL);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  palTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, palTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_PAL);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  fbo = gl.createFramebuffer(); fboTex = gl.createTexture();
  const P = new URLSearchParams(location.search);
  cam.x = P.has('x') ? +P.get('x') : HOME.x;
  cam.z = P.has('z') ? +P.get('z') : HOME.z;
  cam.y = P.has('y') ? +P.get('y') : HOME.y;
  cam.yaw = P.has('yaw') ? (+P.get('yaw') * Math.PI / 180) : HOME.yaw;
  cam.pitch = P.has('pitch') ? +P.get('pitch') : HOME.pitch;
  resizeCanvas();
  requestAnimationFrame(frame);
  } catch(err){
    document.getElementById('hud').innerHTML = '<b>初始化失败</b><br>'+err;
  }
}

function resizeCanvas(){
  const dpr = Math.min(devicePixelRatio||1, 1);
  const w = Math.floor(innerWidth*dpr), h = Math.floor(innerHeight*dpr);
  if(c.width !== w || c.height !== h){ c.width = w; c.height = h; }
  // fixed internal render scale: budget ~1.2 MPix so a 1080p window stays cheap
  const q = Math.min(0.9, Math.sqrt(2.4e6 / (w*h)));
  const fw = Math.max(320, Math.floor(w*q)), fh = Math.max(180, Math.floor(h*q));
  perf.fw = fw; perf.fh = fh;
  gl.bindTexture(gl.TEXTURE_2D, fboTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, fw, fh, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  idTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, idTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_ID);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  atlTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, atlTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_ATL);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  palTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, palTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, IMG_PAL);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, fboTex, 0);
  perf.fboOK = (gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}

addEventListener('resize', resizeCanvas);
addEventListener('keydown', e => {
  const k = e.key === ' ' ? 'space' : e.key.toLowerCase();
  if(k === 'space' || k === 'shift') e.preventDefault();
  keys[k] = true; perf.lastInput = performance.now();
  if(k === 'f'){ collide = !collide; }
  if(k === 'r'){ cam.x=HOME.x; cam.z=HOME.z; cam.y=HOME.y; cam.yaw=HOME.yaw; cam.pitch=HOME.pitch; }
  if(k === '[' || k === ']'){
    moveSpeed = Math.max(1, Math.min(120, moveSpeed + (k === ']' ? 4 : -4)));
    spdEl.value = moveSpeed; spdVEl.textContent = Math.round(moveSpeed);
    store.set('mspeed', moveSpeed);
  }
});
addEventListener('keyup', e => { const k = e.key === ' ' ? 'space' : e.key.toLowerCase(); keys[k] = false; });

let drag=false, lx=0, ly=0;
c.addEventListener('mousedown', e => { drag=true; lx=e.clientX; ly=e.clientY; c.classList.add('drag'); });
addEventListener('mouseup', () => { drag=false; c.classList.remove('drag'); });
addEventListener('mousemove', e => {
  if(!drag) return;
  cam.yaw += (e.clientX-lx)*0.004;
  cam.pitch = Math.max(-88, Math.min(88, cam.pitch + (e.clientY-ly)*0.004*180/Math.PI));
  lx=e.clientX; ly=e.clientY; perf.lastInput = performance.now();
});
c.addEventListener('wheel', e => {
  e.preventDefault();
  cam.fov = Math.max(25, Math.min(100, cam.fov + Math.sign(e.deltaY)*3));
  perf.lastInput = performance.now();
}, {passive:false});

const HMIN_ = -64.0, HSCALE_ = 384.0;
function fillHeights(){
  heightArr = new Uint16Array(TEXW*TEXH);
  const cv = document.createElement('canvas'); cv.width=TEXW; cv.height=TEXH;
  const ctx = cv.getContext('2d'); ctx.drawImage(IMG,0,0);
  const d = ctx.getImageData(0,0,TEXW,TEXH).data;
  for(let i=0;i<TEXW*TEXH;i++) heightArr[i] = (d[i*4]<<6) | (d[i*4+1]>>2);
}
function clampCam(){
  // stay inside the height-map, and between "just above ground" and a sane ceiling
  cam.x = Math.max(2, Math.min(MAPW - 3, cam.x));
  cam.z = Math.max(2, Math.min(MAPH - 3, cam.z));
  cam.y = Math.min(cam.y, 420);
  if(collide){
    // holes (unmapped chunks) decode below y=-63: don't let the camera fall out of the world
    const gh = heightAt(cam.x, cam.z);
    const floor = (gh > -63.0 ? gh + 1.6 : 40.0);
    if(cam.y < floor) cam.y = floor;
  } else {
    cam.y = Math.max(4, Math.min(420, cam.y));   // free fly, only a sanity band
  }
}

function heightAt(x, z){
  if(!heightArr) return 120;
  const i = Math.max(0, Math.min(TEXW-1, Math.floor(x)));
  const j = Math.max(0, Math.min(TEXH-1, Math.floor(z)));
  return HMIN_ + (heightArr[j*TEXW+i]/16383)*HSCALE_;
}

function frame(){
  const now = performance.now();
  const dt = Math.min(0.1, (now - lastNow) / 1000);
  lastNow = now;
  const moving = keys['w']||keys['s']||keys['a']||keys['d']||keys['q']||keys['e']||keys['space']||keys['shift'];
  if(moving){
    const sp = moveSpeed * dt, sy=Math.sin(cam.yaw), cy=Math.cos(cam.yaw);
    if(keys['w']){ cam.x += sy*sp; cam.z += cy*sp; }
    if(keys['s']){ cam.x -= sy*sp; cam.z -= cy*sp; }
    if(keys['a']){ cam.x += cy*sp; cam.z -= sy*sp; }
    if(keys['d']){ cam.x -= cy*sp; cam.z += sy*sp; }
    if(keys['e'] || keys['space']) cam.y += sp;
    if(keys['q'] || keys['shift']) cam.y -= sp;
    perf.lastInput = now;
  }
  clampCam();
  if(moving) perf.lastInput = now;

  // step budget only: cheap while interacting, rich when idle. No buffer reallocation.


  const useFBO = perf.fboOK;
  gl.bindFramebuffer(gl.FRAMEBUFFER, useFBO ? fbo : null);
  gl.viewport(0, 0, useFBO ? perf.fw : c.width, useFBO ? perf.fh : c.height);
  gl.useProgram(sceneP);
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  const loc = gl.getAttribLocation(sceneP,'a');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.uniform2f(u.res, useFBO ? perf.fw : c.width, useFBO ? perf.fh : c.height);
  gl.uniform3f(u.eye, cam.x, cam.y, cam.z);
  gl.uniform1f(u.yaw, cam.yaw);
  gl.uniform1f(u.pitch, cam.pitch*Math.PI/180);
  gl.uniform1f(u.fov, cam.fov);
  gl.uniform1f(u.snow, __SNOW__);
  gl.uniform1f(u.detailDist, 240.0);
  gl.uniform1f(u.below, (cam.y < heightAt(cam.x, cam.z)) ? 1.0 : 0.0);
  gl.uniform1f(u.nowater, new URLSearchParams(location.search).has('nowater') ? 1.0 : 0.0);
  var _dbg = new URLSearchParams(location.search).get('dbg');
  gl.uniform1f(u.dbg, _dbg ? parseFloat(_dbg) : 0.0);
  gl.uniform1f(u.dbgId, __GID__);
  gl.uniform1f(u.fade, new URLSearchParams(location.search).has('fade') ? 1.0 : 0.0);
  gl.uniform2f(u.mapSize, MAPW, MAPH);

  gl.uniform1i(u.tex, 0);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.uniform1i(u.id, 1);
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_2D, idTex);
  gl.uniform1i(u.pal, 2);
  gl.activeTexture(gl.TEXTURE2);
  gl.bindTexture(gl.TEXTURE_2D, palTex);
  gl.uniform1i(u.atl, 3);
  gl.activeTexture(gl.TEXTURE3);
  gl.bindTexture(gl.TEXTURE_2D, atlTex);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

  if(!useFBO){ requestAnimationFrame(frame); updateHUD(); return; }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.viewport(0,0,c.width,c.height);
  gl.useProgram(blitP);
  const loc2 = gl.getAttribLocation(blitP,'a');
  gl.enableVertexAttribArray(loc2);
  gl.vertexAttribPointer(loc2, 2, gl.FLOAT, false, 0, 0);
  gl.uniform2f(ub.res, c.width, c.height);
  gl.uniform1i(ub.fb, 0);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, fboTex);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

  perf.gh = heightAt(cam.x, cam.z);
  perf.frames++;
  if(now - perf.t0 > 500){
    perf.fps = perf.frames*1000/(now-perf.t0); perf.frames = 0; perf.t0 = now;
  }
  updateHUD();
  requestAnimationFrame(frame);
}
function updateHUD(){
  document.getElementById('hud').innerHTML =
    `<b>__NAME__</b><br>x ${cam.x.toFixed(0)} · y ${cam.y.toFixed(0)} · z ${cam.z.toFixed(0)}<br>`+
    `${collide ? '' : '<span style="color:#fc6">自由飞行</span> · '}yaw ${(cam.yaw*180/Math.PI).toFixed(0)}° · pitch ${cam.pitch.toFixed(0)}° · fov ${cam.fov.toFixed(0)}°<br>`+
    `ground ${perf.gh > -63 ? perf.gh.toFixed(0) : '—'} (floor ${(perf.gh > -63 ? perf.gh + 1.6 : 40).toFixed(0)})<br>`+
    `<span style="color:#8a8">${perf.fps.toFixed(0)} fps</span> · ${perf.fw}×${perf.fh} · safe-step<br>`+
    `<span style="color:#9ac;font-size:11px;white-space:normal">${METRICS}</span><br>` +
    `<span class="gpu">${GPU}</span>` +
    (perf.fboOK ? '' : ' · <span style="color:#f88">no-FBO fallback</span>');
}
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--region")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default="preview/viewer.html")
    ap.add_argument("--name")
    ap.add_argument("--metrics-json", help="write the terrain metrics as JSON")
    args = ap.parse_args()

    ground, water, canopy, flags, sid, x0, z0 = collect_layers(
        Path(args.world), args.region, workers=args.workers, fill_missing=False)

    # Map authors ring their build with empty chunks as a wall. Anything outside that ring is
    # not part of the work, so keep only the largest connected component of valid chunks and
    # drop the rest (no invented terrain, no terrain leaking in from beyond the wall).
    hh, ww = ground.shape
    ch, cw = hh // 16, ww // 16
    valid = ground[: ch * 16, : cw * 16] > -63
    per = valid.reshape(ch, 16, cw, 16).all(axis=(1, 3))

    seen = np.zeros_like(per, dtype=bool)
    best_label = np.zeros_like(per, dtype=np.int32)
    best_size, label = 0, 0
    stack: list[tuple[int, int]] = []
    for z0 in range(ch):
        for x0 in range(cw):
            if not per[z0, x0] or seen[z0, x0]:
                continue
            label += 1
            stack = [(z0, x0)]
            seen[z0, x0] = True
            size = 0
            while stack:
                z, x = stack.pop()
                size += 1
                best_label[z, x] = label
                for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nz, nx = z + dz, x + dx
                    if 0 <= nz < ch and 0 <= nx < cw and per[nz, nx] and not seen[nz, nx]:
                        seen[nz, nx] = True
                        stack.append((nz, nx))
            if size > best_size:
                best_size, keep_label = size, label
    keep = (best_label == keep_label) if best_size else per
    full = np.repeat(np.repeat(keep, 16, axis=0), 16, axis=1)
    hole = np.zeros_like(ground, dtype=bool)
    hole[: full.shape[0], : full.shape[1]] = ~full
    ground = np.where(hole, -70.0, ground)
    water = np.where(hole, -1e4, water)
    sid = np.where(hole, np.uint8(255), sid)
    print(f"   kept {best_size}/{int(per.sum())} valid chunks (largest island)")

    metrics = compute_metrics(ground, water, flags)
    print("   " + summary_line(metrics))
    if args.metrics_json:
        import json as _j
        Path(args.metrics_json).write_text(_j.dumps(metrics, indent=2), encoding="utf-8")
        print(f"   metrics -> {args.metrics_json}")

    orig_shape = ground.shape
    img = encode(ground, water, flags)
    bio = io.BytesIO()
    img.save(bio, format="PNG", optimize=True)
    b64 = base64.b64encode(bio.getvalue()).decode("ascii")

    idbio = io.BytesIO()
    encode_id(sid).save(idbio, format="PNG", optimize=True)
    id_b64 = base64.b64encode(idbio.getvalue()).decode("ascii")

    palbio = io.BytesIO()
    palette_image().save(palbio, format="PNG", optimize=True)
    pal_b64 = base64.b64encode(palbio.getvalue()).decode("ascii")

    atlbio = io.BytesIO()
    atlas_image().save(atlbio, format="PNG", optimize=True)
    atlas_b64 = base64.b64encode(atlbio.getvalue()).decode("ascii")

    import json as _json
    _pal = _json.loads((Path(__file__).parent.parent / "_palette" / "palette.json")
                       .read_text(encoding="utf-8"))
    _names = sorted(_pal["colors"])
    gid = _names.index("grass_block") if "grass_block" in _names else 0

    bx, bz, yaw = best_view(ground, water)
    eye_y = float(ground[bz, bx]) + 12.0
    html = (HTML.replace("__B64__", b64)
                .replace("__IDB64__", id_b64)
                .replace("__PALB64__", pal_b64)
                .replace("__ATLB64__", atlas_b64)
                .replace("__GID__", str(gid))
                .replace("__MIPS__", "[]")
                .replace("__SNOW__", f"{float(np.percentile(ground, 92)):.1f}")
                .replace("__NW__", str(ground.shape[1]))
                .replace("__NH__", str(ground.shape[0]))
                .replace("__MAPW__", str(orig_shape[1]))
                .replace("__MAPH__", str(orig_shape[0]))
                .replace("__EX__", f"{bx * 1.0:.1f}")
                .replace("__EZ__", f"{bz * 1.0:.1f}")
                .replace("__EY__", f"{eye_y:.1f}")
                .replace("__YAW__", f"{math.radians(yaw):.5f}")
                .replace("__NAME__", args.name or Path(args.world).name)
                .replace("__METRICS__", summary_line(metrics)))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"-> {out}  ({out.stat().st_size/1e6:.2f} MB)")
    print(f"   texture {ground.shape[1]}x{ground.shape[0]}  origin=({x0},{z0})")
    print(f"   snow {(flags & 1).mean():.1%}  ice {(flags & 2).mean():.1%}  canopy {(flags & 4).mean():.1%}")
    solid = ground > -63
    if solid.any():
        unknown_share = float((sid[solid] == 255).mean())
        print(f"   unknown block: {unknown_share:.1%} of solid columns (shown magenta/black)")
    print(f"   home view: x={bx} z={bz} yaw={yaw:.0f} eye_y={eye_y:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
