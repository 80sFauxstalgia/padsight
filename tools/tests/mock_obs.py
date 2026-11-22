"""A stand-in obs-websocket v5 server for testing PadSight's OBS link without touching a real OBS.

Usage:  python tools/tests/mock_obs.py [--port 4456] [--password testpass] [--control 4466]

Implements: Hello/Identify with password auth, GetCurrentProgramScene, GetStreamStatus, GetRecordStatus,
GetVirtualcamStatus, Start/Stop Stream, Record and Virtualcam (the answer comes first, the
StateChanged event follows 0.4 s later, like OBS's STARTING step), GetSceneList, GetInputList, GetInputSettings, CreateInput, SetInputSettings. Wrong passwords are closed with
code 4009, like OBS.

A tiny control port lets a test drive OBS-side changes:
  curl "http://127.0.0.1:4466/scene?name=BRB"      -> CurrentProgramSceneChanged
  curl "http://127.0.0.1:4466/stream?on=1"         -> StreamStateChanged
  curl "http://127.0.0.1:4466/fail?type=StartRecord"  -> that request type answers an error until /reset (no type: clear)
  curl "http://127.0.0.1:4466/state"               -> JSON dump of scenes and inputs
  curl "http://127.0.0.1:4466/reset"               -> back to the starting scenes and inputs
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
    'virtualcam': False,
    'fail': {},      # request type -> forced error
    'requests': [],  # every request type received, in order
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


OUTPUTS = {  # request -> (state key, event, new value)
    'StartStream': ('streaming', 'StreamStateChanged', True), 'StopStream': ('streaming', 'StreamStateChanged', False),
    'StartRecord': ('recording', 'RecordStateChanged', True), 'StopRecord': ('recording', 'RecordStateChanged', False),
    'StartVirtualcam': ('virtualcam', 'VirtualcamStateChanged', True), 'StopVirtualcam': ('virtualcam', 'VirtualcamStateChanged', False),
}


async def settle_output(key, event, value):
    # Like OBS: Get*Status already says "active", but the *StateChanged event only follows after the STARTING step.
    await asyncio.sleep(0.4)
    await broadcast_event(event, {'outputActive': value, 'outputState': 'x'}, 1 << 6)


def handle_request(rtype, data):
    state['requests'].append(rtype)
    if rtype in state['fail']:
        return False, tuple(state['fail'][rtype])
    if rtype in OUTPUTS:
        key, event, value = OUTPUTS[rtype]
        if state[key] == value:
            return False, (500, 'The output is already %s.' % ('active' if value else 'inactive'))
        state[key] = value
        asyncio.get_running_loop().create_task(settle_output(key, event, value))
        return True, {}
    if rtype == 'GetVirtualcamStatus':
        return True, {'outputActive': state['virtualcam']}
    if rtype == 'GetCurrentProgramScene':
        return True, {'currentProgramSceneName': state['scene'], 'sceneName': state['scene']}
    if rtype == 'GetStreamStatus':
        return True, {'outputActive': state['streaming']}
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
                ok, res = handle_request(d['requestType'], d.get('requestData'))
                print('mock: %s %s -> %s' % (d['requestType'], json.dumps(d.get('requestData')), 'ok' if ok else res))
                out = {'requestType': d['requestType'], 'requestId': d['requestId'],
                       'requestStatus': {'result': ok, 'code': 100 if ok else res[0]}}
                if ok:
                    out['responseData'] = res
                else:
                    out['requestStatus']['comment'] = res[1]
                await send(writer, {'op': 7, 'd': out})
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
        # Tell connected clients, so a PadSight that stays connected drops its cached output flags too.
        await broadcast_event('StreamStateChanged', {'outputActive': False, 'outputState': 'x'}, 1 << 6)
        await broadcast_event('RecordStateChanged', {'outputActive': False, 'outputState': 'x'}, 1 << 6)
        await broadcast_event('VirtualcamStateChanged', {'outputActive': False, 'outputState': 'x'}, 1 << 6)
    elif u.path == '/scene':
        state['scene'] = q.get('name', state['scene'])
        await broadcast_event('CurrentProgramSceneChanged', {'sceneName': state['scene']}, 1 << 2)
    elif u.path == '/stream':
        state['streaming'] = q.get('on') == '1'
        await broadcast_event('StreamStateChanged', {'outputActive': state['streaming'], 'outputState': 'x'}, 1 << 6)
    elif u.path == '/record':
        state['recording'] = q.get('on') == '1'
        await broadcast_event('RecordStateChanged', {'outputActive': state['recording'], 'outputState': 'x'}, 1 << 6)
    elif u.path == '/fail':
        if q.get('type'):
            state['fail'][q['type']] = [int(q.get('code', '500')), q.get('comment', 'forced failure')]
        else:
            state['fail'].clear()
    elif u.path == '/state':
        body = {'recording': state['recording'], 'virtualcam': state['virtualcam'], 'requests': state['requests'], 'scene': state['scene'], 'streaming': state['streaming'], 'inputs': {k: v[1] for k, v in state['inputs'].items()},
                'scene_items': state['scene_items'], 'auth_attempts': state['auth_attempts'],
                'close_replies': state['close_replies'], 'refused': state['refused']}
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
