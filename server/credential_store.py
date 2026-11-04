from __future__ import annotations

from typing import Protocol

import keyring


class CredentialStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...


class SystemCredentialStore:
    def __init__(self, service_name: str = "mingyan-ai-platform") -> None:
        self.service_name = service_name

    def get(self, name: str) -> str | None:
        return keyring.get_password(self.service_name, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.service_name, name, value)
