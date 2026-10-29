#!/usr/bin/env python3
"""Minimal X11/uinput client for Open-P2P's Recap-compatible socket."""

import argparse
import asyncio
import json
import os
import signal
import struct
import sys
import time
from pathlib import Path

os.environ.setdefault("DISPLAY", ":1")

import mss
from evdev import UInput, ecodes as e
from PIL import Image
from Xlib import X, display

OPEN_P2P = Path(os.environ.get("OPEN_P2P_ROOT", "/home/minjune/m8work/open-p2p"))
sys.path.insert(0, str(OPEN_P2P))
from elefant.data.proto import video_inference_pb2 as proto  # noqa: E402

KEYS = {
    "Space": e.KEY_SPACE, "1": e.KEY_1, "2": e.KEY_2, "3": e.KEY_3,
    "4": e.KEY_4, "a": e.KEY_A, "d": e.KEY_D, "e": e.KEY_E,
    "f": e.KEY_F, "q": e.KEY_Q, "w": e.KEY_W, "s": e.KEY_S,
    "z": e.KEY_Z, "DownArrow": e.KEY_DOWN, "UpArrow": e.KEY_UP,
    "LeftArrow": e.KEY_LEFT, "RightArrow": e.KEY_RIGHT,
    "LeftShift": e.KEY_LEFTSHIFT, "RightShift": e.KEY_RIGHTSHIFT,
}
BUTTONS = {"0": e.BTN_LEFT, "1": e.BTN_RIGHT, "2": e.BTN_MIDDLE}
MAX_RECORD = 1 << 20


def pid_for_window(window):
    atom = window.display.get_atom("_NET_WM_PID")
    prop = window.get_full_property(atom, X.AnyPropertyType)
    return int(prop.value[0]) if prop and len(prop.value) else None


def title_for_window(window):
    try:
        return window.get_wm_name() or ""
    except Exception:
        return ""


def walk(window):
    yield window
    try:
        for child in window.query_tree().children:
            yield from walk(child)
    except Exception:
        return


def find_window(dpy, pid, title):
    candidates = []
    for window in walk(dpy.screen().root):
        try:
            geometry = window.get_geometry()
            if geometry.width < 100 or geometry.height < 100:
                continue
            if (pid and pid_for_window(window) == pid) or (title and title.lower() in title_for_window(window).lower()):
                candidates.append((geometry.width * geometry.height, window))
        except Exception:
            pass
    return max(candidates, default=(0, None))[1]


def ancestors(window):
    ids = set()
    while window:
        ids.add(window.id)
        try:
            parent = window.query_tree().parent
            window = None if parent.id == window.id else parent
        except Exception:
            break
    return ids


def focused(dpy, target):
    try:
        active_atom = dpy.get_atom("_NET_ACTIVE_WINDOW")
        prop = dpy.screen().root.get_full_property(active_atom, X.AnyPropertyType)
        active = dpy.create_resource_object("window", int(prop.value[0])) if prop and len(prop.value) else dpy.get_input_focus().focus
        return bool(ancestors(active) & ancestors(target))
    except Exception:
        return False


def client_box(dpy, window):
    geometry = window.get_geometry()
    # python-xlib exposes this as destination.translate_coords(source, ...).
    origin = dpy.screen().root.translate_coords(window, 0, 0)
    return {"left": origin.x, "top": origin.y, "width": geometry.width, "height": geometry.height}


class Input:
    def __init__(self, scale):
        capabilities = {
            e.EV_KEY: list(KEYS.values()) + list(BUTTONS.values()),
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_HWHEEL, e.REL_WHEEL],
        }
        self.device = UInput(capabilities, name="Open-P2P Kevin keyboard mouse")
        self.scale = scale
        self.keys = set()
        self.buttons = set()

    def apply(self, action):
        current_keys = set(action.keys) & KEYS.keys()
        current_buttons = set(action.mouse_action.buttons_down) & BUTTONS.keys()
        for name in current_keys - self.keys:
            self.device.write(e.EV_KEY, KEYS[name], 1)
        for name in self.keys - current_keys:
            self.device.write(e.EV_KEY, KEYS[name], 0)
        for name in current_buttons - self.buttons:
            self.device.write(e.EV_KEY, BUTTONS[name], 1)
        for name in self.buttons - current_buttons:
            self.device.write(e.EV_KEY, BUTTONS[name], 0)
        mouse = action.mouse_action
        if mouse.HasField("mouse_delta_px"):
            dx = round(mouse.mouse_delta_px.x * self.scale)
            dy = round(mouse.mouse_delta_px.y * self.scale)
            if dx:
                self.device.write(e.EV_REL, e.REL_X, dx)
            if dy:
                self.device.write(e.EV_REL, e.REL_Y, dy)
        if mouse.HasField("scroll_delta_px"):
            if mouse.scroll_delta_px.x:
                self.device.write(e.EV_REL, e.REL_HWHEEL, mouse.scroll_delta_px.x)
            if mouse.scroll_delta_px.y:
                self.device.write(e.EV_REL, e.REL_WHEEL, mouse.scroll_delta_px.y)
        self.device.syn()
        self.keys, self.buttons = current_keys, current_buttons

    def release(self):
        for name in self.keys:
            self.device.write(e.EV_KEY, KEYS[name], 0)
        for name in self.buttons:
            self.device.write(e.EV_KEY, BUTTONS[name], 0)
        self.device.syn()
        self.keys.clear()
        self.buttons.clear()

    def close(self):
        self.release()
        self.device.close()


async def read_record(reader):
    size = struct.unpack("<I", await reader.readexactly(4))[0]
    if size > MAX_RECORD:
        raise ValueError(f"unreasonable action record: {size} bytes")
    return await reader.readexactly(size)


async def run(args):
    dpy = display.Display(args.display)
    pid = int(Path(args.window_pid_file).read_text().strip()) if args.window_pid_file else args.window_pid
    deadline = time.monotonic() + args.wait
    window = None
    while not window and time.monotonic() < deadline:
        window = find_window(dpy, pid, args.window_title)
        if not window:
            await asyncio.sleep(0.25)
    if not window:
        raise RuntimeError("Kevin window not found")

    reader, writer = await asyncio.open_unix_connection(args.socket)
    injector = Input(args.mouse_scale)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", buffering=1)
    stop = asyncio.Event()
    send_times = {}
    frame_id = 1
    latest_frame = asyncio.Queue(maxsize=1)

    def request_stop():
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)

    async def capture():
        nonlocal frame_id
        period = 1.0 / args.fps
        next_frame = time.monotonic()
        with mss.mss(display=args.display, with_cursor=True) as grabber:
            while not stop.is_set():
                started_ns = time.monotonic_ns()
                box = client_box(dpy, window)
                shot = grabber.grab(box)
                rgb = Image.frombytes("RGB", shot.size, shot.rgb)
                rgb = rgb.resize((192, 192), Image.Resampling.HAMMING)
                captured_ns = time.monotonic_ns()
                message = proto.Frame(width=192, height=192, data=rgb.tobytes(), id=frame_id)
                payload = message.SerializeToString()
                item = (frame_id, payload, started_ns, captured_ns)
                if latest_frame.full():
                    dropped = latest_frame.get_nowait()
                    log.write(json.dumps({"event": "drop", "id": dropped[0]}) + "\n")
                latest_frame.put_nowait(item)
                frame_id = 1 if frame_id == 2147483647 else frame_id + 1
                next_frame += period
                await asyncio.sleep(max(0, next_frame - time.monotonic()))

    async def sender():
        while not stop.is_set():
            sent_id, payload, started_ns, captured_ns = await latest_frame.get()
            writer.write(struct.pack("<I", len(payload)) + payload)
            await writer.drain()
            sent_ns = time.monotonic_ns()
            send_times[sent_id] = (started_ns, captured_ns, sent_ns)
            if len(send_times) > 256:
                for old_id in sorted(send_times)[:-128]:
                    send_times.pop(old_id, None)
            log.write(json.dumps({"event": "frame", "id": sent_id,
                "capture_ms": (captured_ns-started_ns)/1e6,
                "send_ms": (sent_ns-captured_ns)/1e6}) + "\n")

    async def receiver():
        while not stop.is_set():
            action = proto.Action.FromString(await read_record(reader))
            received_ns = time.monotonic_ns()
            timing = send_times.pop(action.id, None)
            has_focus = focused(dpy, window)
            injected_ns = received_ns
            if has_focus:
                injector.apply(action)
                injected_ns = time.monotonic_ns()
            else:
                injector.release()
            entry = {"event": "action", "id": action.id, "keys": list(action.keys),
                "buttons": list(action.mouse_action.buttons_down), "focused": has_focus,
                "mouse": [action.mouse_action.mouse_delta_px.x, action.mouse_action.mouse_delta_px.y],
                "inject_ms": (injected_ns-received_ns)/1e6}
            if timing:
                entry.update(inference_ms=(received_ns-timing[2])/1e6,
                    end_to_end_ms=(injected_ns-timing[0])/1e6)
            log.write(json.dumps(entry) + "\n")

    try:
        tasks = [asyncio.create_task(capture()), asyncio.create_task(sender()), asyncio.create_task(receiver())]
        if args.duration:
            loop.call_later(args.duration, request_stop)
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait(tasks + [stop_task], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stop_task:
                task.result()
    finally:
        if "stop_task" in locals():
            stop_task.cancel()
        for task in locals().get("tasks", []):
            task.cancel()
        await asyncio.gather(*locals().get("tasks", []), return_exceptions=True)
        injector.close()
        writer.close()
        await writer.wait_closed()
        log.close()
        dpy.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", default=":1")
    parser.add_argument("--socket", default="/tmp/uds.recap")
    parser.add_argument("--window-pid", type=int)
    parser.add_argument("--window-pid-file")
    parser.add_argument("--window-title", default="Halo")
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--mouse-scale", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--wait", type=float, default=30)
    parser.add_argument("--log", default="/home/minjune/m8work/p2p-test/actions.jsonl")
    args = parser.parse_args()
    if not args.window_pid and not args.window_pid_file and not args.window_title:
        parser.error("select the Kevin window by PID, PID file, or title")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
