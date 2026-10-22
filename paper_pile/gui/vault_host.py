"""The vault this app process has open, and switching to another one ("Open vault").

One process serves one vault at a time. Every page reads ``host.vault`` when it is built, so a
switch only has to point the host (and its file watcher) at the new folder and reload the open
pages; their old editors save their notes when they disconnect.
"""

import asyncio
import logging
from pathlib import Path

from nicegui import Client, app, ui

from paper_pile.core.events import EventBus
from paper_pile.core.session import save_last_vault
from paper_pile.core.vault import Vault, ensure_vault_dir, resolve_vault_path
from paper_pile.core.watcher import VaultWatcher

log = logging.getLogger("paper_pile.vault_host")


def window_title(vault: Path) -> str:
    return f"paper-pile — {vault.name}"


class VaultHost:
    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.fs_bus = EventBus()  # one watcher per process; every open page subscribes to this bus
        self._watcher: VaultWatcher | None = None

    def current(self) -> Vault:
        return Vault(self.vault)

    def start_watcher(self) -> None:
        """Watch the open vault for changes made outside the app (call on the event loop)."""
        loop = asyncio.get_running_loop()
        # watchdog calls us from its own thread; hop onto the event loop before touching the UI
        self._watcher = VaultWatcher(
            self.vault, self.fs_bus, dispatch=lambda fn: loop.call_soon_threadsafe(fn)
        )
        self._watcher.start()

    def stop_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def switch(self, folder: Path) -> Path:
        """Open ``folder`` as the vault: every open page reloads onto it. Raises ``VaultError``
        if it is not an existing folder. The caller saves the open notes first."""
        vault = resolve_vault_path(folder)
        ensure_vault_dir(vault)
        save_last_vault(vault)
        if vault == self.vault:
            return vault
        log.info("switching vault: %s -> %s", self.vault, vault)
        self.stop_watcher()
        self.vault = vault
        self.start_watcher()
        window = app.native.main_window
        if window is not None:
            window.set_title(window_title(vault))
        for client in list(Client.instances.values()):
            if client.has_socket_connection:
                with client:
                    ui.navigate.reload()
        return vault
