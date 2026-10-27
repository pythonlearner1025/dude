# m8py port notes

Intentional changes from the Rust reference, required by `docs/port-spec.md`:

- Runtime concurrency is one asyncio event loop; CPU/VAD work and microphone callbacks cross
  into it safely instead of using Rust threads and blocking channels.
- Logs use `logs/<session>/trace.jsonl` (plus spans, GPU samples, audio, views and report) rather
  than Rust's flat `logs/<session>.jsonl`. The unchanged history UI is backed by compatible
  `/sessions`, `/session`, and `/view` routes.
- The site bind/port and game bind are configurable. Rust fixes them at loopback/8090 and
  loopback respectively.
- Remote microphone input and instrumentation are additions. A simple energy-VAD fallback is
  available only when Silero cannot be loaded, so mock-only commands remain usable without a
  model file; real configurations are expected to supply Silero and use the Rust thresholds.
- PNG encoding uses Pillow at compression level zero. Pixel content and marker drawing match
  Rust; PNG container bytes can differ because Pillow chooses its own zlib block layout.
- `voice-design` uses Breeze's confirmed reference-free request fields: `text`, `instruction`,
  `cfg_scale=4`, and `seed`, with no reference fields.

Open question: sherpa-onnx Python wheels occasionally rename recognizer/VAD constructor
properties between releases. The implementation targets the API in the locked wheel and the
mock suite does not instantiate model inference.
