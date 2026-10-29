# Open-P2P / Recap real-time client protocol

Verified 2026-10-28 against:

- `elefant-ai/open-p2p` commit `a329d98cbe62119679a254d71bea6446773541bc`
- `elefant-ai/recap` commit `70ee48d5f4cd0f6bb19810a55b7ec1c3f36e226f`

Primary sources are the Open-P2P [socket server](https://github.com/elefant-ai/open-p2p/blob/a329d98cbe62119679a254d71bea6446773541bc/elefant/inference/unix_socket_server.py), [inference server](https://github.com/elefant-ai/open-p2p/blob/a329d98cbe62119679a254d71bea6446773541bc/elefant/policy_model/inference.py), and [action mapping](https://github.com/elefant-ai/open-p2p/blob/a329d98cbe62119679a254d71bea6446773541bc/elefant/data/action_mapping.py), plus Recap's [wire schema](https://github.com/elefant-ai/recap/blob/70ee48d5f4cd0f6bb19810a55b7ec1c3f36e226f/protos/video_inference.proto), [capture loop](https://github.com/elefant-ai/recap/blob/70ee48d5f4cd0f6bb19810a55b7ec1c3f36e226f/src/handler/capture/mod.rs), [GStreamer pipeline](https://github.com/elefant-ai/recap/blob/70ee48d5f4cd0f6bb19810a55b7ec1c3f36e226f/crates/recap_gst/src/record_window.rs), and [input application](https://github.com/elefant-ai/recap/blob/70ee48d5f4cd0f6bb19810a55b7ec1c3f36e226f/src/handler/capture/helpers.rs).

## Transport and framing

- Address: Unix stream socket `/tmp/uds.recap`.
- The Python server removes a stale pathname at startup, listens with `asyncio.start_unix_server`, and chmods the socket to `0777`.
- This is **not gRPC on the wire**, despite the proto declaring a streaming gRPC service and Recap retaining a crate named `video_inference_grpc`. Both directions use raw serialized protobuf messages with a custom length prefix.
- Each record is `uint32_le byte_length` followed by exactly that many bytes from `SerializeToString`/prost `encode_to_vec`.
- Client-to-server records contain one `Frame`; server-to-client records contain one `Action`.
- Keep one full-duplex connection open and continuously write frames/read actions. There is no request count, version negotiation, magic, heartbeat, authentication, acknowledgement, or checksum.
- Frame IDs are the only request/response correlation mechanism. The server copies `Frame.id` to `Action.id`; responses are otherwise ordered by completed inference.
- There are no protocol timestamps. Recap records a local monotonic `Instant` immediately before writing each frame and computes round-trip latency when the matching action ID arrives.

Reference framing:

```text
client -> server: [4-byte little-endian N][N-byte Frame protobuf] ...
server -> client: [4-byte little-endian M][M-byte Action protobuf] ...
```

## Complete protobuf schema

```proto
syntax = "proto3";
package elefant.training_data.shared;

message Vec2Float {
  double x = 1;
  double y = 2;
}

message Vec2Int {
  int32 x = 1;
  int32 y = 2;
}
```

```proto
syntax = "proto3";
package elefant.training_data.video_inference;
import "shared.proto";

message Frame {
  int32 width = 1;
  int32 height = 2;
  bytes data = 3;
  int32 id = 4;
}

message MouseAction {
  oneof mouse_change {
    Vec2Int mouse_delta_px = 1;
    Vec2Float mouse_pos = 2;
  }
  Vec2Int scroll_delta_px = 3;
  repeated string buttons_down = 4;
}

message Action {
  repeated string keys = 1;
  int32 id = 2;
  MouseAction mouse_action = 3;
}

service VideoInference {
  rpc InferVideo(stream Frame) returns (stream Action) {}
}
```

Field semantics:

| Message.field | Meaning |
|---|---|
| `Frame.width`, `height` | Dimensions used by the server to reshape `data` as HWC. Recap sends 192 and 192. Both must be positive and consistent with `data`; upstream does not validate cleanly before reshaping. |
| `Frame.data` | Uncompressed, tightly packed, row-major RGB24: `R,G,B,R,G,B...`, exactly `width*height*3` bytes, no stride padding or alpha. |
| `Frame.id` | Client-selected signed int32 correlation ID. Recap starts at 1 and increments once per captured inference frame. No wrap handling is present. |
| `Action.keys` | Complete snapshot of model-held keyboard keys for this step, not press/release events. |
| `Action.id` | Exact echoed frame ID. |
| `Action.mouse_action` | Complete mouse snapshot/change. Open-P2P always emits it. |
| `MouseAction.mouse_delta_px` | Signed relative X/Y motion. This is the variant Open-P2P emits. |
| `MouseAction.mouse_pos` | Schema alternative described as fractional window position, but Open-P2P never emits it. Recap passes the doubles directly to `rdev::MouseMove` as absolute coordinates without multiplying by window size, so the comment and implementation disagree. Do not rely on it. |
| `MouseAction.scroll_delta_px` | Optional signed X/Y wheel delta. Open-P2P never populates it. Recap forwards it to `rdev::Wheel`. |
| `MouseAction.buttons_down` | Complete snapshot of held buttons, not edge events. Open-P2P emits numeric strings: `"0"` left, `"1"` right, `"2"` middle. Recap also accepts `Left`, `Right`, and `Middle`, but the model does not emit those forms. |

Proto3 absent/default behavior matters: an absent vector message behaves like no change; numeric scalar components default to zero; repeated fields default empty. Unknown fields should be ignored normally.

## Frame capture and preprocessing

Recap's exact path is:

1. Capture the selected window's **client area** using GStreamer's `d3d12screencapturesrc`, Windows Graphics Capture (`capture-api=wgc`), with `show-cursor=true`.
2. Request 20 fps.
3. For its recording/inference branch, scale the captured client area to height 480 and width `round(source_width * 480/source_height)`, rounded upward to a multiple of four. This preserves aspect ratio at this intermediate stage.
4. Convert to tightly packed RGB24 with square pixels.
5. Directly Hamming-resize the entire intermediate image to 192×192 using `fast_image_resize`.
6. Send those 110,592 bytes in one `Frame` message.

There is no crop, center crop, letterbox, padding, normalization, JPEG/PNG/video compression, BGR conversion, or batch of multiple frames. A non-square window is deliberately stretched to a square at the last resize. The server accepts other dimensions and applies the same Hamming resizer to 192×192, but a Linux client should send the already-resized 192×192 RGB frame to match Recap and avoid ambiguity.

For X display `:1`, match Recap by capturing the chosen window's client/content area, including a composited cursor, converting to RGB24, then Hamming-resizing the full image to 192×192. Do not preserve aspect ratio in the final square, crop, or letterbox.

## Actions and Linux event conversion

The trained output key vocabulary is limited to at most four simultaneously held unique keys from:

```text
Space  1 2 3 4  a d e f q w s z
DownArrow UpArrow LeftArrow RightArrow LeftShift RightShift
```

Strings are case-sensitive. Recap's parser accepts many additional key names, but the model mapping marks them ignored and cannot produce them. For Linux, map these names to the corresponding evdev key codes (for example `Space -> KEY_SPACE`, `w -> KEY_W`, `LeftShift -> KEY_LEFTSHIFT`, `UpArrow -> KEY_UP`). Maintain a previous held-key set for each connection:

- new key in current snapshot: emit key-down;
- previous key missing from current snapshot: emit key-up;
- present in both: emit nothing.

Do the same edge conversion for mouse button snapshots (`0 -> BTN_LEFT`, `1 -> BTN_RIGHT`, `2 -> BTN_MIDDLE`). Release all client-injected held keys/buttons on disconnect, inference pause, error, and session stop.

`mouse_delta_px.x/y` are signed integers in the model's captured relative-motion units. Recap applies them unchanged with Windows `SendInput`, `MOUSEEVENTF_MOVE`, `dx=x`, `dy=y`. It disables Windows pointer acceleration for the Recap lifetime and restores it on exit. There is no Recap multiplier, sensitivity normalization, DPI conversion, window-size scaling, or smoothing. Game sensitivity is external; upstream's tested settings are Roblox 0.52, DOOM smoothing 2× and look/move 22%, and Quake sensitivity 3.5 with smoothing disabled.

For Linux, inject each action as relative `REL_X=x`, `REL_Y=y` motion through uinput (preferred for games) or equivalent relative X11 input, with no extra scale. Preserve sign (`+x` right, `+y` down in the Windows/evdev convention). Configure the game/desktop acceleration and game sensitivity separately to reproduce training behavior.

The default `truncated_normal` decoder samples integer deltas from learned bins. X covers approximately -501..501 and Y -151..151 at the extreme bins; this sampling happens server-side. The client must not re-bin or resample.

## Text instruction channel

Text is **not part of the socket protocol** and there is no text field in `Frame`.

- Start the server with `--input_text`; launch mode cannot be toggled later because the model graph differs.
- The server reads nonempty UTF-8 lines from its own stdin. Each line atomically replaces the current instruction.
- The latest line persists. The inference worker reads that shared value immediately before every model step, so it can change on any step, independently of frame messages.
- Empty lines are ignored. There is no socket acknowledgement or instruction ID.
- Without `--input_text`, the shared value is `None` and the socket client cannot enable text.

A Linux game client that needs dynamic text must therefore also control the inference process's stdin (pipe/FIFO/PTY), or Open-P2P's protocol must be deliberately extended. Do not append text bytes to a `Frame`; the server would interpret them as the next length prefix.

### Tokenizer/model repository used on this host

Open-P2P's `GemmaTextTokenizerConfig` names gated `google/embeddinggemma-300M`. Despite the class name, it loads the complete SentenceTransformer, uses its tokenizer, runs its transformer, then mean-pools a 768-dimensional embedding; tokenizer files alone are insufficient.

This installation sets `P2P_GEMMA_MODEL_ID=unsloth/embeddinggemma-300m`. Local SHA-256 values are:

| File | Bytes | SHA-256 |
|---|---:|---|
| `tokenizer.model` | 4,689,074 | `1299c11d7cf632ef3b4e11937501358ada021bbdf7c47638d13c0ee982f2e79c` |
| `tokenizer.json` | 33,385,008 | `6852f8d561078cc0cebe70ca03c5bfdd0d60a45f9d2e0e1e4cc05b68e9ec329e` |
| `model.safetensors` | 1,211,486,072 | `cbf5a78393b6a033e0b8a63a57549964f7ed5c6fbeb4ba0694214f36123f2fd2` |

The Hugging Face APIs show the same sizes for the gated Google files, and the byte hashes above are identical across four independently named ungated repositories checked (`unsloth`, `michaelfeil`, `h2oai`, and `kp-forks`). The gated Google endpoint returns HTTP 401 and redacts its LFS object hashes without a token, so a direct Google-to-mirror byte comparison was not possible. This is strong multi-mirror evidence, not cryptographic proof against the gated origin. Runtime compatibility was verified by loading the mirror and completing a text-conditioned 1200M socket inference.

## Session lifecycle and low-latency loop

There are no start, reset, pause, resume, or stop protobuf messages.

- Session start: open a Unix stream connection. The server creates an inference worker and resets its KV-cache inference state for that connection.
- Session stop: close/shutdown the stream. EOF ends request iteration and the server closes its side. The server process and socket listener remain alive.
- Server stop: SIGINT/SIGTERM closes the listener and removes `/tmp/uds.recap`.
- Avoid concurrent clients: the server owns one model/inference-state object and upstream explicitly says it is only functional for one state at a time.

Recap's UI/session controls are outside the wire protocol: `Shift+]` starts/stops capture with inference, any real key/button press pauses model control, and `[` resumes. While paused, Recap can continue transport/inference but does not apply returned actions. Capture stop closes the inference tasks and releases simulated keys/buttons.

Low-latency behavior:

1. Capture runs nominally at 20 Hz (one frame every 50 ms).
2. GStreamer AppSink is configured `drop=true`; Recap then feeds a one-slot lag channel that overwrites an unsent old frame with the newest.
3. The writer records `send_time[id]`, writes length+protobuf, and continues accepting latest frames.
4. The server reader converts HWC RGB bytes to CHW uint8 and puts frames in a thread-safe queue.
5. Before inference, the model thread drains the queue and retains only the newest queued frame. Dropped frames produce no actions.
6. The model emits one action for the retained frame. The server writes length+protobuf.
7. The client matches `Action.id`, measures send-to-receive latency, and immediately applies snapshot edges plus relative motion.

Therefore IDs need not be contiguous in received actions. Do not wait forever for every sent ID, and do not run a strict request/response lockstep loop if capture must stay current. Keep independent sender and receiver tasks and tolerate dropped IDs.

## Minimal pseudo-client

This assumes generated `video_inference_pb2` classes and separate platform functions for capture/resize/uinput:

```python
sock = unix_stream_connect("/tmp/uds.recap")
next_id = 1
held_keys = set()
held_buttons = set()
send_times = {}

async def sender():
    global next_id
    every_50_ms:
        # Capture selected X11 client/content area on DISPLAY=:1, including cursor.
        rgb = capture_window_rgb24(display=":1", include_cursor=True)
        rgb192 = hamming_resize(rgb, width=192, height=192)  # stretch; no crop/pad
        frame = Frame(width=192, height=192, data=rgb192, id=next_id)
        payload = frame.SerializeToString()
        await sock.write_all(u32_le(len(payload)) + payload)
        send_times[next_id] = monotonic_ns()
        next_id = int32_increment(next_id)

async def receiver():
    global held_keys, held_buttons
    while True:
        n = from_u32_le(await sock.read_exact(4))
        action = Action.FromString(await sock.read_exact(n))
        observe_latency(action.id, monotonic_ns() - send_times.pop(action.id, now()))

        current_keys = set(action.keys)
        for key in current_keys - held_keys: uinput_key(key, down=True)
        for key in held_keys - current_keys: uinput_key(key, down=False)
        held_keys = current_keys

        mouse = action.mouse_action
        current_buttons = set(mouse.buttons_down)
        for b in current_buttons - held_buttons: uinput_button(b, down=True)
        for b in held_buttons - current_buttons: uinput_button(b, down=False)
        held_buttons = current_buttons

        if mouse.HasField("mouse_delta_px"):
            uinput_rel(mouse.mouse_delta_px.x, mouse.mouse_delta_px.y)  # no scaling
        if mouse.HasField("scroll_delta_px"):
            uinput_wheel(mouse.scroll_delta_px.x, mouse.scroll_delta_px.y)
        uinput_sync()

try:
    run_concurrently(sender(), receiver())
finally:
    release_all(held_keys, held_buttons)
    sock.close()
```

Production code should bound/prune `send_times`, reject unreasonable length prefixes before allocating, validate `len(data) == width*height*3`, handle int32 ID wrap, and always release injected state in `finally`/signal handlers.

## Known quirks relevant to a replacement client

- The `.proto` service declaration is historical; using a gRPC client will not work against `/tmp/uds.recap`.
- No timestamp, instruction, session-control, or error message exists on the wire.
- Recap's `mouse_pos` comment says fraction of window size, but its implementation treats values as direct absolute coordinates. It is unused by Open-P2P.
- Server preprocessing trusts frame dimensions/data enough that malformed frames can raise reshape errors.
- Recap and the server each drop stale frames independently. Missing action IDs are expected under load.
- Open-P2P's mouse button strings are numeric; do not assume `Left`/`Right`/`Middle` output.
- Key/button fields are held-state snapshots, not one-shot taps. A Linux client must synthesize edges and release state on every termination path.
