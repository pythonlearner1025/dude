import asyncio
import json
import struct

import numpy as np
import pytest

from m8py.link import KIND_HEAR, KIND_JSON, KIND_VIEW, GameLink, frame


@pytest.mark.asyncio
async def test_handle_all_incoming_kinds():
    events, hearing = asyncio.Queue(), asyncio.Queue()
    link = GameLink({"type": "hello"}, events, hearing)
    await link.handle_frame(KIND_JSON, json.dumps({"type": "state", "state": "ok"}).encode())
    assert link.state["state"] == "ok"
    await link.handle_frame(KIND_JSON, json.dumps({"type": "new_game", "level": "b30"}).encode())
    assert link.state is None
    assert (await events.get())["level"] == "b30"
    await link.handle_frame(
        KIND_JSON, json.dumps({"type": "settings", "speech_cooldown": 2.5}).encode()
    )
    assert link.speech_cooldown == 2.5
    about = json.dumps({"sample_rate": 16000}).encode()
    await link.handle_frame(
        KIND_HEAR, struct.pack(">H", len(about)) + about + struct.pack("<hh", -32768, 16384)
    )
    _, samples, received_at = await hearing.get()
    np.testing.assert_array_equal(samples, np.array([-1, 0.5], dtype=np.float32))
    assert received_at > 0
    link._view_future = asyncio.get_running_loop().create_future()
    meta = json.dumps({"width": 1, "height": 1, "spots": []}).encode()
    await link.handle_frame(KIND_VIEW, struct.pack(">H", len(meta)) + meta + b"\x01\x02\x03")
    assert (await link._view_future).rgb == bytearray(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_partial_reads_and_outgoing_roundtrip():
    events, hearing = asyncio.Queue(), asyncio.Queue()
    link = GameLink({"type": "hello", "name": "K"}, events, hearing)
    await link.start(0)
    port = link.server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    header = await reader.readexactly(5)
    payload = await reader.readexactly(struct.unpack(">I", header[1:])[0])
    assert json.loads(payload)["type"] == "hello"
    data = frame(KIND_JSON, json.dumps({"type": "event", "text": "x"}).encode())
    for byte in data:
        writer.write(bytes([byte]))
        await writer.drain()
    assert (await asyncio.wait_for(events.get(), 1))["text"] == "x"
    writer.close()
    await writer.wait_closed()
    await link.close()


@pytest.mark.asyncio
async def test_reconnect_replaces_writer():
    events, hearing = asyncio.Queue(), asyncio.Queue()
    link = GameLink({"type": "hello"}, events, hearing)
    await link.start(0)
    port = link.server.sockets[0].getsockname()[1]
    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    await r1.readexactly(5)
    await r1.readexactly(16)
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.05)
    assert link.writer is not None and link.writer is not w1
    w1.close()
    w2.close()
    await link.close()
