# Co-opting existing games for an AI companion runtime

Research cutoff: 27 October 2026. This report treats the local [`m8`](https://github.com/chasmlol/m8) design as the reference contract: a game adapter sends textual state, legal actions and events (plus optional marked screenshots), receives a high-level action, and plays streamed speech in the game. Fast locomotion/combat should remain in game-native code; the language model should select intentions, not synthesize every keypress.

## Executive recommendation

- **Minecraft Java:** start with a **Mineflayer second client** on a private Paper server, plus a small Paper/Fabric voice bridge using Simple Voice Chat. Mineflayer gives the most player-like body and widest action surface for the least game-specific work. Add a server plugin only for authoritative state/event enrichment and voice. Use a Fabric/NeoForge entity only if “one extra account/client” is unacceptable or the companion must exist in single-player without opening LAN.
- **Rust:** run a **private server in the Modded browser category**, load Carbon or Oxide/uMod, and embody the mate as a server-spawned scientist/custom `BasePlayer`-derived NPC. A C# plugin should own sensing, deterministic combat/navigation, and the socket to m8. Player microphone packets are available through `OnPlayerVoice`; generated positional voice is the research-risk item, because the public evidence is an unofficial, old voice-packet streaming proof of concept rather than a supported Facepunch API. Ship text/radio or non-speech game sounds first if that prototype fails on the current protocol.
- **General runtime:** build adapters in descending order of fidelity: official scripting/mod API → engine mod loader → server plugin → reflection/memory bridge → pixels plus input. Keep m8’s semantic action protocol stable and let each adapter advertise only actions it can execute robustly.

---

## 1. Minecraft Java

### Integration choices

#### A. Mineflayer bot client — recommended first route

[Mineflayer](https://github.com/PrismarineJS/mineflayer/blob/master/docs/README.md) is a JavaScript implementation of a Minecraft Java client. It logs into a server as a separate player and exposes entity tracking, nearby blocks, physics, health/weather, inventory, crafting, digging/building, item use, vehicles, combat and chat. Its [API](https://github.com/PrismarineJS/mineflayer/blob/master/docs/api.md) exposes the bot's own entity, nearby entities, a synchronized partial world, block updates, inventory and game events. This maps unusually cleanly to m8.

**Perception.** On a low-rate semantic tick (for example 2–5 Hz, plus event-driven updates), derive prose from:

- `bot.entity`, health, food, held item, effects and inventory;
- `bot.entities`, filtered by distance, line of sight, type, hostility and relationship;
- `bot.world`/`blockAt`/`findBlocks`, but only within loaded chunks and the bot's server-supplied view distance;
- chat, damage, death, item pickup, block update, window/inventory and pathfinder events;
- an optional [Prismarine Viewer](https://github.com/PrismarineJS/prismarine-viewer) first-person frame for m8's screenshot/marked-spot path.

Mineflayer's world is what this client has received, not an omniscient server snapshot. That is a useful fairness boundary but means unloaded chunks, protected-region rules and server-side plugin state are invisible unless a companion Paper plugin enriches the feed.

**Action.** Use atomic Mineflayer calls for look/use/equip/dig/place/attack/craft/container operations and [`mineflayer-pathfinder`](https://github.com/PrismarineJS/mineflayer-pathfinder) for movement. Its path events distinguish success, partial path, timeout, no-path and stuck/reset causes, which should become m8 events rather than leave a language model guessing. Combat can use deterministic code or [`mineflayer-pvp`](https://github.com/PrismarineJS/mineflayer-pvp). An action catalogue should be generated from actual preconditions: do not offer `craft`, `give`, `eat`, `mine`, `sleep` or `revive` unless the necessary item, recipe, block and reachability checks pass.

**Body semantics.** This is a real protocol-level player: it has a name/skin, inventory, damage, hunger, permissions and a place in tab lists and teams. It needs a server slot and, on an online-mode server, a legitimate Microsoft/Minecraft account. A private offline-mode development server can avoid a second account but weakens authentication and is unsuitable when exposed to the internet. Public servers may prohibit automation or flag its movement; obtain owner permission rather than treating protocol compatibility as permission.

**Latency and robustness.** Local state/action calls and path following operate at game/network cadence; only high-level m8 decisions incur model latency. That division is appropriate for survival and combat. Robustness costs are version churn, protocol/authentication changes, anti-cheat heuristics, unloaded terrain and Mineflayer edge cases around newly introduced mechanics. Pin the Minecraft server, Mineflayer and plugins together and test a task suite after every update.

**Prior art.** These are useful code sources, not drop-in product dependencies:

- [Mindcraft](https://github.com/mindcraft-bots/mindcraft) puts an LLM over Mineflayer commands and optionally lets it write new JavaScript actions. Its own warning says coding is unsafe on public servers; for m8, keep runtime code generation off and reuse its command/action patterns.
- [Voyager](https://github.com/MineDojo/Voyager) uses an automatic curriculum, iterative code generation and an executable skill library; its paper/project reports 3.3× more unique items, 2.3× farther travel and up to 15.3× faster technology-tree milestones than its baselines. The transferable idea is a reviewed, versioned skill library, not online arbitrary-code execution.
- [Odyssey](https://github.com/zju-vipa/Odyssey) publishes 40 primitive and 183 compositional Minecraft skills, another good source for action decomposition.
- [Voxta Minecraft Companion](https://doc.voxta.ai/docs/integrations/minecraft) is close product prior art: a separate Minecraft client with live semantic context, microphone conversation, vision, crafting/building/combat/navigation and a character server.
- [ChatClef](https://github.com/elefant-ai/chatclef) combines a Fabric client mod, Player2, AltoClef and Baritone; it can control the local player or use a second client. This illustrates the alternative “possess the player's avatar” route, but that prevents simultaneous human and companion embodiment unless a second client is launched.

#### B. Fabric or NeoForge game mod

[Fabric networking](https://docs.fabricmc.net/develop/networking) and [NeoForge networking](https://docs.neoforged.net/docs/networking/) provide client/server payloads; even single-player has an integrated server. A mod can therefore read exact game objects and registries, subscribe to ticks/events, create an entity with custom goals, render UI/markers, capture a frame, and play audio on an entity-attached sound instance.

There are three possible bodies:

1. **Custom mob/NPC entity.** Best for single-player and zero extra account. It can carry a custom inventory/model and use vanilla goals or a custom controller. It is not a player: many mechanics, plugins, advancements, beds, menus, permission checks and combat assumptions special-case `Player`/`ServerPlayer`.
2. **Fake/server player.** Highest player fidelity but substantially more invasive: connection/network handlers and client assumptions expect a real connection. Maintenance rises sharply across mappings and releases. Treat it as a later route, not the MVP.
3. **Control the human player's avatar.** A client mod can inject movement/use/attack and use [Baritone's stable API](https://baritone.leijurv.com/) for goals, mining, building, following and exploration. It offers excellent state and input fidelity but is a copilot/autopilot, not a simultaneous teammate.

[Baritone](https://baritone.leijurv.com/) is especially useful in the client-mod variants. It accepts goals and high-level processes; its settings document bounded path-search timeouts (for example `failureTimeoutMS`) and known-chunk limits. Keep Baritone below m8: m8 selects “follow Alice” or “go near x,y,z”; Baritone replans every movement.

The cost is a Java/mappings port for every supported Minecraft release and installing the same required mod set on clients/server. Fabric is lean and broadly used; NeoForge offers a richer event/mod ecosystem. Neither changes the fundamental maintenance issue.

#### C. Paper server plugin

[Paper](https://docs.papermc.io/paper/dev/) exposes authoritative worlds, entities, inventories, events, persistent data, mob goals and plugin messaging without modifying vanilla clients. Its [Entity Pathfinder API](https://docs.papermc.io/paper/dev/entity-pathfinder/) can move any `Mob` toward a location/player, subject to vanilla movement capabilities.

A Paper-only companion should therefore be a mob/NPC-like entity with server-controlled goals. State fidelity is excellent on the server; action fidelity is excellent for entity/world operations but incomplete for “behave exactly like a player.” A plugin cannot make an unmodified client render an arbitrary new character model or accept a new voice protocol; use a disguised vanilla entity/player skin solution, a resource pack, and/or an optional client mod. Paper is ideal as an **authoritative sidecar to Mineflayer**: expose claims/regions, quest state, hostile targeting, save IDs and rich events while Mineflayer supplies the body.

Do not block the server tick with HTTP/model calls. Snapshot the minimum state on the main thread, send it to the local m8 socket asynchronously, and marshal accepted actions back to the server thread. m8's decision latency then cannot freeze simulation.

### Voice in and out

The best existing transport is [Simple Voice Chat](https://github.com/henkelmax/simple-voice-chat), which supports Fabric, NeoForge/Forge and Bukkit/Spigot/Paper with a client mod and a server-side mod/plugin. It uses a separate UDP port (24454 by default); players without its client mod cannot hear or transmit through it.

**Companion speech.** Its server API can create a 48 kHz, 16-bit PCM [`EntityAudioChannel`](https://voicechat.modrepo.de/de/maxhenkel/voicechat/api/audiochannel/EntityAudioChannel.html) attached to a Minecraft entity, set a distance/category/whisper flag, and stream samples via `AudioPlayer`. This is the direct equivalent of m8's Halo voice frame: the adapter receives m8 PCM, resamples to 48 kHz if necessary, queues it to an entity channel and signals `audio_end` when the player stops. Use a locational channel for a marker without an entity and a static channel for radio.

**Hearing the player.** [`MicrophonePacketEvent`](https://voicechat.modrepo.de/de/maxhenkel/voicechat/api/events/MicrophonePacketEvent.html) fires when an Opus microphone packet reaches the server and identifies its sender connection. An addon can decode packets and forward selected players' PCM to m8. Get explicit player consent, show capture/mute state, honor voice groups and distance, and avoid double-transcribing m8's ordinary OS microphone. The simplest private-server mode is: Simple Voice Chat is the sole microphone source; route only the paired human's packets to the companion.

If users will not install a voice client mod, the fallback is m8's existing OS microphone plus local PC audio. Vanilla server resource-pack sounds are finite assets and are not suitable for arbitrary streaming TTS.

### A buildable Minecraft adapter

**Phase 1 (small-team MVP):** Mineflayer + private Paper server + OS mic/audio.

1. A Node adapter owns `mineflayer`, pathfinder and deterministic skills.
2. Every event or 250–500 ms when materially changed, it emits concise state and preconditioned actions to m8.
3. It executes one high-level action at a time, emits started/completed/failed/stuck events, and permits an emergency deterministic interrupt.
4. A persona name maps to the bot account/skin. Saves are keyed by server/world identity and player UUID.
5. Optional screenshot frames come from Prismarine Viewer; semantic block/entity targets remain preferable.

**Phase 2:** add a Paper plugin for authoritative events and Simple Voice Chat addon for bidirectional positional audio. This combination preserves the real-player body while solving the two gaps Mineflayer alone cannot solve cleanly.

**3090 Ti fit.** Mineflayer, Paper, pathfinding and Opus are primarily CPU workloads. The 24 GB GPU can host one quantized conversational VLM/LLM plus small STT/TTS if models are selected to fit; do not assume the reference m8 stack's reported ~25 GB simultaneous footprint will fit unchanged. A 2–4B decision model is optional—legal-action scoring can be much smaller—and vision should be requested only on ambiguity.

### Multiplayer and legal constraints

Mojang's [EULA](https://www.minecraft.net/en-us/eula) explicitly permits original Java Edition mods, including in-memory mods, but prohibits distributing a modded copy of the game and asks that mods not be used for griefing. The [Usage Guidelines](https://www.minecraft.net/en-us/usage-guidelines) add branding, commercial and server rules and require unofficial status to be clear; Minecraft Support also says mods are third-party and [not officially supported](https://help.minecraft.net/hc/en-us/articles/4409139065613-Mods-for-Minecraft-Java-Edition-). These permissions do not override a particular server's rules. A Mineflayer bot should therefore default to single-player/LAN or an owner-controlled server, use a legitimate account on online-mode servers, and never attempt anti-cheat evasion.

### Implications for a general companion runtime

- Separate **embodiment** (Mineflayer/player, entity, or possessed avatar) from the m8 brain; expose the same semantic actions for all three.
- Prefer a real client when player mechanics matter; add a server plugin for facts the client cannot legitimately observe.
- Treat navigation/combat as local skills with completion/failure events, never token-by-token model control.
- Make voice a capability-negotiated channel: positional entity, radio/static, or out-of-game fallback.
- Version-pin and regression-test actions; Minecraft's fast release cadence is a larger reliability threat than model reasoning.

---

## 2. Rust (Facepunch)

### What is allowed and operationally sane

Facepunch documents how to [create a dedicated server](https://wiki.facepunch.com/rust/Creating-a-server) and optionally install Oxide for plugin support. Its March 2026 [plugin guidelines](https://support.facepunchstudios.com/hc/en-us/articles/360009062817-Guidelines-for-community-servers-using-plugins-mods) say gameplay-changing plugins belong in the **Modded** server section; the Community section permits only narrow non-gameplay/admin/chat categories. An AI teammate plainly changes gameplay. Run it on a passworded/private server or list it as Modded.

Do not inject into `RustClient.exe`, synthesize input into a public EAC-protected session, read client memory or attempt an EAC bypass. Facepunch says EAC cheating bans are normally permanent and does not disclose detection details ([EAC ban policy](https://support.facepunchstudios.com/hc/en-us/articles/214241045-EAC-Banned)); its troubleshooting documentation says EAC may mark applications “forbidden” ([support article](https://support.facepunchstudios.com/hc/en-us/articles/360019318037-EAC-Authentication-Timeout)). No official source found grants permission for an automated/modded client. This report therefore treats client injection as out of scope and high ban/ToS risk. Server-side plugins on an owner-controlled dedicated server are the supported practical boundary. If client-side research is indispensable, Facepunch documents launching `RustClient.exe` without EAC, which can connect **only to EAC-unsecure servers** ([official instructions](https://support.facepunchstudios.com/hc/en-us/articles/15041503601437-Launching-Rust-with-EAC-disabled-RustClient-exe)); that reduces anti-cheat collision but is not blanket permission to reverse engineer or redistribute the client.

### Server framework and bridge

[Oxide/uMod's Rust extension](https://umod.org/games/rust) supplies C# plugins, chat/console commands, RCON and hundreds of hooks. [Carbon](https://wiki.facepunch.com/rust/Carbon) is a Harmony-based, Oxide-compatible server framework with dynamic hooks and hot reload. Facepunch's own [Hooks guide](https://wiki.facepunch.com/rust/Hooks) explains that these frameworks insert `CallHook` sites into Rust server code.

For a new project, choose Carbon if its current Rust build support and Oxide compatibility pass the team's test suite; choose Oxide/uMod for the most conservative ecosystem path. Do not run both. In either case, create one small C# plugin with:

- an async localhost WebSocket/TCP connection to m8;
- main-thread state snapshotting and action execution;
- hook-driven event generation (`OnEntityTakeDamage`, death, loot, inventory, weapon, team, save, chat and voice hooks);
- persistent companion identity/memory key in plugin data;
- deterministic navigation, aiming, burst fire, healing, looting and revive state machines;
- watchdogs so an absent/slow m8 process cannot block the server tick. uMod explicitly cautions against heavy work in per-frame/tick hooks in its [Rust hook reference](https://umod.org/documentation/games/rust/).

### Body choices

#### Scientist/custom NPC — recommended

Rust's [modding overview](https://wiki.facepunch.com/rust/Modding_Overview) identifies scientists and player models as networked entities. Spawn an existing scientist/human NPC prefab and customize its display name, team/hostility, health, loadout, clothing and brain/controller. This requires no client files and is visible to ordinary clients.

Two implementation levels are viable:

1. **Wrap the stock scientist brain.** Let native AI handle locomotion, cover, aiming and combat; the plugin selects goals/targets, suppresses hostility toward its human and handles follow/hold/loot/revive. This is least code but behavior may be hard to bend into friendly teammate semantics.
2. **Own the controller.** Disable/replace selected brain states and drive navigation/animation/weapon use through server classes. This improves action fidelity but is coupled to Rust internals and monthly server updates.

The old community [HumanNPC](https://github.com/Remod-org/HumanNPC) plugin demonstrates persistent human-shaped NPCs, waypoints, kits, combat/chase settings and lifecycle/range/use hooks. It is useful source material, not a maintained Facepunch API contract; audit and port concepts rather than making it an unexamined production dependency.

#### Player-like server bot

A synthetic `BasePlayer` can look closer to a player, hold normal items and integrate with team/inventory systems. But Rust assumes real players have a network connection, authenticated identity, input stream and anti-cheat lifecycle. Community HumanNPC implementations work around those assumptions; they are more fragile than scientists and remain server entities rather than true remote clients. Use only if stock scientist limitations are unacceptable.

A headless, protocol-emulating Rust player client analogous to Mineflayer is not established by the verified sources in this research. **Unverified:** no current, reputable general Rust bot-client framework was found. Building one would mean private protocol reconstruction and a much larger EAC/policy and maintenance surface; it is not recommended.

### Perception and actions

The server has high-fidelity authoritative state: the companion entity, nearby `BaseEntity` objects, players/scientists/animals, line-of-sight queries, transforms, health/metabolism, held items/inventory, team relations, damage and world time. Convert only companion-plausible facts into m8 prose. Do not leak hidden stashes, distant players, sleeping players behind walls or admin-only map data merely because the server can see it.

Offer high-level actions only when executable:

- `follow/hold/go_to/retreat/take_cover` with destination or human target;
- `attack/defend/cease_fire`, target-filtered to visible hostiles;
- `loot`, `equip`, `reload`, `heal`, `give`, `drop`, `harvest`;
- `revive` if the human is wounded and reachable;
- `mount/dismount`, later, after vehicle-specific testing;
- `look` via server facts first; screenshots are difficult because the server has no rendered camera.

Use a local finite-state executor for every action. The LLM should never aim each projectile or drive each movement tick. Emit action results and material events back to m8, matching its search/then-action pattern.

### Voice: what is and is not supported

**Hearing the player is feasible.** uMod documents [`OnPlayerVoice(BasePlayer, byte[]/ArraySegment<byte>)`](https://docs.oxidemod.com/hooks/player/OnPlayerVoice), called when server voice data arrives; returning non-null can suppress normal forwarding. A plugin can copy—never retain a borrowed buffer—then decode/transcribe the selected player's voice externally. The bytes are Rust/Steam voice frames, not guaranteed PCM. The adapter needs a current decoder/packet parser, consent/mute controls, and backpressure. Leave normal proximity forwarding intact unless the private-server design explicitly replaces it.

**Speaking as the NPC is possible in principle but not a supported public API.** The best concrete evidence is the GPL-2.0 community proof of concept [Rust Voice Streaming Plugin](https://github.com/LucienMP/Rust-Voice-Streaming-Plugin), which spawns an NPC and sends fixed or web-streamed voice using reverse-engineered Steam/Rust audio packet framing. It has only four commits and documents packet assumptions from 2020. Treat current-build compatibility, codec framing, sequence/CRC details and spatial attribution as **unverified until a spike succeeds**. Rust's newer [RustRelay documentation](https://wiki.facepunch.com/rust/RustRelay) also says relay voice packets are off by default “for legal reasons,” another reason not to treat voice packets casually.

Practical fallback order:

1. Prototype current voice-packet injection on a local server/client pair and attach packets to the companion entity so Rust's proximity attenuation handles position.
2. If it is unstable, send companion text to team/local chat and play only existing game sound effects at the NPC.
3. Use m8's local TTS output outside the game as an accessibility fallback; spatialization is then lost.
4. A custom client audio mod would restore arbitrary positional TTS but crosses into EAC/client-mod risk and is not recommended for ordinary Rust clients.

### Rust+ is supplementary, not embodiment

The official [Rust+ companion](https://rust.facepunch.com/companion) exposes server/map information, team chat and paired smart-device control. The community [RustPlusApi](https://github.com/HandyS11/RustPlusApi) documents typed WebSocket access to server time/map/markers, team/clan chat, smart devices and cameras. This is useful for out-of-game notifications, radio text and base alarms, but it cannot spawn/control an NPC, access full local combat state or carry positional voice. Do not base the teammate loop on Rust+.

### A concrete Rust teammate build

1. Install a pinned Rust dedicated server plus Carbon or Oxide/uMod; password it and classify it Modded.
2. Write `M8Companion.cs`. On server initialization, spawn/load one scientist-derived companion and assign it to the paired player's team/friendly set.
3. Every material hook and at a bounded 2–5 Hz state cadence, serialize plausible nearby state and preconditioned actions to the local m8 service.
4. On an action reply, enqueue work onto the server thread and start a deterministic skill. Never await m8/LLM work on the server thread.
5. Capture `OnPlayerVoice`, copy frames to a bounded worker queue, decode and feed the same m8 STT/VAD path; expose a `/m8 mute` command.
6. Run a time-boxed voice-output spike. If it fails, ship chat plus out-of-game TTS rather than injecting the client.
7. Regression-test after every Rust server update: spawn, follow, nav around bases, elevators/doors, friendly fire, combat, loot, wounded/revive, disconnect/reconnect, save/reload and voice.

This is buildable by a small team because all authoritative control stays server-side and GPU use remains in m8. Rust server simulation and NPC AI are CPU/RAM work; the 3090 Ti has the same model-sizing constraint described for Minecraft.

### Implications for a general companion runtime

- A server-authoritative game may expose more state than the character should know; adapters need an explicit **perception policy**, not just serialization.
- “NPC-shaped entity” is often the safest universal body even when it is less player-like.
- Capability negotiation must distinguish `voice_input`, `positional_voice_output`, `chat_output` and `local_tts`; Rust cannot honestly advertise all four before a protocol spike.
- Keep reverse-engineered packet paths quarantined behind versioned modules and graceful fallbacks.
- Private/modded-server support is a product boundary, not an installation footnote; public client automation is the wrong first target.

---

## 3. General patterns for any game

### Integration ladder

| Route | State fidelity | Action fidelity | Typical latency | Per-game work | Main failure/risk |
|---|---|---|---|---|---|
| Official mod/script API or open-source port | Exact typed state/events | Exact engine calls | Tick-level | Medium | Version/API maintenance; content licence |
| Server plugin | Authoritative, sometimes over-complete | Strong for server entities/world; weaker for local UI/player input | Tick/network-level | Medium | Requires owner-controlled server; fairness filters |
| Engine mod loader/reflection | High typed/reflected state | High if engine functions are callable | Tick-level | Medium–high | Injection, update breakage, anti-cheat/ToS |
| Memory read + input injection | High but brittle/untyped | Human-like inputs or unsafe writes | Read/input cadence | High | Address drift, crashes, bans, security concerns |
| Pixels + keyboard/mouse | Only visible/audible state | Human interface only | Model-dependent; usually highest | Low initial, high reliability work | Visual ambiguity, precision, long-horizon memory |
| Hybrid semantic mod + vision + local skills | High where instrumented, visual elsewhere | High-level engine skills plus human UI | Low for skills; model only on ambiguity | Medium | More components, but best practical trade-off |

#### Game-specific source modifications and script APIs

The best case is an open reimplementation/decompilation such as m8's current [OpenCE](https://github.com/OpenCommunityEdition/OpenCE) target, or a game with official Lua/console/mod SDK. The adapter can enumerate entities, events, saves and legal actions, attach TTS to the engine's positional audio, and serialize companion memory into saves. This is maximum fidelity and minimum runtime uncertainty, but every new game needs intimate source/engine work and may have content/licensing restrictions distinct from the open code.

For Unity games, [BepInEx](https://docs.bepinex.dev/) provides C# plugins, Harmony runtime method patches and in-memory assembly patching for Mono games; its current docs also describe separate [IL2CPP builds](https://docs.bepinex.dev/master/articles/user_guide/installation/unity_il2cpp.html). [MelonLoader](https://github.com/LavaGang/MelonLoader) is a comparable Unity mod loader; exact title compatibility must be tested. For Unreal Engine 4/5 shipping games, [UE4SS](https://docs.ue4ss.com/dev/lua-api) can find/enumerate `UObject`s, read/write reflected fields, call functions, register UFunction/map/begin-play hooks and construct objects through Lua/native mods. These tools can produce a rich m8 adapter without source access.

For RE Engine titles, [REFramework](https://refdocs.praydog.com/) exposes Lua, object/singleton inspection and native DLL plugins. [ReShade](https://reshade.me/) is valuable for frame/depth capture and overlays, but it is principally a post-processing injector; it should complement, not substitute for, a game-state/action bridge.

All injection routes should be restricted to offline/single-player titles that permit modding. They load code inside the game process, can crash after updates and resemble cheat techniques to anti-cheat systems. Never market “works with any game” as “safe in any multiplayer game.”

#### Memory reading and input control

External memory readers can recover position, health, inventory and entity arrays where no loader works; keyboard/mouse emulation can act without writes. Fidelity can be high after reverse engineering, but every patch can invalidate signatures/layouts. Direct writes/hooks raise both stability and anti-cheat risk. This route also creates a provenance problem: the runtime may reveal hidden state a human character could not perceive.

Use only after an explicit game/publisher policy review, only offline, and prefer read-only memory plus ordinary input. Put signatures behind a version fingerprint, fail closed when validation changes, and never implement anti-cheat evasion.

#### Vision-only generalist agents

Vision-only agents capture the screen, accept language, and emit ordinary keyboard/mouse actions. They require no game API and therefore generalize furthest, but currently trade away state certainty, precise timing and robustness.

- Google DeepMind's [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) observes pixels and language and acts through keyboard/mouse without game APIs. It adds Gemini reasoning, conversation and self-improvement, but DeepMind explicitly reports short memory (kept short for low latency), long-horizon difficulty, precise-control problems and imperfect 3D visual understanding. It is a limited research preview, not a downloadable consumer runtime.
- NVIDIA's [NitroGen](https://arxiv.org/abs/2601.02427) is an open vision-action foundation model trained from roughly 40,000 hours across 1,000+ games; the paper reports up to 52% relative success improvement over from-scratch models on unseen games. Model/data/evaluation release makes it the most relevant candidate to examine for a local low-level policy, but benchmark transfer is not equivalent to reliable companionship.
- [Lumine](https://arxiv.org/abs/2511.08892) processes raw pixels at 5 Hz and produces keyboard/mouse actions at 30 Hz, using higher-level reasoning only when needed. It reports five-hour storyline completion in Genshin Impact and zero-shot missions in Wuthering Waves and Honkai: Star Rail. Its two-rate design strongly supports m8's separation of deliberation from motor control.
- [Game-TARS](https://arxiv.org/abs/2510.23691) uses a unified native keyboard/mouse action space and sparse reasoning; the paper reports about 2× the previous state of the art's Minecraft success and pretraining on over 500B tokens. It is evidence for the interface, not a one-GPU small-team deployment plan.

These names and capabilities are verified; no claim is made that their full training stacks fit a 3090 Ti. For a small team, use an available small vision-action model only for navigation/UI fallback and keep the relational companion, memory and semantic decisions in m8.

#### Hybrid: recommended general architecture

The practical universal design is a three-speed hybrid:

1. **Fast controller (10–60 Hz):** engine AI, Baritone/behavior tree, or a compact vision-action policy handles aiming, stepping, cover and collision.
2. **Semantic adapter (event-driven, roughly 2–5 Hz):** game mod/plugin converts typed state into concise prose and advertises safe, currently legal high-level actions.
3. **Companion brain (human-turn cadence):** m8 decides intention and whether to speak; the conversational model writes a short line; streaming TTS begins before the full line is complete.

Vision is a tool invoked for “what the player is pointing at?”, spatial ambiguity or UI that the adapter has not instrumented—not the default state channel. This preserves generality without throwing away free, exact game state.

### Effort and risk controls

- Define an adapter capability manifest (`body=player|npc|possessed`, `state=semantic|visual|hybrid`, `voice=entity|location|radio|local`, `save`, `screenshot`, action schemas).
- Require every action to have preconditions, timeout, cancellation, completion/failure events and a deterministic emergency stop.
- Add a “plausible perception” filter to server/memory adapters.
- Fingerprint game version and refuse known-unsafe writes/hooks after updates.
- Maintain a per-game policy sheet: official mod terms, server rules, anti-cheat presence, private/offline restriction and redistributable components.
- Benchmark end-to-end **speech end → useful action**, **speech end → first audible response**, stuck rate and intervention rate—not just LLM tokens/second.

### Implications for a general companion runtime

- “Any game” should mean a stable runtime plus a graded adapter ladder, not zero integration work.
- Hybrid instrumentation is the sweet spot: semantic state for reliability, screenshots for open-ended reference, local skills for latency.
- The brain protocol should be engine-neutral; game adapters own fairness, physics and version-specific mechanics.
- A one-GPU product should spend model compute on personality/ambiguous reasoning and use classical/game-native control everywhere else.
- Risk must be a runtime capability: disable input/injection automatically in anti-cheat/public-server contexts.

---

## 4. Prior art: companions built for fun and relationship

### Mods: breadth and personality, with visible seams

[Mantella](https://art-from-the-machine.github.io/Mantella/) connects Skyrim and Fallout 4 NPCs through STT → LLM → TTS, with persistent conversation memory, world awareness, vision and 20+ actions such as follow, attack, trade and travel. It can run locally or through APIs and covers thousands of existing NPCs. Its strength is reuse of authored worlds, voices and character backgrounds; its weakness is that generated conversation sits beside animation, quest and combat systems never designed for it. A March 2025 [hands-on review](https://www.uploadvr.com/playing-skyrim-vr-with-chatgpt-powering-npc-conversations/) found noticeable latency, improved by switching model/provider. A 2026 [PC Gamer report](https://www.pcgamer.com/games/the-elder-scrolls/this-skyrim-mod-that-makes-npcs-ai-chatterboxes-just-got-a-massive-overhaul/) described pre-update speech as stilted/rudimentary and recalled an AI follower repeatedly failing a simple puzzle, while still finding the result surprising and impressive.

[Herika / CHIM](https://github.com/Dwemer-Dynamics/HerikaServer) uses an SKSE client plus a server bridging LLM, STT, TTS and vector-backed long-term memory. It began as a named follower and evolved toward general character infrastructure. Community reports are positive about immersion but also show the exact failure modes: [one user](https://www.reddit.com/r/skyrimvr/comments/181mmm6) reported the model breaking character by saying it was an OpenAI model, and [another](https://www.reddit.com/r/skyrimvr/comments/1996tym) attributed response delay to the ElevenLabs voice round trip. These are anecdotes, not controlled measurements, but they align with formal literature.

Design lesson: inherited lore and voices create immediate attachment, but a companion needs constrained action tools, world-grounded retrieval, latency masking and an explicit character-integrity evaluator. “Can talk about anything” is less valuable than “remembers the right things and behaves reliably.”

### Minecraft societies and friends

[Project Sid](https://arxiv.org/abs/2411.00114) from Altera (now generally branded Altera; repository at [altera-al/project-sid](https://github.com/altera-al/project-sid)) studied 10–1,000+ LLM agents in Minecraft using the PIANO orchestration architecture and reported specialization, collective rules and cultural/religious transmission. It is important evidence for scalable agent social simulation, but it is not primarily a low-latency embodied friend product and its large-agent demonstrations do not imply one-consumer-GPU operation.

Mindcraft, Voxta and the Fabric [AI Companion mod](https://github.com/Vex-Caine/mc-1.21.1-ai-companion-mod) show demand for a persistent Minecraft friend, but most inherit Mineflayer's mechanical gaps and LLM latency. The useful pattern is one named, persistent character with a bounded tool set; many-agent “civilization” technology is not necessary for m8's first target.

### Studio prototypes and deployed co-playable characters

Ubisoft's [NEO NPC](https://news.ubisoft.com/en-us/article/5qXdxhshJBXoanFZApdG3L/how-ubisofts-new-generative-ai-prototype-changes-the-nature-of-npcs) (GDC 2024) combined writer-authored character/backstory with Inworld's language technology and NVIDIA Audio2Face. Ubisoft explicitly called it a prototype and documented a revealing character-design failure: an attractive female character drifted toward flirtatious answers and had to be reworked. This supports human-authored persona boundaries and ongoing evaluation rather than raw prompting.

Ubisoft's later [Teammates](https://news.ubisoft.com/it-it/article/3mWlITIuWuu0MoVuR6o8ps/ubisoft-reveals-teammates-an-ai-experiment-to-change-the-game) (closed testing announced November 2025) placed voice-responsive squadmates Pablo and Sofia plus assistant Jaspar into an FPS. Jaspar can highlight threats/objects, explain lore/objectives, alter settings and pause the game. This is the same architectural split m8 should use: a grounded assistant/tool layer plus embodied characters, with authored personality above deterministic mechanics. **Unverified public metric:** Ubisoft has not published a controlled retention/engagement result in the sources reviewed.

[NVIDIA ACE](https://developer.nvidia.com/ace) is middleware for conversational/actionable characters rather than one companion. Its 2026 Game Agent SDK announcement highlights the practical obstacles: conversational latency, synchronized global/dynamic state and infinite-loop prevention. It is useful architectural validation, but not directly usable as an add-on to arbitrary closed games without an integration surface.

The strongest deployed evidence is [PUBG Ally](https://developer.nvidia.com/blog/how-krafton-built-pubg-ally-a-co-playable-character-powered-by-nvidia-ace/), KRAFTON's June 2026 two-week beta. It is strikingly similar to m8:

- player voice plus plain-text live game observations feed an event-driven decision loop;
- a quantized on-device 2B Mistral-NeMo-Minitron model handles deliberate coordination/speech;
- a game-tick behavior tree handles movement/combat;
- short-term match context and structured cross-match memory store preferences/history;
- the initial scope is deliberately constrained to Sanhok and AI Duo;
- it runs on GPUs with as little as 8 GB total VRAM and was tuned with feedback from over 1,000 players.

KRAFTON's September 2026 [PUBG Ally paper](https://arxiv.org/abs/2609.29837) reports about 39,000 collected gameplay sessions, about 1.6 seconds per spoken exchange on-device versus 3.4 seconds cloud, and a live-service survey across 141 countries: among respondents with verified play records, positive minus negative willingness-to-recommend was +25.1 percentage points; 18.5% framed Ally as a “teammate” and 31.5% as a “companion.” These are the most useful published numbers found. They support local small models, narrow scope, two-speed control and real user telemetry.

### What users notice and what measurements say

The recurring complaints are not merely anecdotal:

- **Latency.** A 2026 mapping study of 42 papers found reported response times spanning **2.6–15 seconds**, short-term memory in 60%, world grounding in 69%, but long-term memory in only 31% and RAG in 14% ([study summary](https://www.sqrlab.ca/publications/llm-based-npcs-in-video-games-a-systematic-mapping-study/)). A controlled 2026 study with 34 participants found ratings degraded more with slow per-token delivery than with initial delay, and the highest latency reduced most experience categories; moderate delay could feel more human than an instantaneous response ([paper](https://doi.org/10.1016/j.entcom.2026.101213)). Stream audio naturally, but keep token cadence moving.
- **Weak grounding/action reliability.** Conversation feels hollow when the character cannot solve, follow, fight or notice what the player expects. PUBG Ally's behavior-tree/SLM split and m8's advertised-action protocol directly address this.
- **Repetition and shallow memory.** Storing every transcript is not memory. Keep structured relationship facts, promises, shared events and player preferences; summarize episodically; retrieve only relevant memories; permit forgetting and correction.
- **Breaking character.** Provider safety boilerplate, lore hallucination and tone drift break the social contract. Use writer-authored immutable identity, retrieved lore, output checks, and graceful in-character uncertainty.
- **Uncanny or poor voice/animation.** TTS quality, lip sync and turn-taking can negate strong text. Sentence streaming helps latency but must support interruption, emotion/prosody tags and “thinking/listening” animation.
- **Too useful can still be unfun.** A companion should make room for the player, fail legibly and have preferences; it should not vacuum all loot, reveal hidden information or optimize the game out of existence.

### What appears to work

1. **Narrow competence with honest limits.** PUBG constrained map/mode/domain before broadening.
2. **System 1/System 2 split.** Native game AI stays responsive; language handles intent, relationship and explanation.
3. **Event-driven initiative with cooldowns.** The mate comments on meaningful events but does not chatter every tick—already present in m8.
4. **Structured long-term memory.** Names, preferences, promises and shared match history matter more than raw transcript volume.
5. **Authored character plus generative performance.** Ubisoft kept writers responsible for personality/backstory; the model improvises inside that envelope.
6. **Voice inside the game world.** Positional/radio transitions and interruption produce presence that an overlay chatbot cannot.
7. **Real-player testing.** Automated task success does not measure warmth, interruption quality or whether the player wants another session.

### Implications for a general companion runtime

- Optimize for **relationship continuity and timely usefulness**, not benchmark task completion alone.
- Keep personas authored and actions grounded; generation should fill performance, not invent mechanics or canon.
- Measure first-audio latency, interruption success, repeated-line rate, memory precision, action success and post-session “play again” intent.
- A 3090 Ti is ample for the proven on-device pattern if models are deliberately small/quantized; PUBG Ally's 2B/8 GB result is stronger evidence than assuming a 12B+ model is necessary.
- Scope the first release tightly—one mode/world, one body, tens of reliable actions—then expand from telemetry.

---

## Final comparison

| Game / class | Recommended integration route | State fidelity | Action fidelity | Voice-in-game route | Small-team effort | Policy / technical risk |
|---|---|---|---|---|---|---|
| Minecraft Java, private server (MVP) | Mineflayer second client; optional Paper enrichment | High client-plausible state; exact nearby entities/blocks/inventory, limited to loaded chunks | High player-like mechanics; path/edge cases remain | Simple Voice Chat entity channel; mic packets through its server API | **Medium** | Low on owned server; account, version and server-rule constraints |
| Minecraft Java, single-player NPC | Fabric or NeoForge custom entity + Baritone/custom goals | Very high typed integrated-server state | High for mob/world actions; not fully player-equivalent | Simple Voice Chat addon or engine sound instance; OS mic fallback | **High** | Low offline; substantial version-port burden |
| Minecraft Java, vanilla-client server | Paper NPC/mob plugin | Authoritative and very high, requires fairness filtering | Medium–high; entity, not true player | Simple Voice Chat still requires client mod; otherwise finite sounds/text | **Medium** | Low on owned server; vanilla visual/audio limitations |
| Rust, private Modded server | Carbon or Oxide/uMod plugin + scientist/custom NPC | Very high authoritative state; must hide omniscient facts | Medium–high with native brain/local FSM; fragile for player-only mechanics | Input: `OnPlayerVoice`; output: current-build voice-packet spike, else chat/local TTS | **High** | Moderate server-update risk; low EAC risk if entirely server-side; voice output unverified |
| Rust, Rust+ only | External companion API | Low–medium: map/team/chat/devices, not local world/combat | Low: chat/devices, no embodied teammate | No positional NPC voice | **Low** | Low, but cannot meet the core embodiment goal |
| Unity offline game | BepInEx/MelonLoader C# adapter + Harmony/game APIs | High where assemblies/reflection expose it | High, game-specific | Hook game audio or attach Unity `AudioSource` | **High per title** | Moderate injection/update risk; avoid anti-cheat multiplayer |
| Unreal offline game | UE4SS Lua/native adapter | High reflected `UObject`/event state | High where UFunctions/controllers are accessible | Spawn/attach engine audio component | **High per title** | Moderate–high compatibility/injection risk |
| Open-source/decompiled port | Source-level adapter (OpenCE pattern) | Maximum | Maximum | Native positional/radio audio | **Very high once, robust after** | Licence/content review; lowest runtime uncertainty |
| Any visually accessible game | Screen capture + VLM/vision-action + keyboard/mouse | Low–medium; visible state only | Medium for tolerant tasks, low for precise/fast tasks | OS TTS unless a mod injects audio | **Low prototype / very high reliability** | High public-multiplayer cheat risk; long-horizon and precision failures |
| General best case | Hybrid semantic adapter + local skills + vision fallback | High | High | Capability-negotiated native/entity/radio/local | **Medium–high** | Best controlled trade-off; still needs per-game policy/version work |

## Decision in one sentence

Build Minecraft as a **Mineflayer player with a thin Paper/Simple Voice Chat bridge**, and Rust as a **Carbon/uMod-owned scientist NPC on a private Modded server with voice output treated as a gated experiment**; preserve one m8 semantic protocol above both and use vision only where typed integration runs out.
