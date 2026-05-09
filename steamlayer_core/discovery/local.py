from __future__ import annotations

import logging
import pathlib
import re

log = logging.getLogger("steamlayer.discovery.local")


class LocalDiscovery:
    def find(self, path: pathlib.Path) -> int | None:
        wanted_file = "steam_appid.txt"
        seen: set[str] = set()

        for f in path.rglob(wanted_file):
            key = str(f).lower()
            if key in seen:
                continue
            seen.add(key)

            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r"\d+", content)

                if match:
                    appid = int(match.group())
                    log.info(f"Found AppID {appid} in '{f}'")
                    return appid

            except OSError as e:
                log.warning(f"Failed to read '{f}': {e}")
                continue

        parent = path.parent
        if parent.name.lower() == "common":
            library_root = parent.parent
            manifests = list(library_root.glob("appmanifest_*.acf"))

            for manifest in manifests:
                try:
                    content = manifest.read_text(errors="ignore")
                    if path.name.lower() in content.lower():
                        match = re.search(r'"appid"\s+"(\d+)"', content)
                        if match:
                            appid = int(match.group(1))
                            log.info(f"Found AppID {appid} in '{manifest.name}'")
                            return appid
                except Exception:
                    continue

        return None
