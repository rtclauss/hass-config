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
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlencode, urlparse

from .config import connection_config_from_env, load_calibration_config
from .labels import CAPTURE_ID_RE, IMAGE_NAMES, LabelError, LabelStore

LOG = logging.getLogger(__name__)

DEFAULT_PORT = 8092
COOKIE_NAME = "wm_token"
MAX_BODY_BYTES = 4096

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
.imgbox img{display:block;width:100%;height:auto;image-rendering:pixelated}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:.85rem;color:var(--muted)}
.badge{border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.badge.test{color:var(--bad);border-color:var(--bad)}.badge.verify{color:var(--warn);border-color:var(--warn)}.badge.train{color:var(--good);border-color:var(--good)}
#cells{display:grid;grid-template-columns:repeat(8,1fr);gap:6px}
@media (max-width:520px){#cells{grid-template-columns:repeat(4,1fr)}}
.cell{border:2px solid var(--line);border-radius:10px;background:var(--bg);padding:4px;min-height:88px;display:flex;flex-direction:column;align-items:center;justify-content:space-between;cursor:pointer}
.cell img{width:100%;max-height:48px;object-fit:contain;background:#000;border-radius:4px}
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
#reading{font-size:1.4rem;letter-spacing:.15em;width:11ch;min-height:44px;border:1px solid var(--line);border-radius:8px;background:var(--bg);padding:4px 8px;font-variant-numeric:tabular-nums}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:6;background:var(--card);border-top:1px solid var(--line);display:flex;gap:8px;padding:8px 12px calc(8px + env(safe-area-inset-bottom))}
.bar button{flex:1;font-size:1rem}
.bar .primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
#toast{position:fixed;left:50%;top:64px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:999px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
#toast.on{opacity:.95}
table{border-collapse:collapse;width:100%;font-size:.8rem;font-variant-numeric:tabular-nums}
td,th{border:1px solid var(--line);padding:2px 4px;text-align:center}
td.z{color:var(--bad)}
details{margin-top:8px}
button{cursor:pointer}
</style>
</head>
<body>
<header>
  <h1>Meter labels <span id="depth" class="chip"></span></h1>
  <select id="mode" aria-label="List">
    <option value="queue">Queue</option><option value="all">All</option><option value="labeled">Labeled</option>
  </select>
  <label class="chip"><input type="checkbox" id="blind"> Blind</label>
</header>
<div id="toast" role="status"></div>
<main>
  <section class="card" id="viewer">
    <div class="imgbox"><img id="crop" alt="meter display crop"></div>
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
    </div>
    <details id="statsbox"><summary>Progress &amp; coverage</summary><div id="stats"></div></details>
  </section>
</main>
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
    const has = cur && cur.files.includes('digit'+i);
    d.innerHTML = (has?'<img alt="" src="/img?id='+cur.id+'&name=digit'+i+'">':'<span></span>')+'<span class="d">'+(cells[i]||'·')+'</span>';
    d.onclick = () => { sel=i; renderCells(); };
    box.appendChild(d);
  }
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
  const badges = [];
  badges.push('<span class="badge '+(cur.split||'')+'">'+(cur.split ? cur.split : 'no split yet')+'</span>');
  badges.push('<span class="badge">'+cur.status+'</span>');
  if (cur.rejected) badges.push('<span class="badge" style="color:var(--bad)">rejected</span>');
  if (cur.reason) badges.push('<span class="badge">'+cur.reason.replace(/[<>&]/g,'')+'</span>');
  if (cur.guess) badges.push('<span class="badge">model: '+cur.guess+'</span>');
  $('meta').innerHTML = badges.join('');
  $('hint').textContent = labeled ? 'labeled - edit to relabel' : (cur.guess ? 'orange = model guess, unconfirmed' : 'tap a digit, then the keypad');
  renderCells();
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
  toast(name+(value?' set':' cleared')); if (value && name==='unreadable') await loadList(true);
}
async function loadStats(){
  const s = await api('/api/stats');
  let h = '<p>'+s.captures+' captures: '+s.labeled+' labeled, '+s.partial+' partial, '+s.unlabeled+' unlabeled.<br>'+
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
(async () => {
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
                if mode not in ("queue", "all", "labeled"):
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
            if parsed.path != "/api/label":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                _json(self, 400, {"error": "bad body size"})
                return
            try:
                body = json.loads(self.rfile.read(length))
                capture_id = body["capture_id"]
                kind = body["kind"]
            except (ValueError, KeyError, TypeError):
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
