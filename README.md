<div align="center">

# steamlayer-core

[![PyPI](https://img.shields.io/pypi/v/steamlayer-core)](https://pypi.org/project/steamlayer-core/)
[![Python](https://img.shields.io/pypi/pyversions/steamlayer-core)](https://pypi.org/project/steamlayer-core/)
[![CI](https://img.shields.io/github/actions/workflow/status/layeredtools/steamlayer-core/ci.yml?branch=main&label=ci)](https://github.com/layeredtools/steamlayer-core/actions)
[![License](https://img.shields.io/github/license/layeredtools/steamlayer-core)](LICENSE)

The emulator-agnostic engine behind SteamLayer. Handles Steam game identification,
DRM patching, and DLC hydration — with no opinion about which emulator you use.
</div>

## Overview

`steamlayer-core` is a Python library that provides a clean pipeline for:

1. **Resolving** a game directory to its Steam AppID (local files → app index → store search → disambiguation)
2. **Patching** the game by swapping Steam API DLLs with emulator binaries and writing config
3. **Unpatching** to restore the original files from a local backup vault
4. **Fetching DLC metadata** for a given AppID, with disk caching

The library is designed to be embedded inside higher-level tools. It has no `print()` or
`input()` calls anywhere — all user interaction is delegated to injected callbacks.

---

## Installation

```bash
pip install steamlayer-core
```

Python 3.13+ is required.

---

## Quick start

### One-shot functions

The simplest way to use the library. Each call opens its own HTTP session and closes it
when done.

```python
from pathlib import Path
from steamlayer_core.api import resolve_game, patch_game

# 1. Identify the game — resolve_game checks the directory for a steam_appid.txt
#    or an appmanifest_*.acf file first. If found, no network call is made.
game = resolve_game(Path("C:/games/Euro Truck Simulator 2"))
print(game.appid, game.game_name)  # 227300, Euro Truck Simulator 2

# 2. Patch it (requires a VendorProvider and ConfigWriter from your emulator layer)
result = patch_game(game, Path("C:/games/Euro Truck Simulator 2"), vendor=vendor, config_writer=writer)
print(result.patched_files)
```

If no local marker is found, the engine falls back to the app index and then a live
store search. You can also skip the path entirely and trigger a web search directly by
passing the game name as a string:

```python
# No path — goes straight to index/store search
game = resolve_game("Euro Truck Simulator 2")
```

### Stateful client

Use `SteamLayerClient` when you need to reuse a single HTTP session across multiple
operations, wire progress callbacks once, or manage the lifecycle explicitly.

```python
from pathlib import Path
from steamlayer_core import SteamLayerClient

with SteamLayerClient(vendor=vendor, config_writer=writer, progress=my_progress_hook) as client:
    game = client.resolve(Path("C:/games/Euro Truck Simulator 2"))
    dlcs = client.fetch_dlcs(game.appid)
    result = client.patch(game, Path("C:/games/Euro Truck Simulator 2"))
```

### Reverting a patch

```python
from steamlayer_core.api import SteamLayerClient

with SteamLayerClient() as client:
    if client.is_patched(game_path):
        restored = client.unpatch(game_path)
        print(f"Restored {len(restored)} file(s)")
```


## Core concepts

### Resolution waterfall

When you call `resolve()` or `resolve_game()`, the engine tries each strategy in order,
stopping as soon as a confident match is found:

```
Game directory
      │
      ▼
Local file inspection    (steam_appid.txt, appmanifest_*.acf, ...)
      │ no match
      ▼
App index lookup         (offline index bundled with the library)
      │ no match / low confidence
      ▼
Steam store search       (live web query, skipped if allow_network=False)
      │ ambiguous
      ▼
Disambiguation callback  (your on_disambiguation handler, or AmbiguousMatchError)
```

### Emulator agnosticism

`steamlayer-core` never references a specific emulator. It interacts with two
protocols that you implement (or get from an emulator-specific package):

| Protocol | Responsibility |
|---|---|
| `VendorProvider` | Supplies the emulator DLL binaries to be written into the game directory |
| `ConfigWriter` | Defines what config files to write and where (AppID, DLC list, etc.) |

This means the same core library can drive Goldberg, or any future emulator, just by
swapping the injected implementations.

### Backup vault

Before any file is overwritten, `patch()` creates a local vault inside the game
directory. `unpatch()` reads exclusively from this vault — it does not need to know
which emulator was used. `purge_vault=True` (default) deletes the vault after a
successful restore.

### DLC caching

`fetch_dlcs()` caches results to `~/.steamlayer/.cache/dlcs_{appid}.json`. Subsequent
calls within the TTL window never touch the network. The cache path and TTL are
configurable via `SteamlayerOptions`.


## Design principles

- **No I/O side-effects.** No `print()`, no `input()`, no logging to stdout. Progress
  and interaction are surfaced through injected callbacks.
- **Protocol-based injection.** `VendorProvider`, `ConfigWriter`, `HTTPClientProtocol`,
  and the handler callbacks are all protocols. Mock any of them in tests without
  subclassing.
  implementation detail and may change between minor versions.

---

## Contributing

Issues and pull requests are welcome. Please open an issue before starting significant
work so we can discuss the approach.

```bash
git clone https://github.com/your-org/steamlayer-core
cd steamlayer-core
pip install -e ".[dev]"
```

---

## License

[MIT](LICENSE)