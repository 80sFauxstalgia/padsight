"""A stand-in obs-websocket v5 server for testing PadSight's OBS link without touching a real OBS.

Usage:  python tools/tests/mock_obs.py [--port 4456] [--password testpass] [--control 4466]

Implements: Hello/Identify with password auth, GetCurrentProgramScene, GetStreamStatus, GetRecordStatus,
GetSceneList, GetInputList, GetInputSettings, CreateInput, SetInputSettings. Wrong passwords are closed with
code 4009, like OBS.

Stream control: StartStream, StopStream, GetOutputList, GetHotkeyList, TriggerHotkeyByName and CallVendorRequest,
imitating two multistream plugins:
  * obs-multi-rtmp: targets 1001 and 1002, driven only by the hotkeys "obs-multi-rtmp.start.<id>" / ".stop.<id>";
    every running target is an output named "multi-output".
  * Aitum Multistream: vendor "aitum-multistream" with get_outputs / start_output / stop_output, outputs named
    "aitum_multi_output_<name>", and output_started / output_stopped vendor events.
Every stream request is logged in order under "calls" in /state.

A tiny control port lets a test drive OBS-side changes:
  curl "http://127.0.0.1:4466/scene?name=BRB"      -> CurrentProgramSceneChanged
  curl "http://127.0.0.1:4466/stream?on=1"         -> StreamStateChanged
  curl "http://127.0.0.1:4466/state"               -> JSON dump of scenes and inputs
  curl "http://127.0.0.1:4466/reset"               -> back to the starting scenes and inputs
  curl "http://127.0.0.1:4466/plugins?mrtmp=0&aitum=0" -> pretend the multistream plugins aren't installed
       (also dup=1: Aitum lists a name twice; nonascii=1: a non-ASCII obs-multi-rtmp id; hostile=1: an Aitum
        output whose name is HTML)
  curl "http://127.0.0.1:4466/outputlist?fail=1"   -> GetOutputList fails
  curl "http://127.0.0.1:4466/hang?type=A,B"       -> requests of these types never get an answer (/hang clears)
  curl "http://127.0.0.1:4466/startmode?m=error"   -> StartStream fails; m=never: accepted but never live;
                                                       m=hostile / m=long: the error comment has a bidi override and a
                                                       line break / is 5000 characters;
                                                       m=slow: live 3 s after StartStream; m=ok: at once
  curl "http://127.0.0.1:4466/aitummode?m=slow"    -> Aitum outputs stay "connecting" (not in the output list) for
                                                       3 s after start_output; stop_output cancels; stopping an
                                                       output that isn't running is refused inside responseData
                                                       ({success: false}); &refuse=1 refuses every stop
       (plugins bidi=1: an Aitum output name with a right-to-left override)
Standard library only.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import struct
import urllib.parse

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

import copy

INITIAL = None
state = {
    'scene': 'Gameplay',
    'scenes': ['Starting Soon', 'Gameplay', 'Rocket League', 'BRB'],
    'streaming': False,
    'recording': False,
    'inputs': {  # name -> (kind, settings)
        'Old PadSight': ('browser_source', {'url': 'http://127.0.0.1:47820/?theme=steamcontroller/graphite/Full.json', 'width': 1000, 'height': 760}),
        'Chat widget': ('browser_source', {'url': 'https://example.invalid/chat', 'width': 400, 'height': 600}),
        'Cam frame': ('browser_source', {'url': 'http://127.0.0.1:9000/overlays/camframe.html', 'width': 400, 'height': 266}),
    },
    'scene_items': {},
    'auth_attempts': 0,  # Identify messages that carried an authentication string
    'close_replies': 0,  # clients that answered our close frame (a polite close)
    'refused': 0,        # connection attempts while "restarting"
    'down_until': 0.0,
    'plugins': {'mrtmp': True, 'aitum': True, 'dup': False, 'nonascii': False, 'hostile': False, 'bidi': False},
    'start_mode': 'ok',
    'aitum_mode': 'ok',
    'aitum_refuse': False,   # stop_output refused for another reason
    'aitum_answer': 'plain', # okmsg: successes carry {success: true, message}; objerr: refusals carry an object as error;
                             # hostile: a refusal with a bidi override and a line break; notactive: "output is not active"
    'outputlist_fail': False,  # GetOutputList fails
    'hang': [],                # request types that never get an answer
    'aitum_live_at': {},   # Aitum output name -> when a slow start goes live
    'live_at': 0.0,   # slow start: when the stream goes live
    'mrtmp': {'1001': False, '1002': False},              # target id -> running
    'aitum': {'Kick': False, 'YouTube Vertical': False},  # output name -> running
    'calls': [],    # stream-control requests, in order: [requestType, detail]
    'events': [],   # events to send after the current response: (type, data, intent)
}
clients = set()
INITIAL = copy.deepcopy(state)


async def read_frame(reader):
    h = await reader.readexactly(2)
    op = h[0] & 0x0F
    masked = h[1] & 0x80
    n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack('>H', await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack('>Q', await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else b'\0\0\0\0'
    data = bytearray(await reader.readexactly(n))
    for i in range(n):
        data[i] ^= mask[i & 3]
    return op, bytes(data)


def frame(op, payload):
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | op, n])
    elif n < 65536:
        head = bytes([0x80 | op, 126]) + struct.pack('>H', n)
    else:
        head = bytes([0x80 | op, 127]) + struct.pack('>Q', n)
    return head + payload


async def send(writer, obj):
    writer.write(frame(1, json.dumps(obj).encode()))
    await writer.drain()


async def broadcast_event(event_type, data, intent):
    for (w, subs) in list(clients):
        if subs & intent:
            try:
                await send(w, {'op': 5, 'd': {'eventType': event_type, 'eventIntent': intent, 'eventData': data}})
            except Exception:
                pass


STREAM_CALLS = {'StartStream', 'StopStream', 'TriggerHotkeyByName', 'CallVendorRequest'}


def stream_event():
    state['events'].append(('StreamStateChanged', {'outputActive': state['streaming'],
                            'outputState': 'OBS_WEBSOCKET_OUTPUT_STARTED' if state['streaming'] else 'OBS_WEBSOCKET_OUTPUT_STOPPED'}, 1 << 6))


def promote_aitum():
    import time
    for n, t in list(state['aitum_live_at'].items()):
        if time.time() >= t:
            del state['aitum_live_at'][n]
            state['aitum'][n] = True


def handle_request(rtype, data):
    promote_aitum()
    if rtype in STREAM_CALLS and (data or {}).get('requestType') != 'get_outputs':  # log what changes state, not lookups
        d = data or {}
        detail = d.get('hotkeyName') or (d.get('requestType', '') + ' ' + json.dumps(d.get('requestData', {}))).strip()
        state['calls'].append([rtype, detail])
    if rtype == 'StartStream':
        if state['streaming'] or state['live_at']:
            return False, (500, 'The stream output is already running.')
        mode = state['start_mode']
        if mode == 'error':
            return False, (702, 'Failed to start the stream (mock).')
        if mode == 'hostile':
            return False, (702, 'Failed' + chr(0x202E) + chr(10) + 'now')
        if mode == 'long':
            return False, (702, 'x' * 5000)
        if mode == 'never':
            return True, {}
        if mode == 'slow':
            import time
            state['live_at'] = time.time() + 3
            return True, {}
        state['streaming'] = True
        stream_event()
        return True, {}
    if rtype == 'StopStream':
        if state['live_at'] and not state['streaming']:   # still connecting: stopping cancels it
            state['live_at'] = 0.0
            return True, {}
        if not state['streaming']:
            return False, (501, 'The stream output is not running.')
        state['streaming'] = False
        stream_event()
        return True, {}
    if rtype == 'GetOutputList':
        if state['outputlist_fail']:
            return False, (702, 'output list unavailable (mock)')
        outs = [{'outputName': 'simple_stream', 'outputKind': 'rtmp_output', 'outputActive': state['streaming']},
                {'outputName': 'simple_file_output', 'outputKind': 'ffmpeg_muxer', 'outputActive': state['recording']}]
        outs += [{'outputName': 'multi-output', 'outputKind': 'rtmp_output', 'outputActive': True} for on in state['mrtmp'].values() if on]
        outs += [{'outputName': 'aitum_multi_output_' + n, 'outputKind': 'rtmp_output', 'outputActive': True} for n, on in state['aitum'].items() if on]
        return True, {'outputs': outs}
    if rtype == 'GetHotkeyList':
        keys = ['OBSBasic.StartStreaming', 'OBSBasic.StopStreaming']
        if state['plugins']['mrtmp']:
            keys += ['obs-multi-rtmp.start_all', 'obs-multi-rtmp.stop_all']
            for i in state['mrtmp']:
                keys += ['obs-multi-rtmp.start.' + i, 'obs-multi-rtmp.stop.' + i]
            if state['plugins']['nonascii']:
                keys += ['obs-multi-rtmp.start.12\u00e9', 'obs-multi-rtmp.stop.12\u00e9']
        return True, {'hotkeys': keys}
    if rtype == 'TriggerHotkeyByName':
        name = (data or {}).get('hotkeyName', '')
        if state['plugins']['mrtmp'] and name.startswith('obs-multi-rtmp.'):
            verb, _, tid = name[len('obs-multi-rtmp.'):].partition('.')
            if tid in state['mrtmp'] and verb in ('start', 'stop'):
                state['mrtmp'][tid] = verb == 'start'
                return True, {}
        return False, (600, 'No hotkeys were found by that name.')
    if rtype == 'CallVendorRequest':
        d = data or {}
        if d.get('vendorName') != 'aitum-multistream' or not state['plugins']['aitum']:
            return False, (600, 'No vendor was found by that name.')
        rt, rd = d.get('requestType'), d.get('requestData') or {}
        out = {'vendorName': 'aitum-multistream', 'requestType': rt}
        if rt == 'get_outputs':
            names = list(state['aitum'])
            if state['plugins']['dup']:
                names.append('Kick')
            out['responseData'] = {'outputs': [{'name': n, 'vertical': 'Vertical' in n} for n in names]}
            return True, out
        if rt in ('start_output', 'stop_output'):
            n = rd.get('name')
            if n not in state['aitum']:
                return False, (702, 'output not found')
            if rt == 'stop_output':
                if n in state['aitum_live_at']:
                    del state['aitum_live_at'][n]      # still connecting: stopping cancels it
                elif state['aitum_refuse']:
                    err = {'objerr': {'code': 5}, 'hostile': 'stop' + chr(0x202E) + chr(10) + 'refused',
                           'notactive': 'output is not active'}.get(state['aitum_answer'], 'stop refused (mock)')
                    out['responseData'] = {'success': False, 'error': err}
                    return True, out
                elif state['aitum'][n]:
                    state['aitum'][n] = False
                else:
                    # Request status success with the vendor's own failure inside, as obs-websocket passes vendor
                    # answers through. The wording is the mock's guess until a real-OBS check.
                    out['responseData'] = {'success': False, 'error': 'output is not running'}
                    return True, out
            elif state['aitum_mode'] == 'slow':
                import time
                state['aitum_live_at'][n] = time.time() + 3
            else:
                state['aitum'][n] = True
            if state['aitum_answer'] == 'okmsg':
                out['responseData'] = {'success': True, 'message': 'Started' if rt == 'start_output' else 'Stopped'}
            state['events'].append(('VendorEvent', {'vendorName': 'aitum-multistream',
                                    'eventType': 'output_started' if rt == 'start_output' else 'output_stopped',
                                    'eventData': {'name': 'aitum_multi_output_' + n}}, 1 << 9))
            out.setdefault('responseData', {})
            return True, out
        return False, (702, 'unknown vendor request')
    if rtype == 'GetCurrentProgramScene':
        return True, {'currentProgramSceneName': state['scene'], 'sceneName': state['scene']}
    if rtype == 'GetStreamStatus':
        import time
        if state['live_at'] and time.time() >= state['live_at']:
            state['live_at'] = 0.0
            state['streaming'] = True
            stream_event()
        return True, {'outputActive': state['streaming'], 'outputReconnecting': False}
    if rtype == 'GetRecordStatus':
        return True, {'outputActive': state['recording']}
    if rtype == 'GetSceneList':
        n = len(state['scenes'])
        return True, {'currentProgramSceneName': state['scene'],
                      'scenes': [{'sceneName': s, 'sceneIndex': n - 1 - i} for i, s in enumerate(state['scenes'])]}
    if rtype == 'GetInputList':
        kind = (data or {}).get('inputKind')
        return True, {'inputs': [{'inputName': k, 'inputKind': v[0]} for k, v in state['inputs'].items() if not kind or v[0] == kind]}
    if rtype == 'GetInputSettings':
        name = (data or {}).get('inputName')
        if name not in state['inputs']:
            return False, (600, 'No source was found by the name of `%s`.' % name)
        return True, {'inputKind': state['inputs'][name][0], 'inputSettings': state['inputs'][name][1]}
    if rtype == 'SetInputSettings':
        name = data.get('inputName')
        if name not in state['inputs']:
            return False, (600, 'No source was found.')
        state['inputs'][name][1].update(data.get('inputSettings', {}))
        return True, {}
    if rtype == 'CreateInput':
        name = data.get('inputName')
        if name in state['inputs']:
            return False, (601, 'A source already exists by that input name.')
        if data.get('sceneName') not in state['scenes']:
            return False, (600, 'No scene was found.')
        state['inputs'][name] = (data.get('inputKind'), dict(data.get('inputSettings', {})))
        state['scene_items'].setdefault(data['sceneName'], []).append(name)
        return True, {'inputUuid': 'mock-' + name, 'sceneItemId': len(state['inputs'])}
    return False, (204, 'Unknown request type (mock).')


async def ws_handler(reader, writer, password):
    import time
    if time.time() < state['down_until']:
        state['refused'] += 1
        writer.close()
        return
    req = b''
    while b'\r\n\r\n' not in req:
        chunk = await reader.read(1024)
        if not chunk:
            return
        req += chunk
    headers = {}
    for line in req.decode(errors='replace').split('\r\n')[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            headers[k.strip().lower()] = v.strip()
    accept = base64.b64encode(hashlib.sha1((headers.get('sec-websocket-key', '') + GUID).encode()).digest()).decode()
    writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                  'Sec-WebSocket-Accept: %s\r\n\r\n' % accept).encode())
    salt = base64.b64encode(os.urandom(16)).decode()
    challenge = base64.b64encode(os.urandom(16)).decode()
    hello = {'obsWebSocketVersion': '5.5.mock', 'rpcVersion': 1}
    if password:
        hello['authentication'] = {'salt': salt, 'challenge': challenge}
    await send(writer, {'op': 0, 'd': hello})
    entry = None
    try:
        op, data = await read_frame(reader)
        msg = json.loads(data)
        if msg.get('op') != 1:
            return
        if msg['d'].get('authentication'):
            state['auth_attempts'] += 1
        if password:
            secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
            expected = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
            if msg['d'].get('authentication') != expected:
                print('mock: wrong password, closing with 4009')
                writer.write(frame(8, struct.pack('>H', 4009) + b'Authentication failed.'))
                await writer.drain()
                return
        subs = msg['d'].get('eventSubscriptions', 0)
        await send(writer, {'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        entry = (writer, subs)
        clients.add(entry)
        print('mock: client identified, subscriptions=%d' % subs)
        while True:
            op, data = await read_frame(reader)
            if op == 8:
                state['close_replies'] += 1
                return
            if op == 9:
                writer.write(frame(10, data))
                continue
            if op != 1:
                continue
            msg = json.loads(data)
            if msg.get('op') == 6:
                d = msg['d']
                if d['requestType'] in state['hang']:
                    print('mock: %s -> no answer (hang)' % d['requestType'])
                    continue
                ok, res = handle_request(d['requestType'], d.get('requestData'))
                print('mock: %s %s -> %s' % (d['requestType'], json.dumps(d.get('requestData')), 'ok' if ok else res))
                out = {'requestType': d['requestType'], 'requestId': d['requestId'],
                       'requestStatus': {'result': ok, 'code': 100 if ok else res[0]}}
                if ok:
                    out['responseData'] = res
                else:
                    out['requestStatus']['comment'] = res[1]
                await send(writer, {'op': 7, 'd': out})
                events, state['events'] = state['events'], []
                for ev in events:
                    await broadcast_event(*ev)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        if entry:
            clients.discard(entry)
        writer.close()


async def control_handler(reader, writer):
    line = (await reader.readline()).decode()
    while (await reader.readline()) not in (b'\r\n', b'\n', b''):
        pass
    path = line.split(' ')[1] if ' ' in line else '/'
    u = urllib.parse.urlparse(path)
    q = dict(urllib.parse.parse_qsl(u.query))
    body = {'ok': True}
    if u.path == '/restart':
        # Like OBS restarting its WebSocket server: close every client, refuse connections for a while.
        import time
        state['down_until'] = time.time() + float(q.get('down', '4'))
        state['refused'] = 0
        state['close_replies'] = 0
        for (w, subs) in list(clients):
            try:
                w.write(frame(8, struct.pack('>H', 1001) + b'Server restarting'))
                await w.drain()
            except Exception:
                pass
    elif u.path == '/reset':
        state.clear()
        state.update(copy.deepcopy(INITIAL))
    elif u.path == '/plugins':
        for k in ('mrtmp', 'aitum', 'dup', 'nonascii', 'hostile', 'bidi'):
            if k in q:
                state['plugins'][k] = q[k] == '1'
        hostile = '<img src=x onerror=alert(1)>'
        bidi = 'Kick' + chr(0x202E) + 'evil'
        if state['plugins'].get('bidi'):
            state['aitum'].setdefault(bidi, False)
        else:
            state['aitum'].pop(bidi, None)
        if state['plugins']['hostile']:
            state['aitum'].setdefault(hostile, False)
        else:
            state['aitum'].pop(hostile, None)
    elif u.path == '/outputlist':
        state['outputlist_fail'] = q.get('fail') == '1'
    elif u.path == '/hang':
        state['hang'] = [x for x in q.get('type', '').split(',') if x]
    elif u.path == '/aitummode':
        state['aitum_mode'] = q.get('m', 'ok')
        state['aitum_refuse'] = q.get('refuse') == '1'
        state['aitum_answer'] = q.get('answer', 'plain')
    elif u.path == '/startmode':
        state['start_mode'] = q.get('m', 'ok')
    elif u.path == '/scene':
        state['scene'] = q.get('name', state['scene'])
        await broadcast_event('CurrentProgramSceneChanged', {'sceneName': state['scene']}, 1 << 2)
    elif u.path == '/stream':
        state['streaming'] = q.get('on') == '1'
        await broadcast_event('StreamStateChanged', {'outputActive': state['streaming'], 'outputState': 'x'}, 1 << 6)
    elif u.path == '/record':
        state['recording'] = q.get('on') == '1'
        await broadcast_event('RecordStateChanged', {'outputActive': state['recording'], 'outputState': 'x'}, 1 << 6)
    elif u.path == '/state':
        promote_aitum()
        body = {'scene': state['scene'], 'streaming': state['streaming'], 'inputs': {k: v[1] for k, v in state['inputs'].items()},
                'scene_items': state['scene_items'], 'auth_attempts': state['auth_attempts'],
                'close_replies': state['close_replies'], 'refused': state['refused'],
                'mrtmp': state['mrtmp'], 'aitum': state['aitum'], 'calls': state['calls']}
    data = json.dumps(body).encode()
    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n' % len(data) + data)
    await writer.drain()
    writer.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=4456)
    ap.add_argument('--password', default='testpass')
    ap.add_argument('--control', type=int, default=4466)
    a = ap.parse_args()
    s1 = await asyncio.start_server(lambda r, w: ws_handler(r, w, a.password), '127.0.0.1', a.port)
    s2 = await asyncio.start_server(control_handler, '127.0.0.1', a.control)
    print('mock obs-websocket on 127.0.0.1:%d (control %d)' % (a.port, a.control), flush=True)
    async with s1, s2:
        await asyncio.gather(s1.serve_forever(), s2.serve_forever())


if __name__ == '__main__':
    asyncio.run(main())
