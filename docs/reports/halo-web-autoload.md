# Halo m8 web automatic game-data report

## Result

The localhost package now imports a colocated `maps/` folder into browser storage automatically on a fresh visit. It uses the existing worker's validation and copy path, including `ui.map`, map signatures/cache version/build checks, storage quota handling, and the final `.complete` marker. A completed browser store bypasses the manifest entirely on later loads. `?autoload=0` keeps the manual flow.

Commit: `31d9fb19043af9b31a81446bef8f5356233c39cc` (`m8-web`)

Artifacts:

- `/home/minjune/m8work/web-dist/halo-m8-web/`
- `/home/minjune/m8work/web-dist/halo-m8-web.tgz`
- tarball SHA-256: `98fb0fb2a87917bc4d428ae812456f3048a3f61cb2676d1ea6902d5df3b0cb8f`
- `/home/minjune/m8work/codex-out/opence-m8-web.patch` (full binary-safe diff from `m8-linux`)

Neither package artifact contains a `maps/` directory or any map file.

## Changed files

- `port/web/site/app.js`: localhost autoload discovery/progress, completed-store bypass, `?autoload=0`, and automatic microphone start only for an already-granted permission.
- `port/web/site/xiso-worker.js`: validated same-origin manifest source with 4 MiB bounded HTTP range reads, feeding the existing checked-file/copy implementation.
- `tools/make_maps_manifest.py`: Python 3.9+ stdlib generator for `maps/manifest.json`.
- `tools/web_serve.py`: refreshes the manifest at startup when the served root has `maps/`.
- `port/web/site/index.html`, `port/web/README.md`: local-package and query-parameter documentation.
- `port/web/tests/xiso.test.js`: ranged manifest source and validation coverage.
- packaged `README-MAC.md`: automatic first-visit and already-granted microphone instructions.

`ninja web` completed, the JavaScript suite passed all 14 tests, and the packaged server returned the required COOP/COEP/CORP headers. Its stamped commit is `31d9fb19`.

## Browser verification

The test used a fresh persistent profile in headless Google Chrome with SwiftShader, fake media devices, pre-granted microphone permission, a symlink to `build/linux/maps`, and only the dummy endpoints `ws://127.0.0.1:9/game` and `/mic`. It never contacted the real m8py.

- First automatic progress: 1.54 s, with no chooser interaction.
- All 24 maps / 1.86 GB ready: 11.11 s.
- Streaming: 479 range requests; no whole-map response was accepted.
- Reload: no second manifest request and the import panel remained hidden.
- Microphone: automatically changed to `Reconnecting…`/“Turn microphone off,” confirming capture was enabled from existing permission (the dummy port intentionally cannot connect).
- `a10`: the game reached its first frame at 19.59 s overall. Console evidence included `init: map_name levels\\a10\\a10`, `starting precaching of map 'a10'`, WebGL 2 initialization, and the campaign map's menu/HUD setup. As expected for this worker-rendered headless run, the game screenshot itself is black; the frame watcher and game log establish startup.

Screenshots:

- `/home/minjune/m8work/logs/web-autoload-importing.png`
- `/home/minjune/m8work/logs/web-autoload-complete.png`
- `/home/minjune/m8work/logs/web-autoload-reload.png`
- `/home/minjune/m8work/logs/web-autoload-a10.png`

## Deploy on the Mac

Stop the current `web_serve.py` with Ctrl-C. Copy the new `halo-m8-web.tgz` to the Mac, then extract it over the existing folder; because the archive contains no `maps/`, the existing `~/halo-m8-web/maps/` remains in place:

```sh
cd ~
tar -xzf ~/Downloads/halo-m8-web.tgz
cd ~/halo-m8-web
python3 web_serve.py
```

The server prints that it refreshed `~/halo-m8-web/maps/manifest.json`. Leave it running and open:

<http://localhost:8000/?m8=ws://100.126.232.8:8091/game>

On a browser profile without stored maps, the Game data panel imports automatically. On later visits it immediately uses the completed browser copy. If microphone permission was granted previously, the streamer also starts automatically; otherwise use the existing button and permission prompt.
