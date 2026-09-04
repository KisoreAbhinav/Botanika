# Configuration boundary

Versioned, non-secret runtime defaults and model contracts will live here.
API keys and machine-local overrides must stay outside Git.

Phase 7 keeps its OS-level AP inputs in
[`environments/phase7-native-packages.txt`](environments/phase7-native-packages.txt)
and its non-secret runtime example in
[`environments/phase7-network.env.example`](environments/phase7-network.env.example).
The WPA passphrase is machine-local and is never committed.

The AP is optional. For a phone on any internet-connected network, enable the
free no-account Cloudflare Quick Tunnel independently with
`BOTANIKA_NETWORK_ENABLED=false`, loopback host/binding, and
`BOTANIKA_TUNNEL_ENABLED=true`. Set `BOTANIKA_CLOUDFLARED_PATH` to the local
`cloudflared` executable and leave the startup timeout at a bounded value.
Quick Tunnels are development/testing only: random per-process URL, no SLA,
200 in-flight requests, and no SSE. Botanika's remote paired flow uses polling
and uploads, so the limitation is explicit.

The same environment example contains optional Phase 8 GPIO assignments and
pairing lease settings. Leave the pin values blank when running without
physical hardware; the software mode toggle remains available.

Phase 9 adds optional local asset paths for a manually installed GGUF/llama.cpp
model and explicit `BOTANIKA_LLAMA_CLI_PATH`, Vosk STT models, Piper voices, and
the independent weed-beta manifest. The Pi release and checksum contracts are
tracked in `llm/phase9-llama.example.json`, `weed/phase9-beta.json`, and the
model review in `../docs/MODEL_ASSET_REVIEW_2026-09-04.md`.
No asset is downloaded by the application. Source/license provenance lives in
[`knowledge/source-license-manifest.json`](knowledge/source-license-manifest.json);
the release tools rebuild and checksum the SQLite FTS5/embedding index.
