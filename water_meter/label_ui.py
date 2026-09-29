"""Web UI for labeling water meter captures (full readings and single digits).

Stdlib-only, in the style of correction_listener.py: one ThreadingHTTPServer,
one embedded single-page app (no CDN, no build step), LAN only. Works on a
phone (touch keypad, single column) and a desktop (keyboard shortcuts).

Auth: the same shared secret as the correction listener
(WATER_METER_CORRECTION_TOKEN, or WATER_METER_LABEL_UI_TOKEN to override).
Open the UI once with `/?token=...`; it sets a long-lived cookie, so later
links (including the notification deep link `/?item=<capture_id>`) carry no
secret.

Blind mode (`blind=1`) hides the model's guess and rejection reason
*server-side*, for labeling verify/test items without anchoring on the model.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import shutil
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlencode, urlparse

from .config import (
    CalibrationConfig,
    connection_config_from_env,
    load_calibration_config,
    save_calibration_config,
)
from .labels import CAPTURE_ID_RE, IMAGE_NAMES, LabelError, LabelStore

LOG = logging.getLogger(__name__)

DEFAULT_PORT = 8092
COOKIE_NAME = "wm_token"
MAX_BODY_BYTES = 4096
MAX_ROTATION_DEGREES = 15.0


class CalibrationError(ValueError):
    """Rejected calibration edit (bad boxes, out of bounds, absurd rotation)."""


def _valid_box(box: object, width: int, height: int, what: str) -> tuple[int, int, int, int]:
    if not (isinstance(box, (list, tuple)) and len(box) == 4 and all(
        isinstance(v, int) and not isinstance(v, bool) for v in box
    )):
        raise CalibrationError(f"{what} must be four integers [x, y, w, h]")
    x, y, w, h = box
    if w < 4 or h < 4 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise CalibrationError(f"{what} {list(box)} is outside the {width}x{height} frame")
    return (x, y, w, h)


def update_calibration(store: LabelStore, body: dict) -> CalibrationConfig:
    """Apply a box/rotation edit from the UI to calibration.json, keeping a
    timestamped backup of the previous file. Everything not being edited
    (ssocr args, thresholds, capture size...) is preserved."""
    path = store.calibration_path
    if path is None or not path.exists():
        raise CalibrationError("no calibration file to edit")
    current = load_calibration_config(path)
    boxes = body.get("digit_boxes", [list(b) for b in current.digit_boxes])
    if not isinstance(boxes, list) or len(boxes) != current.digit_count:
        raise CalibrationError(f"expected {current.digit_count} digit boxes")
    width, height = current.capture_width, current.capture_height
    new_boxes = tuple(_valid_box(b, width, height, f"digit box {i + 1}") for i, b in enumerate(boxes))
    rotation = body.get("rotation_degrees", current.rotation_degrees)
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or abs(rotation) > MAX_ROTATION_DEGREES:
        raise CalibrationError(f"rotation must be a number within +/-{MAX_ROTATION_DEGREES:g} degrees")
    roi = _valid_box(body["roi"], width, height, "roi") if "roi" in body else current.roi
    updated = replace(current, digit_boxes=new_boxes, rotation_degrees=float(rotation), roi=roi)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(path, path.with_name(f"{path.name}.bak.{stamp}"))
    save_calibration_config(path, updated)
    return updated


def calibration_view(config: CalibrationConfig) -> dict:
    return {
        "roi": list(config.roi),
        "digit_boxes": [list(b) for b in config.digit_boxes],
        "rotation_degrees": config.rotation_degrees,
        "capture_width": config.capture_width,
        "capture_height": config.capture_height,
        "digit_count": config.digit_count,
    }

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0e7c86">
<title>Meter labels</title>
<style>
:root{--bg:#f4f7f7;--card:#fff;--ink:#171d22;--muted:#5c6b71;--line:#d3dcdd;--accent:#0e7c86;--accent-ink:#fff;
--warn:#b06a00;--good:#1f7a54;--bad:#a03e1f}
@media (prefers-color-scheme:dark){:root{--bg:#10171a;--card:#171f23;--ink:#e9f1f1;--muted:#9db1b5;--line:#2b3a3e;--accent:#4fc4cd;--accent-ink:#06282b;--warn:#eab35b;--good:#6bcb9c;--bad:#e88761}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.4 system-ui,-apple-system,Segoe UI,sans-serif;padding-bottom:calc(84px + env(safe-area-inset-bottom))}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:8px 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
header h1{font-size:1rem;margin:0;flex:1 1 auto}
select,button,input{font:inherit;color:inherit}
select,.chip{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-height:44px}
main{max-width:980px;margin:0 auto;padding:12px;display:grid;gap:12px}
@media (min-width:860px){main{grid-template-columns:1.15fr 1fr;align-items:start}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.imgbox{background:#000;border-radius:8px;overflow:auto;touch-action:pinch-zoom pan-x pan-y}
.imgbox img,.imgbox #roiView{display:block;width:100%;height:auto;image-rendering:pixelated}
[hidden]{display:none !important}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:.85rem;color:var(--muted)}
.badge{border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.badge.test{color:var(--bad);border-color:var(--bad)}.badge.verify{color:var(--warn);border-color:var(--warn)}.badge.train{color:var(--good);border-color:var(--good)}
#cells{display:grid;grid-template-columns:repeat(8,1fr);gap:6px}
@media (max-width:520px){#cells{grid-template-columns:repeat(4,1fr)}}
.cell{border:2px solid var(--line);border-radius:10px;background:var(--bg);padding:4px;min-height:88px;display:flex;flex-direction:column;align-items:center;justify-content:space-between;cursor:pointer}
.cell img,.cell canvas{max-width:100%;max-height:52px;object-fit:contain;border-radius:4px;background:var(--card)}
.cell .d{font-size:1.9rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.cell.sel{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent) inset}
.cell.guess .d{color:var(--warn);font-style:italic}
.cell.human .d{color:var(--good)}
#keypad{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:10px}
#keypad button,.bar button{min-height:52px;border-radius:10px;border:1px solid var(--line);background:var(--card);font-size:1.25rem;font-weight:600}
#keypad button:active,.bar button:active{background:var(--accent);color:var(--accent-ink)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px}
.row label{display:flex;gap:8px;align-items:center;min-height:44px}
input[type=checkbox]{width:22px;height:22px}
#reading{font-size:1.4rem;letter-spacing:.12em;width:13ch;min-height:44px;border:1px solid var(--line);border-radius:8px;background:var(--bg);padding:4px 8px;font-variant-numeric:tabular-nums}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:6;background:var(--card);border-top:1px solid var(--line);display:flex;gap:8px;padding:8px 12px calc(8px + env(safe-area-inset-bottom))}
.bar button{flex:1;font-size:1rem}
.bar .primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
#toast{position:fixed;left:50%;top:64px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:999px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
#toast.on{opacity:.95}
table{border-collapse:collapse;width:100%;font-size:.8rem;font-variant-numeric:tabular-nums}
td,th{border:1px solid var(--line);padding:2px 4px;text-align:center}
td.z{color:var(--bad)}
details{margin-top:8px}
#boxcard{max-width:956px;margin:0 auto 12px}
#boxCanvas{display:block;width:100%;height:auto;touch-action:none;cursor:crosshair;background:#222}
#preview{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
#preview canvas{border:1px solid var(--line);border-radius:6px;background:var(--card);height:64px;width:auto}
.nudge button,.row .sm{min-height:44px;min-width:44px;border-radius:10px;border:1px solid var(--line);background:var(--card);font-size:1.1rem}
.badge.embargo{color:var(--muted)}
.badge.warn{color:var(--warn);border-color:var(--warn)}
button{cursor:pointer}
</style>
</head>
<body>
<header>
  <h1>Meter labels <span id="depth" class="chip"></span></h1>
  <select id="mode" aria-label="List">
    <option value="queue">Queue</option><option value="all">All</option><option value="labeled">Labeled</option><option value="excluded">Rejected frames</option><option value="legacy">Legacy frames</option>
  </select>
  <label class="chip"><input type="checkbox" id="blind"> Blind</label>
</header>
<div id="toast" role="status"></div>
<main>
  <section class="card" id="viewer">
    <div class="imgbox"><canvas id="roiView" hidden></canvas><img id="crop" alt="meter display crop"></div>
    <div class="row"><button id="toggleRaw" class="chip" type="button">Full frame</button>
      <span id="capid" class="chip"></span></div>
    <div class="imgbox" id="rawbox" hidden><img id="raw" alt="full frame"></div>
    <div class="meta" id="meta"></div>
  </section>
  <section class="card" id="editor">
    <div id="cells" role="group" aria-label="digits"></div>
    <div class="row">
      <input id="reading" inputmode="numeric" pattern="[0-9]*" maxlength="__DIGITS__" autocomplete="off" aria-label="full reading">
      <span class="chip" id="hint">tap a digit, then the keypad</span>
    </div>
    <div id="keypad"></div>
    <div class="row">
      <label><input type="checkbox" id="fUnreadable"> Unreadable</label>
      <label><input type="checkbox" id="fNot"> Not the totalizer</label>
      <label><input type="checkbox" id="fBad"> Cut off / bad frame (reject)</label>
    </div>
    <details id="statsbox"><summary>Progress &amp; coverage</summary><div id="stats"></div></details>
  </section>
</main>
<section class="card" id="boxcard">
  <details id="boxbox"><summary><strong>Refine digit boxes &amp; rotation</strong></summary>
    <p class="meta">Rotate the frame in 1&deg; steps (positive = counter-clockwise, same as the reader), then drag a box or nudge it.
      Each digit crop below should hold exactly one digit. Saving writes the Pi's calibration (a backup is kept) and applies from the next read.</p>
    <div class="row nudge">
      <button id="rotM" type="button" aria-label="rotate clockwise 1 degree">&minus;1&deg;</button>
      <span id="rotVal" class="chip">0&deg;</span>
      <button id="rotP" type="button" aria-label="rotate counter-clockwise 1 degree">+1&deg;</button>
      <button id="rotReset" type="button" class="sm">Reset</button>
    </div>
    <div class="imgbox"><canvas id="boxCanvas"></canvas></div>
    <div class="row nudge">
      <label>Box <select id="boxSel"></select></label>
      <label>Step <select id="step"><option>1</option><option>2</option><option>5</option></select> px</label>
      <button id="nL" type="button">&larr;</button><button id="nR" type="button">&rarr;</button>
      <button id="nU" type="button">&uarr;</button><button id="nD" type="button">&darr;</button>
      <button id="wM" type="button">W&minus;</button><button id="wP" type="button">W+</button>
      <button id="hM" type="button">H&minus;</button><button id="hP" type="button">H+</button>
    </div>
    <div class="row">
      <button id="evenOut" type="button" class="sm">Space evenly (first &rarr; last)</button>
      <button id="sameSize" type="button" class="sm">Same size as selected</button>
      <button id="boxRevert" type="button" class="sm">Revert</button>
      <button id="boxSave" type="button" class="sm primary" style="background:var(--accent);color:var(--accent-ink)">Save to Pi</button>
      <span id="boxNote" class="chip"></span>
    </div>
    <div id="preview" aria-label="digit crops preview"></div>
  </details>
</section>
<div class="bar">
  <button id="prev" type="button">&larr; Prev</button>
  <button id="skip" type="button">Skip</button>
  <button id="saveDigit" type="button">Save digit</button>
  <button id="saveReading" type="button" class="primary">Save reading</button>
</div>
<script>
const N = __DIGITS__;
let items = [], idx = 0, cur = null, sel = 0;
let cells = Array(N).fill(''), state = Array(N).fill('');   // state: '', 'guess', 'human'
const $ = id => document.getElementById(id);
const qs = new URLSearchParams(location.search);

function toast(msg){ const t=$('toast'); t.textContent=msg; t.classList.add('on'); setTimeout(()=>t.classList.remove('on'),1400); }
async function api(path, opts){
  const r = await fetch(path, Object.assign({credentials:'same-origin'}, opts||{}));
  if (r.status === 401){ document.body.innerHTML = '<p style="padding:16px">Not signed in. Open this page once with <code>?token=...</code>.</p>'; throw new Error('401'); }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
const blind = () => $('blind').checked ? 1 : 0;

function buildKeypad(){
  const kp = $('keypad'); kp.innerHTML = '';
  for (const k of ['1','2','3','4','5','6','7','8','9','0','⌫','◀','▶','Clear']){
    if (k === 'Clear') continue;
    const b = document.createElement('button'); b.type='button'; b.textContent=k; b.setAttribute('aria-label', 'key '+k);
    b.onclick = () => key(k); kp.appendChild(b);
  }
}
function key(k){
  if (k >= '0' && k <= '9'){ cells[sel]=k; state[sel]='human'; if (sel<N-1) sel++; }
  else if (k === '⌫'){ cells[sel]=''; state[sel]=''; if (sel>0) sel--; }
  else if (k === '◀'){ if (sel>0) sel--; }
  else if (k === '▶'){ if (sel<N-1) sel++; }
  renderCells();
}
function renderCells(){
  const box = $('cells'); box.innerHTML = '';
  for (let i=0;i<N;i++){
    const d = document.createElement('div');
    d.className = 'cell'+(i===sel?' sel':'')+(state[i]?(' '+state[i]):''); d.tabIndex = 0;
    if (liveOk()){ const cv = document.createElement('canvas'); cv.dataset.i = i; d.appendChild(cv); }
    else d.appendChild(document.createElement('span'));  // legacy frame: stored digit crops were cut with other boxes, so show none
    const sp = document.createElement('span'); sp.className='d'; sp.textContent = cells[i]||'·'; d.appendChild(sp);
    d.onclick = () => { sel=i; renderCells(); };
    box.appendChild(d);
  }
  box.querySelectorAll('canvas').forEach(cv => drawCrop(cv, boxes[+cv.dataset.i], 52));
  $('reading').value = cells.join('');
}
$('reading').addEventListener('input', e => {
  const v = e.target.value.replace(/\D/g,'').slice(0,N);
  for (let i=0;i<N;i++){ cells[i] = v[i]||''; state[i] = v[i]?'human':''; }
  sel = Math.min(v.length, N-1); renderCells();
});

async function show(id){
  cur = await api('/api/item?id='+id+'&blind='+blind());
  $('crop').src = cur.files.includes('crop') ? '/img?id='+id+'&name=crop&t='+Date.now() : '';
  $('raw').src = cur.files.includes('raw') ? '/img?id='+id+'&name=raw' : '';
  $('capid').textContent = id;
  frameImg = cur.files.includes('raw') ? await loadImage('/img?id='+id+'&name=raw') : null;
  rebuildRotated(); drawRoiView();
  const digits = cur.labels.digits || {};
  const labeled = Object.keys(digits).length > 0;
  for (let i=0;i<N;i++){
    if (digits[i] !== undefined){ cells[i]=digits[i]; state[i]='human'; }
    else if (cur.guess && cur.guess.length===N){ cells[i]=cur.guess[i]; state[i]='guess'; }
    else { cells[i]=''; state[i]=''; }
  }
  sel = 0; const firstOpen = state.findIndex(s => s !== 'human'); if (firstOpen >= 0) sel = firstOpen;
  $('fUnreadable').checked = cur.labels.flags.includes('unreadable');
  $('fNot').checked = cur.labels.flags.includes('not_totalizer');
  $('fBad').checked = cur.labels.flags.includes('bad_frame');
  const badges = [];
  badges.push('<span class="badge '+(cur.split||cur.scheduled_split||'')+'">'+(cur.split ? cur.split : 'will be '+cur.scheduled_split)+'</span>');
  badges.push('<span class="badge">'+cur.status+'</span>');
  if (cur.rejected) badges.push('<span class="badge" style="color:var(--bad)">rejected</span>');
  if (cur.reason) badges.push('<span class="badge">'+cur.reason.replace(/[<>&]/g,'')+'</span>');
  if (cur.legacy) badges.push('<span class="badge warn" title="Captured at '+cur.frame.width+'x'+cur.frame.height+' (or no full frame): the current ROI, digit boxes and rotation do not apply, so digit crops are hidden. You can still label the full reading from the image.">legacy frame '+(cur.frame.width?cur.frame.width+'x'+cur.frame.height:'(no full frame)')+'</span>');
  if (cur.guess) badges.push('<span class="badge">model: '+cur.guess+'</span>');
  $('meta').innerHTML = badges.join('');
  $('hint').textContent = labeled ? 'labeled - edit to relabel' : (cur.guess ? 'orange = model guess, unconfirmed' : 'tap a digit, then the keypad');
  renderCells(); drawBoxes(); drawPreview();
}
async function loadList(keep){
  const q = await api('/api/queue?mode='+$('mode').value+'&blind='+blind()+'&limit=200');
  items = q.items; $('depth').textContent = q.depth+' in '+$('mode').selectedOptions[0].text.toLowerCase();
  if (!keep) idx = 0;
  if (items.length){ idx = Math.min(idx, items.length-1); await show(items[idx].id); }
  else { cur = null; $('meta').textContent = 'Nothing here.'; $('crop').removeAttribute('src'); cells.fill(''); state.fill(''); renderCells(); }
}
async function go(delta){ if (!items.length) return; idx = (idx+delta+items.length)%items.length; await show(items[idx].id); }
async function post(body){
  return api('/api/label', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
}
async function saveReading(){
  if (!cur) return;
  if (cells.some(c => c === '')){ toast('Fill all '+N+' digits first'); return; }
  await post({capture_id: cur.id, kind:'reading', value: cells.join('')});
  toast('Saved reading'); await loadList(true);
}
async function saveDigit(){
  if (!cur || cells[sel] === ''){ toast('Pick a digit first'); return; }
  await post({capture_id: cur.id, kind:'digit', position: sel, value: cells[sel]});
  toast('Saved digit '+(sel+1)); await show(cur.id);
}
async function flag(name, value){
  if (!cur) return; await post({capture_id: cur.id, kind:'flag', flag:name, value:value});
  toast(name+(value?' set':' cleared')); if (value && (name==='unreadable' || name==='bad_frame')) await loadList(true);
}
async function loadStats(){
  const s = await api('/api/stats');
  let h = '<p>'+s.captures+' captures: '+s.labeled+' labeled, '+s.partial+' partial, '+s.unlabeled+' unlabeled, '+s.excluded+' rejected frames.<br>'+
    'Labeled by split - train '+s.by_split.train+', verify '+s.by_split.verify+', test '+s.by_split.test+
    ' (distinct values '+s.distinct_values_by_split.train+'/'+s.distinct_values_by_split.verify+'/'+s.distinct_values_by_split.test+').</p>'+
    '<table><tr><th>pos</th>'+[...Array(10).keys()].map(d=>'<th>'+d+'</th>').join('')+'</tr>';
  s.coverage.forEach((row,i)=>{ h += '<tr><th>'+i+'</th>'+row.map(c=>'<td'+(c===0?' class="z"':'')+'>'+c+'</td>').join('')+'</tr>'; });
  $('stats').innerHTML = h+'</table><p>Red zero cells are digit values with no human label at that position yet.</p>';
}
$('statsbox').addEventListener('toggle', e => { if (e.target.open) loadStats(); });
$('mode').onchange = () => loadList(false);
$('blind').onchange = () => loadList(true);
$('prev').onclick = () => go(-1); $('skip').onclick = () => go(1);
$('saveReading').onclick = saveReading; $('saveDigit').onclick = saveDigit;
$('fUnreadable').onchange = e => flag('unreadable', e.target.checked);
$('fNot').onchange = e => flag('not_totalizer', e.target.checked);
$('fBad').onchange = e => flag('bad_frame', e.target.checked);
$('toggleRaw').onclick = () => { const b=$('rawbox'); b.hidden = !b.hidden; };
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' && e.target.id === 'reading') { if (e.key==='Enter') saveReading(); return; }
  if (e.target.tagName === 'SELECT') return;
  if (e.key >= '0' && e.key <= '9') key(e.key);
  else if (e.key === 'Backspace') key('⌫');
  else if (e.key === 'ArrowLeft') key('◀'); else if (e.key === 'ArrowRight') key('▶');
  else if (e.key === 'ArrowUp') go(-1); else if (e.key === 'ArrowDown') go(1);
  else if (e.key === 'Enter') saveReading(); else return;
  e.preventDefault();
});
buildKeypad();
// ---- rotation + digit-box editor ----
let calib = null, frameImg = null, rot = 0, boxes = [], bsel = 0, view = null, drag = null;
const rc = document.createElement('canvas');
function loadImage(src){ return new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; }); }
function liveOk(){ return !!(frameImg && calib && boxes.length === N && frameImg.naturalWidth === calib.capture_width && frameImg.naturalHeight === calib.capture_height); }
function rebuildRotated(){
  if (!frameImg){ rc.width = rc.height = 0; return; }
  rc.width = frameImg.naturalWidth; rc.height = frameImg.naturalHeight;
  // Pivot on the ROI centre (same as reader.py), so the display tilts in place
  // instead of sliding away from the boxes.
  const r = calib ? calib.roi : [0, 0, rc.width, rc.height], px = r[0]+r[2]/2, py = r[1]+r[3]/2;
  const c = rc.getContext('2d'); c.save(); c.translate(px, py);
  c.rotate(-rot*Math.PI/180); c.drawImage(frameImg, -px, -py); c.restore();
}
function drawCrop(cv, b, maxH){
  if (!b || !rc.width) return;
  const h = Math.min(maxH, b[3]*3), w = Math.max(8, Math.round(h*b[2]/b[3]));
  cv.width = w; cv.height = h; const c = cv.getContext('2d'); c.imageSmoothingQuality = 'high';
  c.drawImage(rc, b[0], b[1], b[2], b[3], 0, 0, w, h);
}
function drawPreview(){
  const box = $('preview'); if (!$('boxbox').open) return; box.innerHTML = '';
  boxes.forEach((b, i) => { const cv = document.createElement('canvas'); box.appendChild(cv); drawCrop(cv, b, 64); cv.title = 'box '+(i+1); });
}
function drawBoxes(){
  if (!$('boxbox').open) return;
  const cv = $('boxCanvas'), note = $('boxNote');
  if (!liveOk()){
    cv.width = 10; cv.height = 10;
    note.textContent = !frameImg || !calib ? 'No full frame for this capture - pick a newer one to adjust boxes'
      : 'This frame is '+frameImg.naturalWidth+'x'+frameImg.naturalHeight+' but the calibration is for '+
        calib.capture_width+'x'+calib.capture_height+' - pick a newer capture to adjust boxes';
    return;
  }
  note.textContent = '';
  const r = calib.roi, m = 24;
  const rx = Math.max(0, r[0]-m), ry = Math.max(0, r[1]-m);
  const rw = Math.min(rc.width-rx, r[2]+2*m), rh = Math.min(rc.height-ry, r[3]+2*m);
  const S = Math.max(1, cv.parentElement.clientWidth / rw);
  cv.width = Math.round(rw*S); cv.height = Math.round(rh*S);
  const c = cv.getContext('2d'); c.imageSmoothingEnabled = false;
  c.drawImage(rc, rx, ry, rw, rh, 0, 0, cv.width, cv.height);
  c.strokeStyle = 'rgba(255,255,255,.5)'; c.setLineDash([6,4]); c.strokeRect((r[0]-rx)*S,(r[1]-ry)*S,r[2]*S,r[3]*S); c.setLineDash([]);
  boxes.forEach((b, i) => {
    c.lineWidth = i === bsel ? 3 : 2; c.strokeStyle = i === bsel ? '#ffd400' : '#19d3ff';
    c.strokeRect((b[0]-rx)*S, (b[1]-ry)*S, b[2]*S, b[3]*S);
    c.fillStyle = c.strokeStyle; c.font = 'bold 14px system-ui'; c.fillText(String(i+1), (b[0]-rx)*S+3, (b[1]-ry)*S+15);
  });
  view = {rx, ry, S};
}
function boxesChanged(){ drawBoxes(); drawPreview(); renderCells(); }
function setRot(v){ rot = Math.max(-15, Math.min(15, Math.round(v))); $('rotVal').textContent = rot+'°'; rebuildRotated(); drawRoiView(); boxesChanged(); }
function clampBox(b){
  const W = rc.width || calib.capture_width, H = rc.height || calib.capture_height;
  b[2] = Math.max(4, Math.min(W, b[2])); b[3] = Math.max(4, Math.min(H, b[3]));
  b[0] = Math.max(0, Math.min(W-b[2], b[0])); b[1] = Math.max(0, Math.min(H-b[3], b[1]));
}
function nudge(dx, dy, dw, dh){
  if (!boxes.length) return; const k = +$('step').value, b = boxes[bsel];
  b[0] += dx*k; b[1] += dy*k; b[2] += dw*k; b[3] += dh*k; clampBox(b); boxesChanged();
}
function boxAt(fx, fy){ for (let i = boxes.length-1; i >= 0; i--){ const b = boxes[i]; if (fx >= b[0] && fx <= b[0]+b[2] && fy >= b[1] && fy <= b[1]+b[3]) return i; } return -1; }
function pointerFrame(e){ const cv = $('boxCanvas'), rect = cv.getBoundingClientRect(), k = cv.width / rect.width;
  return {x: (e.clientX-rect.left)*k/view.S + view.rx, y: (e.clientY-rect.top)*k/view.S + view.ry}; }
$('boxCanvas').addEventListener('pointerdown', e => {
  if (!view) return; const p = pointerFrame(e), i = boxAt(p.x, p.y); if (i < 0) return;
  bsel = i; $('boxSel').value = i; drag = {i, dx: p.x-boxes[i][0], dy: p.y-boxes[i][1]};
  e.target.setPointerCapture(e.pointerId); drawBoxes();
});
$('boxCanvas').addEventListener('pointermove', e => {
  if (!drag) return; const p = pointerFrame(e), b = boxes[drag.i];
  b[0] = Math.round(p.x-drag.dx); b[1] = Math.round(p.y-drag.dy); clampBox(b); boxesChanged();
});
['pointerup','pointercancel'].forEach(t => $('boxCanvas').addEventListener(t, () => { drag = null; }));
$('boxSel').onchange = e => { bsel = +e.target.value; drawBoxes(); };
$('rotM').onclick = () => setRot(rot-1); $('rotP').onclick = () => setRot(rot+1);
$('rotReset').onclick = () => setRot(0);
$('nL').onclick = () => nudge(-1,0,0,0); $('nR').onclick = () => nudge(1,0,0,0);
$('nU').onclick = () => nudge(0,-1,0,0); $('nD').onclick = () => nudge(0,1,0,0);
$('wM').onclick = () => nudge(0,0,-1,0); $('wP').onclick = () => nudge(0,0,1,0);
$('hM').onclick = () => nudge(0,0,0,-1); $('hP').onclick = () => nudge(0,0,0,1);
$('evenOut').onclick = () => {
  if (boxes.length < 3) return; const a = boxes[0], z = boxes[boxes.length-1], n = boxes.length-1;
  boxes.forEach((b, i) => { b[0] = Math.round(a[0] + (z[0]-a[0])*i/n); b[1] = a[1]; b[2] = a[2]; b[3] = a[3]; clampBox(b); });
  boxesChanged(); toast('Spaced evenly');
};
$('sameSize').onclick = () => {
  const s0 = boxes[bsel]; if (!s0) return;
  boxes.forEach(b => { const cx = b[0]+b[2]/2, cy = b[1]+b[3]/2; b[2] = s0[2]; b[3] = s0[3]; b[0] = Math.round(cx-b[2]/2); b[1] = Math.round(cy-b[3]/2); clampBox(b); });
  boxesChanged(); toast('Same size');
};
async function loadCalib(){
  calib = await api('/api/calibration');
  boxes = calib.digit_boxes.map(b => b.slice()); rot = calib.rotation_degrees || 0;
  $('rotVal').textContent = rot+'°';
  const sel = $('boxSel'); sel.innerHTML = ''; boxes.forEach((_, i) => { const o = document.createElement('option'); o.value = i; o.textContent = i+1; sel.appendChild(o); });
  bsel = 0; rebuildRotated(); boxesChanged();
}
$('boxRevert').onclick = () => loadCalib().then(() => toast('Reverted to saved'));
$('boxSave').onclick = async () => {
  if (!liveOk()){ toast('Open a frame at the calibration resolution to save boxes'); return; }
  try {
    calib = await api('/api/calibration', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({digit_boxes: boxes, rotation_degrees: rot})});
    toast('Saved - used from the next read'); drawBoxes();
  } catch (e) { toast('Save failed: '+e.message); }
};
$('boxbox').addEventListener('toggle', e => { if (e.target.open){ boxesChanged(); } });
window.addEventListener('resize', () => drawBoxes());

// The main view re-cuts the ROI from the raw frame with the *current* calibration (ROI +
// rotation) whenever the frame matches it, so old misframed stored crops never mislead a label.
function drawRoiView(){
  const cv = $('roiView'), im = $('crop');
  if (!liveOk()){ cv.hidden = true; im.hidden = false; return; }
  const r = calib.roi; cv.width = r[2]*3; cv.height = r[3]*3;
  const c = cv.getContext('2d'); c.imageSmoothingQuality = 'high'; c.drawImage(rc, r[0], r[1], r[2], r[3], 0, 0, cv.width, cv.height);
  cv.hidden = false; im.hidden = true; checkCutoff(cv);
}
// Flag frames whose display looks cut off: ink touching the top/bottom edge of the crop.
function checkCutoff(src){
  try {
    const w = src.naturalWidth || src.width, h = src.naturalHeight || src.height;
    const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    const c = cv.getContext('2d'); c.drawImage(src, 0, 0, w, h);
    const x0 = Math.round(w*.15), x1 = Math.round(w*.85), d = c.getImageData(0,0,w,h).data;
    const luma = (x,y) => { const k = (y*w+x)*4; return .3*d[k]+.59*d[k+1]+.11*d[k+2]; };
    let mean = 0, n = 0; for (let y = 0; y < h; y += 2) for (let x = x0; x < x1; x += 2){ mean += luma(x,y); n++; } mean /= n;
    const t = Math.max(3, Math.round(h*.045));
    const edge = rows => { let dark = 0, tot = 0; rows.forEach(y => { for (let x = x0; x < x1; x++){ tot++; if (luma(x,y) < mean-45) dark++; } }); return dark/tot; };
    const top = edge([...Array(t).keys()]), bottom = edge([...Array(t).keys()].map(k => h-1-k));
    if (top > .06 || bottom > .06){ const b = document.createElement('span'); b.className = 'badge warn'; b.textContent = 'may be cut off ('+(top>bottom?'top':'bottom')+')'; $('meta').appendChild(b); }
  } catch (e) { /* canvas read can fail on odd images; the badge is only a hint */ }
}
$('crop').addEventListener('load', () => { if (!$('crop').hidden) checkCutoff($('crop')); });

(async () => {
  try { await loadCalib(); } catch (e) { /* editor is optional */ }
  const want = qs.get('item');
  await loadList(false);
  if (want && /^\d{8}T\d{6}Z$/.test(want)) { try { await show(want); } catch (e) { toast('Capture not found'); } }
})();
</script>
</body>
</html>
"""


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(store: LabelStore, token: str) -> type[BaseHTTPRequestHandler]:
    page = PAGE.replace("__DIGITS__", str(store.digit_count)).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _token_ok(self, supplied: str | None) -> bool:
            return bool(supplied) and hmac.compare_digest(supplied.encode(), token.encode())

        def _authorized(self, query: dict) -> bool:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if COOKIE_NAME in cookie and self._token_ok(cookie[COOKIE_NAME].value):
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer ") and self._token_ok(header[7:]):
                return True
            return False

        def _deny(self, api: bool) -> None:
            if api:
                _json(self, 401, {"error": "unauthorized"})
                return
            body = b"Unauthorized. Open this page once with ?token=<label UI token>."
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            path = parsed.path

            if path == "/" and self._token_ok(query.get("token")):
                # First visit with the secret: store it in a cookie and strip
                # it from the URL so it doesn't linger in history/screenshots.
                rest = {k: v for k, v in query.items() if k != "token"}
                location = "/" + ("?" + urlencode(rest) if rest else "")
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header(
                    "Set-Cookie",
                    f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000",
                )
                self.end_headers()
                return

            if not self._authorized(query):
                self._deny(api=path.startswith("/api/") or path == "/img")
                return

            blind = query.get("blind") == "1"
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
            elif path == "/api/queue":
                mode = query.get("mode", "queue")
                if mode not in ("queue", "all", "labeled", "excluded", "legacy"):
                    _json(self, 400, {"error": "bad mode"})
                    return
                try:
                    limit = max(1, min(500, int(query.get("limit", "50"))))
                except ValueError:
                    _json(self, 400, {"error": "bad limit"})
                    return
                _json(self, 200, store.queue(mode, limit, blind=blind))
            elif path == "/api/item":
                capture_id = query.get("id", "")
                if not CAPTURE_ID_RE.match(capture_id) or not store.capture_exists(capture_id):
                    _json(self, 404, {"error": "unknown capture"})
                    return
                _json(self, 200, store.item(capture_id, blind=blind))
            elif path == "/api/stats":
                _json(self, 200, store.stats())
            elif path == "/api/calibration":
                if store.calibration_path is None or not store.calibration_path.exists():
                    _json(self, 404, {"error": "no calibration file"})
                    return
                _json(self, 200, calibration_view(load_calibration_config(store.calibration_path)))
            elif path == "/img":
                capture_id, name = query.get("id", ""), query.get("name", "")
                if not CAPTURE_ID_RE.match(capture_id) or name not in IMAGE_NAMES:
                    self.send_response(404)
                    self.end_headers()
                    return
                file_path = store.capture_files(capture_id).get(name)
                if file_path is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized({}):
                self._deny(api=True)
                return
            if parsed.path not in ("/api/label", "/api/calibration"):
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                _json(self, 400, {"error": "bad body size"})
                return
            try:
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise TypeError("body must be an object")
            except (ValueError, TypeError):
                _json(self, 400, {"error": "bad request"})
                return
            if parsed.path == "/api/calibration":
                try:
                    updated = update_calibration(store, body)
                except CalibrationError as error:
                    _json(self, 400, {"error": str(error)})
                    return
                LOG.info("Calibration updated via UI: rotation=%s", updated.rotation_degrees)
                _json(self, 200, calibration_view(updated))
                return
            try:
                capture_id = body["capture_id"]
                kind = body["kind"]
            except (KeyError, TypeError):
                _json(self, 400, {"error": "bad request"})
                return
            try:
                item = store.add_label(
                    capture_id,
                    kind,
                    value=body.get("value"),
                    position=body.get("position"),
                    flag=body.get("flag"),
                )
            except LabelError as error:
                _json(self, 400, {"error": str(error)})
                return
            _json(self, 200, item)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            LOG.info("%s - %s", self.address_string(), format % args)

    return Handler


def build_store() -> LabelStore:
    connection = connection_config_from_env()
    digit_count = 8
    try:
        digit_count = load_calibration_config(connection.calibration_path).digit_count
    except (OSError, ValueError):
        LOG.warning("Could not load calibration; assuming %d digits", digit_count)
    return LabelStore(
        connection.image_dir,
        connection.state_dir,
        calibration_path=connection.calibration_path,
        digit_count=digit_count,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Water meter labeling UI.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the web UI (default).")
    imp = sub.add_parser(
        "import-golden", help="Register an existing golden_set manifest as human labels."
    )
    imp.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()

    store = build_store()
    if args.command == "import-golden":
        count = store.import_manifest(args.dir)
        print(f"Imported {count} labels from {args.dir}")
        return

    token = os.environ.get("WATER_METER_LABEL_UI_TOKEN") or os.environ.get(
        "WATER_METER_CORRECTION_TOKEN"
    )
    if not token:
        sys.exit(
            "WATER_METER_LABEL_UI_TOKEN or WATER_METER_CORRECTION_TOKEN must be set - refusing "
            "to serve an unauthenticated labeling UI that can write training labels"
        )
    port = int(os.environ.get("WATER_METER_LABEL_UI_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(store, token))
    LOG.info("Water meter label UI running on port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
