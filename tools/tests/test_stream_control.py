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

# 7b. a stop the user confirmed always reaches OBS, even when the list said "off"
control('/reset')
wait_connected()
mark = len(calls())
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main'], 'confirm': True})
check('stop asks OBS even when the stream shows as off', code == 200 and calls()[mark:] == ['StopStream:{}'] and r['results'][0]['message'] == 'Already off', (r, calls()))

# 7c. OBS's own stream fails to start: nothing else may start
control('/startmode?m=error')
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main', 'mrtmp:1001', 'aitum:Kick'], 'confirm': True})
res = {x['key']: x for x in r.get('results', [])}
c = calls()
check('failed OBS start is reported', code == 200 and res['main']['ok'] is False, r)
check('plugin targets are skipped when OBS fails to start', res.get('mrtmp:1001', {}).get('ok') is False and 'Skipped' in res['mrtmp:1001']['message'] and res['aitum:Kick']['ok'] is False, r)
check('no plugin request after the failed start', not any(x.startswith(('TriggerHotkeyByName', 'CallVendorRequest')) for x in c), c)
check('nothing is live after the failed start', not control('/state')['streaming'] and not any(control('/state')['mrtmp'].values()))

control('/startmode?m=never')
t0 = time.time()
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
res = {x['key']: x for x in r.get('results', [])}
check('a start that never goes live times out with a "may still go live" warning', code == 200 and res['main']['ok'] is False and 'may still go live' in res['main']['message'] and time.time() - t0 >= 14, r)
check('and the plugin target is skipped', res['aitum:Kick']['ok'] is False and not control('/state')['aitum']['Kick'], r)

# 7d. a Stop sent while a Start waits for OBS sees the real state afterwards (one operation at a time)
import threading
control('/reset')
wait_connected()
control('/startmode?m=slow')   # OBS goes live 3 s after StartStream
out = {}
def do_start():
    out['start'] = api('obs/streams/action', {'op': 'start', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
th = threading.Thread(target=do_start)
th.start()
time.sleep(0.8)
out['stop'] = api('obs/streams/action', {'op': 'stop', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
th.join()
st = control('/state')
check('start then an overlapping stop both succeed', out['start'][0] == 200 and out['stop'][0] == 200, out)
check('after the overlapping stop nothing is left live', not st['streaming'] and not st['aitum']['Kick'], st)
c = calls()
check('the stop ran after the start finished', c == ['StartStream:{}', 'CallVendorRequest:start_output {"name": "Kick"}',
                                                   'CallVendorRequest:stop_output {"name": "Kick"}', 'StopStream:{}'], c)
control('/startmode?m=ok')

# 7e. odd data from plugins
control('/reset')
wait_connected()
control('/plugins?dup=1')
code, r, t = streams()
check('a duplicate Aitum name is listed once', code == 200 and [x['key'] for x in r['targets']].count('aitum:Kick') == 1, (code, list(t)))
code, r = api('obs/streams/action', {'op': 'stop', 'targets': list(t), 'confirm': True})
check('stop all still works with a duplicate name', code == 200, (code, r))
control('/plugins?dup=0&nonascii=1')
code, r, t = streams()
check('a non-ASCII obs-multi-rtmp id is left out', code == 200 and not any('12' in k and k.startswith('mrtmp:') and k not in ('mrtmp:1001', 'mrtmp:1002') for k in t), list(t))
code, r = api('obs/streams/prefs', {'targets': {k: {'label': 'x', 'type': 'Other'} for k in t}})
check('prefs for every listed stream can be saved', code == 200, (code, r))
control('/plugins?nonascii=0&hostile=1')
hostile = '<img src=x onerror=alert(1)>'
code, r, t = streams()
check('an Aitum name with HTML comes through as plain data', ('aitum:' + hostile) in t, list(t))
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['aitum:' + hostile], 'confirm': True})
check('and can be started like any other', code == 200 and r['results'][0]['ok'], (code, r))
control('/plugins?hostile=0')
code, r = api('obs/streams/prefs', {'targets': {'main': {'label': '<b>bold</b> & "quotes"', 'type': 'Twitch'}}})
check('a label with HTML is stored as text', code == 200 and r['saved']['prefs']['main']['Label'] == '<b>bold</b> & "quotes"', (code, r))
code, r = api('obs/streams/prefs', {'targets': {'main': {'label': 'Main\u202eevil', 'type': 'Twitch'}}})
check('a label with a bidi override is refused', code == 400, (code, r))
code, r = api('obs/streams/prefs', {'targets': {'main': {'label': 'ok'}}, 'combos': {'bad name!': ['main']}})
check('an invalid combination saves nothing', code == 400 and api('obs/streams')[1]['saved']['prefs'].get('main', {}).get('Label') != 'ok', (code, r))
api('obs/streams/prefs', {'targets': {}, 'combos': {}})

# 7f. an Aitum output that is still connecting is stopped too (round 2)
control('/reset')
wait_connected()
control('/aitummode?m=slow')   # Kick only shows as live 3 s after start_output
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
check('start with a slow Aitum output', code == 200 and all(x['ok'] for x in r['results']), r)
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
check('the stop right after it succeeds', code == 200 and all(x['ok'] for x in r['results']), r)
check('stop_output was sent although Kick still read as off', 'CallVendorRequest:stop_output {"name": "Kick"}' in calls(), calls())
time.sleep(4)
st = control('/state')
check('the connecting Aitum output never went live', not st['aitum']['Kick'] and not st['streaming'], st)
control('/aitummode?m=ok')
# The "not running" refusal below is the mock's guess at Aitum's answer, to be confirmed against a real OBS.
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('stopping an Aitum output that is off reads as already off, flagged for the status line',
      res.get('ok') is True and res.get('notice') is True and res.get('message', '').startswith('Already off'), r)
api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
control('/aitummode?m=ok&refuse=1')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('a vendor-level refusal of a stop is reported as failed, not as stopping', res.get('ok') is False and 'refused' in res.get('message', ''), r)
control('/aitummode?m=ok&refuse=1&answer=objerr')
api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('a refusal whose error is not text is still read as a refusal', res.get('ok') is False and res.get('message') == 'Aitum refused: no reason given', r)
control('/aitummode?m=ok&refuse=0&answer=okmsg')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('a success answer that carries a message reads as success', res.get('ok') is True and res.get('message') == 'Stopping', r)
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('also for a start', res.get('ok') is True and res.get('message') == 'Starting', r)
control('/aitummode?m=ok&refuse=0&answer=plain')
api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})

# 7h. a stop is never refused as a whole because one stream is missing
api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
control('/plugins?aitum=0')   # Aitum stops answering (or the output was renamed)
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main', 'aitum:Kick'], 'confirm': True})
res = {x['key']: x for x in r.get('results', [])}
check('stop with a missing stream still succeeds as a request', code == 200, (code, r))
check('OBS\'s own stream is stopped anyway', res.get('main', {}).get('ok') is True and not control('/state')['streaming'], r)
check('the missing stream is reported as not stopped', res.get('aitum:Kick', {}).get('ok') is False, r)
control('/plugins?aitum=1')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['../x'], 'confirm': True})
check('a malformed key is still refused', code == 400, (code, r))

# 7g. names that read differently from what they are
control('/plugins?bidi=1')
code, r, t = streams()
check('an Aitum name with a bidi override is left out', code == 200 and not any(k.startswith('aitum:Kick') and k != 'aitum:Kick' for k in t), list(t))
control('/plugins?bidi=0')
code, r = api('obs/streams/prefs', {'targets': {'main' + chr(10): {'label': 'x'}}})
check('a stream key with a trailing newline is refused', code == 400, (code, r))
code, r = api('obs/streams/prefs', {'targets': {'main': {'label': 'a' + chr(0x7F) + 'b'}}})
check('a label with DEL is refused', code == 400, (code, r))

# 7i. text from OBS and plugins is filtered before it is shown (round 5)
control('/reset')
wait_connected()
control('/startmode?m=hostile')
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
msg = r['results'][0]['message'] if code == 200 else ''
check('an OBS error comment with a bidi override or line break is not shown', msg == 'reason not shown', r)
control('/startmode?m=linesep')
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
msg = r['results'][0]['message'] if code == 200 else ''
check('an OBS error comment with a line separator (U+2028) is not shown', msg == 'reason not shown', r)
control('/startmode?m=long')
code, r = api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
msg = r['results'][0]['message'] if code == 200 else ''
check('a long OBS error comment is capped', 0 < len(msg) <= 203 and msg.endswith('...'), len(msg))
control('/startmode?m=ok')
api('obs/streams/action', {'op': 'start', 'targets': ['aitum:Kick'], 'confirm': True})
control('/aitummode?m=ok&refuse=1&answer=hostile')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
msg = r['results'][0]['message'] if code == 200 else ''
check('a hostile Aitum refusal is not shown', msg == 'Aitum refused: reason not shown', r)
control('/aitummode?m=ok&refuse=0&answer=plain')
api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})

# 7j. without OBS's output list the states are unknown, never "off"
control('/outputlist?fail=1')
code, r, t = streams()
check('without the output list Aitum states are unknown', code == 200 and r['outputListOk'] is False and t['aitum:Kick']['active'] is None, (r.get('outputListOk'), t.get('aitum:Kick')))
control('/aitummode?m=ok&refuse=1&answer=notactive')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['aitum:Kick'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('a "not active" refusal is not read as already off when the state is unknown', res.get('ok') is False, r)
control('/aitummode?m=ok&refuse=0&answer=plain')
control('/outputlist?fail=0')

# 7k. OBS's own "Already off" stays on the status line
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main'], 'confirm': True})
res = r['results'][0] if code == 200 else {}
check('OBS stream already off is flagged for the status line', res.get('message') == 'Already off' and res.get('notice') is True, r)

# 7l. a slow OBS: the first timeout skips the rest, and a stop never turns into a 500
api('obs/streams/action', {'op': 'start', 'targets': ['main'], 'confirm': True})
control('/hang?type=TriggerHotkeyByName')
t0 = time.time()
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['mrtmp:1001', 'mrtmp:1002', 'main'], 'confirm': True})
took = time.time() - t0
res = {x['key']: x for x in r.get('results', [])}
check('after one timeout the remaining plugins are not waited for', code == 200 and took < 13 and res.get('mrtmp:1002', {}).get('message', '').startswith('Not stopped'), (round(took, 1), r))
check('a hung plugin request never keeps OBS\'s own stream live', res.get('main', {}).get('ok') is True and 'StopStream:{}' in calls() and not control('/state')['streaming'], (r, calls()[-3:]))
control('/hang')
control('/hang?type=GetStreamStatus')
code, r = api('obs/streams/action', {'op': 'stop', 'targets': ['main'], 'confirm': True})
check('a stop still runs when OBS doesn\'t answer its status request', code == 200 and r['results'][0]['ok'] is True, (code, r))
code, r = api('obs/streams')
check('the stream list reports a slow OBS instead of failing', code == 200 and r.get('obsSlow') is True, (code, r.get('obsSlow')))
control('/hang')

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
