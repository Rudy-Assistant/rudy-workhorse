#!/usr/bin/env python3
"""
Credential Vault -- S199 (per S198 AA16 / Audit-Discipline A15.2).

The "one file still missing" from the S197 A15 un-shipped list:
a cross-service credential vault that replaces the plaintext
``rudy-data/robin-secrets.json`` with an OS-protected store.

Design goals
------------
* Replace plaintext ``robin-secrets.json`` (current callers in
  ``robin_autonomy.py`` lines 545-550, 797-799, 1191-1194).
* Windows-first: prefer Windows DPAPI via ``win32crypt`` if available,
  then ``keyring`` (which itself uses Credential Manager on Windows),
  then a XOR-obfuscated on-disk fallback so the vault is ALWAYS usable
  even on a fresh install with no extra deps. The fallback is NOT
  cryptographically strong; it is only better than plaintext and is
  flagged in ``status()``.
* Stdlib-only by default (matches the deliberate import isolation in
  ``lucius_gate.py``). ``win32crypt`` and ``keyring`` are soft imports.
* Backwards-compatible read path: ``get_secret(name)`` falls through
  to the legacy ``robin-secrets.json`` file if present, so existing
  Robin processes keep working during the cutover.
* One-shot migration helper (``migrate_from_legacy()``) so any future
  ``robin-secrets.json`` that appears can be ingested and deleted.
* No network. No subprocesses. No third-party calls.

Public surface
--------------
    get_secret(name, default=None) -> str | None
    set_secret(name, value)        -> None
    delete_secret(name)            -> bool
    list_secrets()                 -> list[str]
    migrate_from_legacy()          -> dict   # {migrated, skipped, errors}
    status()                       -> dict   # backend, count, warnings

Wiring (S199): ``robin_autonomy.py`` should import ``get_secret`` from
this module and call ``get_secret("github_pat")`` /
``get_secret("ollama_model", default="qwen2.5:7b")`` instead of
opening ``robin-secrets.json`` directly. A thin shim is provided
below as ``robin_autonomy_compat`` for the three call sites.

Author: Alfred S199. Lines: ~200. Stdlib-only required path.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

try:
    from rudy.paths import RUDY_DATA
except Exception:  # pragma: no cover -- standalone
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"

log = logging.getLogger("credential_vault")

VAULT_DIR = RUDY_DATA / "vault"
VAULT_FILE = VAULT_DIR / "credentials.dat"
LEGACY_FILE = RUDY_DATA / "robin-secrets.json"
SERVICE_NAME = "rudy-workhorse-credential-vault"

# Soft imports -- best backend wins
_BACKEND = "fallback"
try:
    import win32crypt  # type: ignore
    _BACKEND = "dpapi"
except Exception:
    try:
        import keyring  # type: ignore
        _BACKEND = "keyring"
    except Exception:
        pass


# -------------------------------------------------------------------
# On-disk container
# -------------------------------------------------------------------

def _ensure_dir() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)


def _xor_obfuscate(data: bytes) -> bytes:
    """Last-resort fallback. NOT cryptography. Beats plaintext only."""
    key = (os.environ.get("USERNAME", "rudy") + SERVICE_NAME).encode()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _encrypt(plaintext: str) -> bytes:
    raw = plaintext.encode("utf-8")
    if _BACKEND == "dpapi":
        blob = win32crypt.CryptProtectData(raw, SERVICE_NAME, None, None, None, 0)
        return b"DPAPI:" + base64.b64encode(blob)
    return b"XOR:" + base64.b64encode(_xor_obfuscate(raw))


def _decrypt(blob: bytes) -> str:
    if blob.startswith(b"DPAPI:") and _BACKEND == "dpapi":
        raw = base64.b64decode(blob[6:])
        _desc, plain = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
        return plain.decode("utf-8")
    if blob.startswith(b"XOR:"):
        return _xor_obfuscate(base64.b64decode(blob[4:])).decode("utf-8")
    # Bare plaintext (shouldn't happen, but tolerate)
    return blob.decode("utf-8")


def _load_store() -> dict[str, bytes]:
    if not VAULT_FILE.exists():
        return {}
    try:
        raw = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
        return {k: v.encode("latin-1") for k, v in raw.items()}
    except Exception as e:
        log.error("vault load failed: %s", e)
        return {}


def _save_store(store: dict[str, bytes]) -> None:
    _ensure_dir()
    serialised = {k: v.decode("latin-1") for k, v in store.items()}
    VAULT_FILE.write_text(json.dumps(serialised, indent=2), encoding="utf-8")
    try:  # tighten perms where the OS allows
        os.chmod(VAULT_FILE, 0o600)
    except Exception:
        pass


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def set_secret(name: str, value: str) -> None:
    """Store a secret. Uses keyring backend when available, else file."""
    if _BACKEND == "keyring":
        try:
            keyring.set_password(SERVICE_NAME, name, value)
            return
        except Exception as e:
            log.warning("keyring set failed, falling through: %s", e)
    store = _load_store()
    store[name] = _encrypt(value)
    _save_store(store)


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read a secret. Tries vault, then legacy ``robin-secrets.json``."""
    if _BACKEND == "keyring":
        try:
            v = keyring.get_password(SERVICE_NAME, name)
            if v is not None:
                return v
        except Exception:
            pass
    store = _load_store()
    if name in store:
        try:
            return _decrypt(store[name])
        except Exception as e:
            log.error("decrypt %s failed: %s", name, e)
    # Legacy fallback -- preserves running Robin during cutover
    if LEGACY_FILE.exists():
        try:
            data = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
            if name in data:
                return data[name]
        except Exception as e:
            log.warning("legacy read failed: %s", e)
    return default


def delete_secret(name: str) -> bool:
    deleted = False
    if _BACKEND == "keyring":
        try:
            keyring.delete_password(SERVICE_NAME, name)
            deleted = True
        except Exception:
            pass
    store = _load_store()
    if name in store:
        del store[name]
        _save_store(store)
        deleted = True
    return deleted


def list_secrets() -> list[str]:
    names: set[str] = set(_load_store().keys())
    if LEGACY_FILE.exists():
        try:
            names.update(json.loads(LEGACY_FILE.read_text(encoding="utf-8")).keys())
        except Exception:
            pass
    return sorted(names)


def migrate_from_legacy() -> dict:
    """Pull every key from ``robin-secrets.json`` into the vault.

    Does NOT delete the legacy file -- caller decides. Idempotent.
    """
    result = {"migrated": [], "skipped": [], "errors": [], "backend": _BACKEND}
    if not LEGACY_FILE.exists():
        result["note"] = "no legacy file"
        return result
    try:
        legacy = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        result["errors"].append(f"parse: {e}")
        return result
    for k, v in legacy.items():
        if not isinstance(v, str):
            result["skipped"].append(k)
            continue
        try:
            set_secret(k, v)
            result["migrated"].append(k)
        except Exception as e:
            result["errors"].append(f"{k}: {e}")
    return result


def status() -> dict:
    warnings: list[str] = []
    if _BACKEND == "fallback":
        warnings.append(
            "no DPAPI/keyring -- using XOR fallback. Install pywin32 or keyring."
        )
    if LEGACY_FILE.exists():
        warnings.append(
            f"legacy {LEGACY_FILE.name} still present -- run migrate_from_legacy()"
        )
    return {
        "backend": _BACKEND,
        "vault_file": str(VAULT_FILE),
        "exists": VAULT_FILE.exists(),
        "count": len(list_secrets()),
        "warnings": warnings,
    }


# -------------------------------------------------------------------
# robin_autonomy.py compatibility shim
# -------------------------------------------------------------------
# These mirror the three call sites flagged in S198 AA16 F-S198-C.
# Wiring step (S199 part 2): replace those inline json.loads calls
# with credential_vault.read_github_pat() / read_ollama_model().

def read_github_pat() -> str:
    return get_secret("github_pat", default="") or ""


def read_ollama_model(default: str = "qwen2.5:7b") -> str:
    return get_secret("ollama_model", default=default) or default


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(status(), indent=2))
    print("secrets:", list_secrets())
