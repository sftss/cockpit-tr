"""Where the API key lives: the credential manager of the operating system.

The key is never written to the database, to a file of the application or to
the repository, and no endpoint returns it.
"""

from __future__ import annotations

import os
from typing import Protocol

SERVICE = "cockpit-tr"
ACCOUNT = "anthropic-api-key"
ENV_VAR = "ANTHROPIC_API_KEY"


class KeyStore(Protocol):
    def get(self) -> str | None: ...
    def set(self, key: str) -> None: ...
    def delete(self) -> None: ...


class KeyStoreError(RuntimeError):
    """The credential manager is not usable on this machine."""


class SystemKeyStore:
    """Windows Credential Manager (or the equivalent elsewhere), through keyring."""

    def get(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(SERVICE, ACCOUNT) or None
        except Exception:  # no usable backend: behave as if nothing was stored
            return None

    def set(self, key: str) -> None:
        try:
            import keyring

            keyring.set_password(SERVICE, ACCOUNT, key)
        except Exception as exc:
            raise KeyStoreError(
                "Le gestionnaire d'identifiants du système n'est pas disponible."
            ) from exc

    def delete(self) -> None:
        try:
            import keyring

            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:  # nothing stored, or no backend: nothing to remove
            return


def check_format(key: str) -> str:
    key = key.strip()
    if not key.startswith("sk-ant-") or len(key) < 20 or any(c.isspace() for c in key):
        raise ValueError("Cette valeur ne ressemble pas à une clé d'API Anthropic (sk-ant-…).")
    return key


def resolve(store: KeyStore) -> tuple[str | None, str | None]:
    """The key and where it comes from ('coffre' or 'environnement')."""
    stored = store.get()
    if stored:
        return stored, "coffre"
    env = os.environ.get(ENV_VAR, "").strip()
    return (env, "environnement") if env else (None, None)
