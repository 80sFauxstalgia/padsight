"""End-to-end test of PadSight's OBS link against tools/tests/mock_obs.py.

Start the mock (python tools/tests/mock_obs.py) and a PadSight instance, then:
    python tools/tests/test_obs_link.py --panel http://127.0.0.1:47818 --settings <path to that instance's settings json>
The settings file is only read for the panel key. Standard library only.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--panel', default='http://127.0.0.1:47818')
ap.add_argument('--settings', required=True)
ap.add_argument('--mock-port', type=int, default=4456)
ap.add_argument('--control', default='http://127.0.0.1:4466')
ap.add_argument('--other-port', type=int, default=4457, help='a second mock (another "host") for the password-scope test')
ap.add_argument('--other-control', default='http://127.0.0.1:4467')
a = ap.parse_args()
KEY = json.load(open(a.settings, encoding='utf-8-sig'))['PanelKey']
failures = []


def api(path, body=None):
    req = urllib.request.Request(a.panel + '/api/' + path, headers={'X-Panel-Key': KEY})
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def raw_post(path, body, headers):
    """POST without the helper's defaults, so a test can leave out the key, or send another Origin / Content-Type."""
    req = urllib.request.Request(a.panel + '/api/' + path, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def control(path):
    with urllib.request.urlopen(a.control + path, timeout=5) as r:
        return json.loads(r.read())


def obs_state():
    return api('state')[1]['obs']


def wait_for(pred, what, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        s = obs_state()
        if pred(s):
            return s
        time.sleep(0.2)
    return obs_state()


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (('  -- ' + str(detail)) if detail and not ok else ''))
    if not ok:
        failures.append(name)


# Start every run from the same OBS state, and from PadSight disconnected.
control('/reset')
urllib.request.urlopen(a.other_control + '/reset', timeout=5).read()
api('obs/connect', {'enabled': False})

# 1. wrong password
api('obs/connect', {'enabled': True, 'host': '127.0.0.1', 'port': a.mock_port, 'password': 'nope'})
s = wait_for(lambda s: s['status'] == 'WrongPassword', 'wrong password')
check('wrong password is reported', s['status'] == 'WrongPassword', s)

# 2. right password
api('obs/connect', {'enabled': True, 'password': 'testpass'})
s = wait_for(lambda s: s['status'] == 'Connected', 'connected')
check('connects with the right password', s['status'] == 'Connected', s)
check('reads the program scene', s['scene'] == 'Gameplay', s.get('scene'))
stored = json.load(open(a.settings, encoding='utf-8-sig')).get('ObsPasswordProtected', '')
check('password stored encrypted, not in plain text', stored and 'testpass' not in stored)
check('state never returns the password', 'testpass' not in json.dumps(api('state')[1]))

# 3. scenes and PadSight sources
code, sc = api('obs/scenes')
check('scene list in OBS order', code == 200 and sc['scenes'] == ['Starting Soon', 'Gameplay', 'Rocket League', 'BRB'], sc)
names = [x['name'] for x in sc.get('sources', [])]
check('only PadSight overlay sources are listed', names == ['Old PadSight'], names)
check('old port is flagged', sc['sources'] and sc['sources'][0]['portOk'] is False)

# 4. add a source
base = a.panel + '/'
code, r = api('obs/add-source', {'scene': 'Gameplay', 'name': 'Evil', 'url': 'https://evil.example/', 'width': 100, 'height': 100})
check('refuses a foreign URL', code == 400, (code, r))
code, r = api('obs/add-source', {'scene': 'Gameplay', 'name': 'PadSight', 'url': base + '?theme=steamcontroller/graphite/Full.json', 'width': 1000, 'height': 760})
check('adds its own overlay', code == 200, (code, r))
st = control('/state')
added = st['inputs'].get('PadSight', {})
check('source settings: url, size, shutdown when hidden', added.get('url', '').startswith(base) and added.get('width') == 1000 and added.get('shutdown') is True, added)
check('source placed in the chosen scene', 'PadSight' in st['scene_items'].get('Gameplay', []), st['scene_items'])
code, r = api('obs/add-source', {'scene': 'Gameplay', 'name': 'PadSight', 'url': base, 'width': 1000, 'height': 760})
check('duplicate name is a clear 409', code == 409, (code, r))
code, r = api('obs/add-source', {'scene': 'Gameplay', 'name': 'bad<name>', 'url': base, 'width': 1000, 'height': 760})
check('odd source names refused', code == 400, (code, r))

# 5. fix port
code, r = api('obs/fix-port', {'name': 'Old PadSight'})
fixed = control('/state')['inputs']['Old PadSight']['url']
check('fix-port moves an old source to this port, keeping its theme', code == 200 and fixed == base + '?theme=steamcontroller/graphite/Full.json', fixed)
code, r = api('obs/fix-port', {'name': 'Chat widget'})
check('fix-port refuses non-PadSight sources', code == 400, (code, r))
check('non-PadSight source untouched', control('/state')['inputs']['Chat widget']['url'] == 'https://example.invalid/chat')

# 6. hide on a scene
api('obs/rules', {'hideScenes': ['BRB']})
control('/scene?name=BRB')
s = wait_for(lambda s: s['visible'] is False, 'hidden on BRB')
check('hidden on a break scene', s['visible'] is False and 'BRB' in (s['hiddenReason'] or ''), s)
control('/scene?name=Gameplay')
s = wait_for(lambda s: s['visible'] is True, 'visible again')
check('visible again on other scenes', s['visible'] is True, s)

# 7. only while live
api('obs/rules', {'onlyWhenLive': True})
s = wait_for(lambda s: s['visible'] is False, 'hidden offline')
check('only-while-live hides when offline', s['visible'] is False, s)
control('/stream?on=1')
s = wait_for(lambda s: s['visible'] is True, 'shown live')
check('shows once streaming starts', s['visible'] is True, s)
control('/stream?on=0')
api('obs/rules', {'onlyWhenLive': False})

# 8. theme per scene (start from a known theme, so there is one to go back to)
api('theme', {'theme': 'steamcontroller/graphite/Full.json'})
time.sleep(0.5)
before = api('state')[1]['theme']
before_key = before and before.get('key')
code, r = api('obs/rules', {'sceneThemes': {'Rocket League': 'steamcontroller/vaporwave/Full.json'}})
check('scene theme saved', code == 200, r)
code, r = api('obs/rules', {'sceneThemes': {'X': '../../settings.json'}})
check('unknown theme in a rule is refused', code == 400, (code, r))
control('/scene?name=Rocket%20League')
time.sleep(1.0)
key = (api('state')[1]['theme'] or {}).get('key')
check('scene rule switches the theme', key == 'steamcontroller/vaporwave/Full.json', key)
control('/scene?name=Gameplay')
time.sleep(1.0)
key = (api('state')[1]['theme'] or {}).get('key')
check('leaving the scene restores the previous theme', key == before_key, (key, before_key))
api('obs/rules', {'sceneThemes': {}, 'hideScenes': []})

# 9. manual hide, and the overlay page itself gets told
def overlay_meta_visible():
    """Open the overlay WebSocket like OBS does and return the 'visible' flag of its first meta message."""
    import base64, os, socket, struct
    host, port = a.panel.split('//')[1].split(':')
    s = socket.create_connection((host, int(port)), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(('GET /ws?theme=steamcontroller/graphite/Full.json HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\n'
               'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (host, port, key)).encode())
    buf = b''
    while b'\r\n\r\n' not in buf:
        buf += s.recv(1024)
    buf = buf.split(b'\r\n\r\n', 1)[1]
    def need(n):
        nonlocal buf
        while len(buf) < n:
            buf += s.recv(65536)
        out, buf = buf[:n], buf[n:]
        return out
    while True:
        h = need(2)
        n = h[1] & 0x7F
        if n == 126: n = struct.unpack('>H', need(2))[0]
        elif n == 127: n = struct.unpack('>Q', need(8))[0]
        data = need(n)
        if h[0] & 0x0F == 1:
            m = json.loads(data)
            if m.get('type') == 'meta':
                s.close()
                return m.get('visible')

api('visibility', {'hidden': True})
check('manual hide', obs_state()['visible'] is False)
check('overlay page is told to hide', overlay_meta_visible() is False)
api('visibility', {'hidden': False})
check('manual show', obs_state()['visible'] is True)
check('overlay page is told to show', overlay_meta_visible() is True)

# 10. hotkeys
code, r = api('hotkeys', {'toggle': 'F9'})
check('hotkey without a modifier refused', code == 400, (code, r))
code, r = api('hotkeys', {'toggle': 'Ctrl+Alt+Shift+F11'})
check('hotkey with modifiers accepted and registered', code == 200 and not r['obs']['hotkeys']['errors'], r)
api('hotkeys', {'toggle': ''})

# 11. a saved password is never sent to another OBS address
code, r = api('obs/connect', {'enabled': True, 'port': a.other_port})
s = wait_for(lambda s: s['status'] in ('WrongPassword', 'Unreachable'), 'other host')
check('changing the address forgets the saved password', s['hasPassword'] is False, s)
with urllib.request.urlopen(a.other_control + '/state', timeout=5) as resp:
    other = json.loads(resp.read())
check('the other server never got an answer derived from the password', other['auth_attempts'] == 0, other['auth_attempts'])
check('it asks for the password instead of retrying', s['status'] == 'WrongPassword', s)
api('obs/connect', {'enabled': True, 'port': a.mock_port, 'password': 'testpass'})
s = wait_for(lambda s: s['status'] == 'Connected', 'back')
check('re-entering the password reconnects', s['status'] == 'Connected', s)

# 12. addresses pasted from OBS's "Show Connect Info"
api('obs/connect', {'enabled': False})
code, r = api('obs/connect', {'enabled': True, 'host': 'ws://127.0.0.1:%d/' % a.mock_port, 'port': 4455, 'password': 'testpass'})
s = wait_for(lambda s: s['status'] == 'Connected', 'pasted url')
check('a pasted ws:// server URL works, port taken from it', code == 200 and s['status'] == 'Connected' and s['port'] == a.mock_port and s['host'] == '127.0.0.1', s)
code, r = api('obs/connect', {'enabled': True, 'host': '127.0.0.1:%d' % a.mock_port, 'password': 'testpass'})
s = wait_for(lambda s: s['status'] == 'Connected', 'host:port')
check('host:port works', code == 200 and s['status'] == 'Connected' and s['port'] == a.mock_port, s)
code, r = api('obs/connect', {'enabled': True, 'host': 'not a host!!'})
check('a nonsense address gets a clear message', code == 400 and '127.0.0.1' in r.get('error', ''), (code, r))
code, r = api('obs/connect', {'enabled': True, 'port': 70000})
check('an impossible port gets a clear message', code == 400 and '4455' in r.get('error', ''), (code, r))

# 13. OBS restarts its WebSocket server (as when its settings dialog is saved)
api('obs/connect', {'enabled': True, 'host': '127.0.0.1', 'port': a.mock_port, 'password': 'testpass'})
wait_for(lambda s: s['status'] == 'Connected', 'connected before restart')
control('/restart?down=5')
time.sleep(6)
st = control('/state')
check('answers the server close politely', st['close_replies'] >= 1, st['close_replies'])
check('no hammering while OBS restarts (<= 3 tries in 5 s)', st['refused'] <= 3, st['refused'])
s = wait_for(lambda s: s['status'] == 'Connected', 'reconnected', timeout=20)
check('reconnects by itself afterwards', s['status'] == 'Connected', s)

# 13b. outputs: POST /api/obs/outputs (the one route that can put the user on air)
api('obs/connect', {'enabled': True, 'host': '127.0.0.1', 'port': a.mock_port, 'password': 'testpass'})
wait_for(lambda s: s['status'] == 'Connected', 'connected for outputs')
control('/reset')  # a clean request log and all outputs off (PadSight keeps its connection)
wait_for(lambda s: not s['streaming'] and not s['recording'] and not s['virtualcam'], 'outputs off')
OUT_REQ = ('StartStream', 'StopStream', 'StartRecord', 'StopRecord', 'StartVirtualcam', 'StopVirtualcam')
def sent():
    return [r for r in control('/state')['requests'] if r in OUT_REQ]

# Guard: key, Origin and JSON are all required, and none of the refused calls reaches OBS.
body = json.dumps({'streaming': True}).encode()
code, r = raw_post('obs/outputs', body, {'Content-Type': 'application/json'})
check('outputs: no panel key is refused (401)', code == 401, (code, r))
code, r = raw_post('obs/outputs', body, {'Content-Type': 'application/json', 'X-Panel-Key': 'wrong'})
check('outputs: wrong panel key is refused (401)', code == 401, (code, r))
code, r = raw_post('obs/outputs', body, {'Content-Type': 'application/json', 'X-Panel-Key': KEY, 'Origin': 'https://evil.example'})
check('outputs: a foreign Origin is refused even with the key (403)', code == 403, (code, r))
code, r = raw_post('obs/outputs', body, {'Content-Type': 'application/json', 'X-Panel-Key': KEY, 'Origin': 'null'})
check('outputs: Origin "null" is refused (403)', code == 403, (code, r))
code, r = raw_post('obs/outputs', body, {'Content-Type': 'text/plain', 'X-Panel-Key': KEY})
check('outputs: a text/plain body (cross-site form post) is refused (415)', code == 415, (code, r))
code, r = raw_post('obs/outputs', body, {'Content-Type': 'application/x-www-form-urlencoded', 'X-Panel-Key': KEY})
check('outputs: a form-encoded body is refused (415)', code == 415, (code, r))
code, r = raw_post('obs/outputs', body, {'X-Panel-Key': KEY})
check('outputs: no Content-Type is refused (415)', code == 415, (code, r))
check('outputs: nothing refused above reached OBS', sent() == [], sent())

# Validation: 400 and nothing sent.
code, r = api('obs/outputs', {})
check('outputs: empty body is 400', code == 400, (code, r))
code, r = api('obs/outputs', {'streaming': 'true'})
check('outputs: a string instead of a boolean is 400', code == 400 and r.get('error') == '"streaming" must be true or false', (code, r))
code, r = api('obs/outputs', {'recording': 1})
check('outputs: a number instead of a boolean is 400', code == 400, (code, r))
code, r = api('obs/outputs', {'streaming': None})
check('outputs: null is 400', code == 400, (code, r))
code, r = api('obs/outputs', {'streaming': True, 'recording': 'yes'})
check('outputs: one bad value rejects the whole call', code == 400 and sent() == [], (code, r, sent()))
code, r = api('obs/outputs', {'somethingElse': True})
check('outputs: unknown keys are not passed through', code == 400 and sent() == [], (code, r, sent()))

# Start: the reply is not the final state; OBS settles a moment later and the pushed state follows.
code, r = api('obs/outputs', {'streaming': True})
check('outputs: start stream is accepted and lists it as applied', code == 200 and r.get('applied') == ['streaming'], (code, r))
check('outputs: only StartStream was sent', sent() == ['StartStream'], sent())
s = wait_for(lambda s: s['streaming'], 'streaming settled')
check('outputs: the pushed state settles to streaming', s['streaming'] is True and not s['recording'] and not s['virtualcam'], s)

# Already in the target state: no output request at all (checked against OBS, not the cache).
before = control('/state')['requests']
code, r = api('obs/outputs', {'streaming': True})
after = control('/state')['requests']
check('outputs: already-live stream sends no Start request', code == 200 and r.get('applied') == [] and [x for x in after[len(before):] if x in OUT_REQ] == [], (code, r, after[len(before):]))
# A quick second start right after the first would have hit the stale cache; it must not reach OBS either.
control('/stream?on=0')
wait_for(lambda s: not s['streaming'], 'stream off')
api('obs/outputs', {'streaming': True})
code, r = api('obs/outputs', {'streaming': True})   # immediately, before the event has arrived
check('outputs: a second start before the event is a no-op, not an OBS error', code == 200 and r.get('applied') == [], (code, r))
wait_for(lambda s: s['streaming'], 'streaming again')

# Partial failure: stream is already on, record fails -> 502 names what was applied, with the current state.
control('/reset')
wait_for(lambda s: not s['streaming'], 'reset')
control('/fail?type=StartRecord&code=207&comment=disk%20full')
code, r = api('obs/outputs', {'streaming': True, 'recording': True, 'virtualcam': True})
check('outputs: partial failure is 502 with the OBS message', code == 502 and 'disk full' in r.get('error', ''), (code, r))
check('outputs: partial failure lists what was applied', r.get('applied') == ['streaming'], r)
check('outputs: partial failure carries the current obs state', isinstance(r.get('obs'), dict) and r['obs'].get('status') == 'Connected', r)
check('outputs: nothing after the failing request was sent', sent()[-1:] == ['StartRecord'] and 'StartVirtualcam' not in sent(), sent())
s = wait_for(lambda s: s['streaming'], 'stream live after partial')
check('outputs: the stream that was applied really is live', s['streaming'] is True and not s['recording'], s)
control('/fail')

# An OBS build without a virtual camera: the status question itself is refused (like a very old OBS).
control('/reset')
wait_for(lambda s: not s['streaming'], 'reset for old obs')
control('/fail?type=GetVirtualcamStatus&code=500&comment=no%20virtual%20camera%20in%20this%20build')
code, r = api('obs/outputs', {'streaming': True, 'virtualcam': False})
check('outputs: a virtualcam stop where OBS has none is skipped, not a 502',
      code == 200 and r.get('applied') == ['streaming'] and sent() == ['StartStream'], (code, r, sent()))
control('/fail?type=StartVirtualcam&code=500&comment=no%20virtual%20camera%20in%20this%20build')
code, r = api('obs/outputs', {'virtualcam': True})
check('outputs: a virtualcam start where OBS has none fails naming StartVirtualcam',
      code == 502 and 'StartVirtualcam' in r.get('error', '') and r.get('applied') == [], (code, r))
control('/fail')

# Stop everything that runs; outputs that are already off are not asked again.
control('/reset')
wait_for(lambda s: not s['streaming'], 'reset again')
api('obs/outputs', {'recording': True, 'virtualcam': True})
wait_for(lambda s: s['recording'] and s['virtualcam'], 'record + virtualcam on')
n = len(control('/state')['requests'])
code, r = api('obs/outputs', {'streaming': False, 'recording': False, 'virtualcam': False})
sent_now = [x for x in control('/state')['requests'][n:] if x in OUT_REQ]
check('outputs: stop all only stops what runs', code == 200 and sorted(sent_now) == ['StopRecord', 'StopVirtualcam'], (code, r, sent_now))
s = wait_for(lambda s: not s['recording'] and not s['virtualcam'], 'all off')
check('outputs: everything ends up off', not s['streaming'] and not s['recording'] and not s['virtualcam'], s)

# 14. disconnect
api('obs/connect', {'enabled': False})
s = wait_for(lambda s: s['status'] == 'Off', 'off')
check('disconnects', s['status'] == 'Off', s)

# 15. outputs while OBS isn't connected: 409 with the state, and nothing sent
n = len(control('/state')['requests'])
code, r = api('obs/outputs', {'streaming': True})
check('outputs: 409 when OBS is not connected', code == 409 and 'connected' in r.get('error', '') and isinstance(r.get('obs'), dict), (code, r))
check('outputs: nothing reached OBS while disconnected', control('/state')['requests'][n:] == [])

print('\n%d failure(s)' % len(failures))
sys.exit(1 if failures else 0)
