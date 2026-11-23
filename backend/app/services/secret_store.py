"""Current-user Windows DPAPI storage for provider API keys."""

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _data_path() -> Path:
    home = Path(os.environ.get("MELOFORGE_HOME", Path(__file__).resolve().parents[2] / "data"))
    return home / "secrets.dpapi.json"


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Encrypted local key storage is available only on Windows.")
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    protect.restype = wintypes.BOOL
    if not protect(ctypes.byref(source), "MeloForge Studio provider key", None, None, None, 0x1, ctypes.byref(target)):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI could not encrypt the key.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(target.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Encrypted local key storage is available only on Windows.")
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    description = wintypes.LPWSTR()
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    unprotect.restype = wintypes.BOOL
    if not unprotect(ctypes.byref(source), ctypes.byref(description), None, None, None, 0x1, ctypes.byref(target)):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI could not decrypt the key for this user.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(target.pbData)
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))


def _read_all() -> dict[str, str]:
    try:
        value = json.loads(_data_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def store_secret(name: str, value: str) -> None:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 5000:
        raise ValueError("Credential length is invalid.")
    stored = _read_all()
    stored[name] = base64.b64encode(_protect(encoded)).decode("ascii")
    path = _data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_secret(name: str) -> str | None:
    value = _read_all().get(name)
    if not isinstance(value, str):
        return None
    return _unprotect(base64.b64decode(value, validate=True)).decode("utf-8")


def delete_secret(name: str) -> None:
    stored = _read_all()
    stored.pop(name, None)
    path = _data_path()
    if stored:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        temporary.replace(path)
    else:
        path.unlink(missing_ok=True)
