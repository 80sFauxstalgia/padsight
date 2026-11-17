"""End-to-end test of PadSight's stream control (panel "Streams" card) against tools/tests/mock_obs.py.

Start the mock (python tools/tests/mock_obs.py) and a PadSight instance, then:
    python tools/tests/test_stream_control.py --panel http://127.0.0.1:47818 --settings <that instance's settings json>
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
a = ap.parse_args()
KEY = json.load(open(a.settings, encoding='utf-8-sig'))['PanelKey']
failures = []


def api(path, body=None):
    req = urllib.request.Request(a.panel + '/api/' + path, headers={'X-Panel-Key': KEY})
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def control(path):
    with urllib.request.urlopen(a.control + path, timeout=5) as r:
        return json.loads(r.read())


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (('  -- ' + str(detail)) if detail and not ok else ''))
    if not ok:
        failures.append(name)


def wait_connected():
    end = time.time() + 10
    while time.time() < end:
        if api('state')[1]['obs']['status'] == 'Connected':
            return True
        time.sleep(0.2)
    return False


def streams():
    code, r = api('obs/streams')
    return code, r, {t['key']: t for t in r.get('targets', [])}


def calls():
    return [c[0] + ':' + c[1] for c in control('/state')['calls']]


control('/reset')
api('obs/connect', {'enabled': False})
code, r = api('obs/streams')
check('needs the OBS link first', code == 409, (code, r))
api('obs/connect', {'enabled': True, 'host': '127.0.0.1', 'port': a.mock_port, 'password': 'testpass'})
check('linked to the mock', wait_connected())

# 1. discovery
code, r, t = streams()
check('lists the main stream', code == 200 and t.get('main', {}).get('active') is False, r)
check('finds obs-multi-rtmp targets from its hotkeys', 'mrtmp:1001' in t and 'mrtmp:1002' in t and r['multiRtmp'] is True, list(t))
check('obs-multi-rtmp targets report no per-target state', t.get('mrtmp:1001', {}).get('active', 'x') is None, t.get('mrtmp:1001'))
check('finds Aitum Multistream outputs', 'aitum:Kick' in t and 'aitum:YouTube Vertical' in t and r['aitum'] is True, list(t))
check('marks a vertical Aitum output', t.get('aitum:YouTube Vertical', {}).get('note') == 'Vertical', t.get('aitum:YouTube Vertical'))
check('start_all is not mistaken for a target', not any(k.startswith('mrtmp:start') or k == 'mrtmp:all' for k in t), list(t))
control('/plugins?mrtmp=0&aitum=0')
code, r, t = streams()
check('without plugins only the main stream is listed', code == 200 and list(t) == ['main'], list(t))
control('/plugins?mrtmp=1&aitum=1')

# 2. guard rails
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main']})
check('refused without confirm', code == 400, (code, r))
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': 'yes'})
check('confirm must be true, not just truthy', code == 400, (code, r))
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['mrtmp:9999'], 'confirm': True})
check('unknown stream refused', code == 400 and '9999' in r.get('error', ''), (code, r))
code, r = api('obs/streams/action', {'op': 'launch', 'targets': ['main'], 'confirm': True})
check('unknown op refused', code == 400, (code, r))
check('nothing was sent to OBS by refused calls', calls() == [], calls())

# 3. start all: main first, then each plugin target
everything = ['aitum:Kick', 'mrtmp:1001', 'main', 'mrtmp:1002', 'aitum:YouTube Vertical']
code, r = api('obs/streams/action', {'op': 'start', 'targets': everything, 'confirm': True})
check('start all succeeds', code == 200 and all(x['ok'] for x in r['results']), (code, r))
c = calls()
check('OBS stream starts before any plugin target', c and c[0].startswith('StartStream:') and len(c) == 5, c)
check('obs-multi-rtmp started through its own hotkeys', 'TriggerHotkeyByName:obs-multi-rtmp.start.1001' in c and 'TriggerHotkeyByName:obs-multi-rtmp.start.1002' in c, c)
check('Aitum started through its vendor request', any(x.startswith('CallVendorRequest:start_output') and 'Kick' in x for x in c), c)
st = control('/state')
check('everything is live in OBS', st['streaming'] and all(st['mrtmp'].values()) and all(st['aitum'].values()), st)
code, r, t = streams()
check('Aitum outputs show as live', t['aitum:Kick']['active'] is True, t['aitum:Kick'])
check('multi-rtmp live count is reported', r['multiRtmpActive'] == 2, r['multiRtmpActive'])
check('main shows as live', t['main']['active'] is True)
check('the stream list version moved with OBS events', api('state')[1]['obs']['streamsVersion'] > 0)

# 4. starting again skips what is already live
control('/reset')
wait_connected()
api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
before = len(calls())
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
check('already-live main stream is not started twice', code == 200 and r['results'][0]['ok'] and len(calls()) == before, (r, calls()))

# 5. add one stream mid-session
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
c = calls()
check('mid-session add sends only that target', code == 200 and c[-1].startswith('CallVendorRequest:start_output') and 'Kick' in c[-1] and len(c) == before + 1, c)
check('main stream untouched by the add', control('/state')['streaming'] is True)

# 6. stop all: plugin targets first, then main
api('obs/streams/action', {'op': 'start', 'targets': ['mrtmp:1001'], 'confirm': True})
mark = len(calls())
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main', 'mrtmp:1001', 'aitum:Kick'], 'confirm': True})
c = calls()[mark:]
check('stop all succeeds', code == 200 and all(x['ok'] for x in r['results']), r)
check('plugin targets stop before the OBS stream', c and c[-1].startswith('StopStream:') and len(c) == 3, c)
st = control('/state')
check('everything is off in OBS', not st['streaming'] and not any(st['mrtmp'].values()) and not any(st['aitum'].values()), st)

# 7. a failure is reported per target, not hidden
control('/plugins?aitum=0')
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
check('a vanished plugin target is refused up front', code == 400, (code, r))
control('/plugins?aitum=1')

# 8. labels, types and combinations
code, r = api('obs/streams/prefs', {'targets': {'main': {'label': 'Main', 'type': 'Twitch'}, 'mrtmp:1001': {'label': 'Second', 'type': 'YouTube'}},
                                    'combos': {'Weekend': ['main', 'mrtmp:1001']}})
check('prefs saved', code == 200 and r['saved']['prefs']['main']['Type'] == 'Twitch' and r['saved']['combos']['Weekend'] == ['main', 'mrtmp:1001'], (code, r))
code, r, t = streams()
check('prefs come back with the stream list', r['saved']['prefs']['mrtmp:1001']['Label'] == 'Second', r['saved'])
code, r = api('obs/streams/prefs', {'combos': {'<script>': ['main']}})
check('odd combination names refused', code == 400, (code, r))
code, r = api('obs/streams/prefs', {'combos': {'Empty': []}})
check('empty combination refused', code == 400, (code, r))
code, r = api('obs/streams/prefs', {'targets': {'main': {'type': 'Twitch; DROP'}}})
check('odd type refused', code == 400, (code, r))
code, r = api('obs/streams/prefs', {'targets': {'../../x': {'type': 'Twitch'}}})
check('odd stream key refused', code == 400, (code, r))
api('obs/streams/prefs', {'targets': {}, 'combos': {}})

api('obs/connect', {'enabled': False})
print('\n%d failure(s)' % len(failures))
sys.exit(1 if failures else 0)
