# steamlayer-core

**Headless, emulator-agnostic Steam game identification and patching.**

steamlayer-core handles the full pipeline from a game directory to a patched installation — resolving AppIDs, hydrating DLC metadata, backing up original binaries, and writing emulator configuration — without caring which emulator you use or how your UI works.

---

## Installation

```bash
pip install steamlayer-core
```

Requires Python 3.12+.

---

## Quickstart

### One-shot (simple scripts)

```python
from pathlib import Path
from steamlayer_core import resolve_game, patch_game
from steamlayer_core import GoldbergLocalVendorProvider, GoldbergConfigWriter

game = resolve_game(Path("./games/Cyberpunk 2077"))
print(f"{game.game_name} — AppID {game.appid}, {len(game.dlcs)} DLCs")

result = patch_game(
    game,
    Path("./games/Cyberpunk 2077"),
    vendor=GoldbergLocalVendorProvider(Path("./vendors")),
    config_writer=GoldbergConfigWriter(),
)
print(f"Patched. Vault at: {result.vault_path}")
```

### Stateful client (CLIs, GUIs, services)

```python
from pathlib import Path
from steamlayer_core import SteamLayerClient, GoldbergLocalVendorProvider, GoldbergConfigWriter

with SteamLayerClient(
    vendor=GoldbergLocalVendorProvider(Path("./vendors")),
    config_writer=GoldbergConfigWriter(),
) as client:
    game = client.resolve(Path("./games/Cyberpunk 2077"))
    result = client.patch(game, Path("./games/Cyberpunk 2077"))
```

The `SteamLayerClient` manages the HTTP session lifecycle and reuses the resolution engine across calls — prefer it for anything beyond a single operation.

---

## How it works

steamlayer-core is built around three injected strategies:

| Component | Responsibility | Default |
|---|---|---|
| `VendorProvider` | Supplies emulator DLLs and auxiliary tools | — |
| `ConfigWriter` | Writes emulator configuration files | — |
| Handlers | Resolve disambiguation and low-confidence matches | Raises exceptions |

The engine never hardcodes which emulator is used, where its binaries live, or what format its config files take. Swap any strategy without touching the core.

### Resolution waterfall

AppID discovery runs in order, stopping at the first confident result:

1. **Manual override** — `SteamlayerOptions(appid=...)` skips all discovery
2. **Local file scan** — reads `steam_appid.txt` or `.acf` manifests from the game directory
3. **Community index** — fuzzy match against a locally cached title index
4. **Steam Store search** — live web query as a last resort

### Vault system

Before any file is modified, originals are backed up to a `__steamlayer_vault__` directory with a JSON manifest. `client.unpatch()` restores everything exactly, even if files were renamed after patching.

---

## Bringing your own emulator

`GoldbergLocalVendorProvider` and `GoldbergConfigWriter` are the built-in implementations for [gbe_fork](https://github.com/Detanup01/gbe_fork). To support any other emulator, implement the two protocols:

```python
from pathlib import Path
from steamlayer_core.protocols import VendorProvider, ConfigWriter
from steamlayer_core.domain.models import DLCInfo
from steamlayer_core import SteamLayerClient

class MyVendor:
    def get_emulator_dll(self, architecture: str) -> Path: ...
    def get_steamless_exe(self) -> Path | None: ...

class MyConfigWriter:
    def write(self, dll_dir: Path, appid: int, dlcs: dict[int, DLCInfo]) -> None: ...

with SteamLayerClient(vendor=MyVendor(), config_writer=MyConfigWriter()) as client:
    result = client.patch(game, game_path)
```

> **Note:** steamlayer-core does not download or bundle third-party binaries.
> You are responsible for obtaining them. A custom `VendorProvider` that
> handles automatic binary acquisition is a natural extension point.

---

## Acquiring binaries

For the built-in Goldberg support:

- **Goldberg (gbe_fork):** <https://github.com/Detanup01/gbe_fork/releases>
- **Steamless:** <https://github.com/atom0s/Steamless/releases> *(optional — skipped silently if absent)*

Expected layout for `GoldbergLocalVendorProvider`:
vendors/
goldberg/
regular/
x64/
steam_api64.dll
x86/
steam_api.dll
steamless/
Steamless.CLI.exe

---

## Error handling

All exceptions inherit from `SteamLayerError`:
```text
SteamLayerError
├── AppIDResolutionError
│   ├── AppIDNotFoundError
│   ├── AmbiguousMatchError
│   └── LowConfidenceError
├── DLCHydrationError
│   └── DLCCacheError
└── PatchError
├── VaultError
└── EmulatorBinaryError
```

---
