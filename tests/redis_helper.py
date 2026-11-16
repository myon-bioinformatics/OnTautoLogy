"""Minimal stdlib-only Redis RESP2 test helper + in-memory fallback for tests.

Tests remain runnable under ``python3 -S -m unittest`` without external packages.
When ``REDIS_URL`` (e.g. ``redis://127.0.0.1:6379/15``) is set, ``open_test_redis()``
connects to that Redis server over TCP; otherwise it falls back to ``FakeRedis``.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import unquote, urlparse


class RedisError(RuntimeError):
    """Raised when Redis returns an error reply or malformed RESP frame."""


class _SocketReader:
    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buf = bytearray()

    def readline(self) -> bytes:
        while True:
            idx = self._buf.find(b"\r\n")
            if idx != -1:
                line = bytes(self._buf[:idx])
                del self._buf[: idx + 2]
                return line
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("unexpected EOF from Redis server")
            self._buf.extend(chunk)

    def read_exact(self, size: int) -> bytes:
        while len(self._buf) < size:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("unexpected EOF from Redis server")
            self._buf.extend(chunk)
        data = bytes(self._buf[:size])
        del self._buf[:size]
        return data


def _encode_command(*args: object) -> bytes:
    parts = [f"*{len(args)}\r\n".encode("ascii")]
    for arg in args:
        raw = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
        parts.append(f"${len(raw)}\r\n".encode("ascii"))
        parts.append(raw)
        parts.append(b"\r\n")
    return b"".join(parts)


def _read_reply(reader: _SocketReader):
    line = reader.readline()
    if not line:
        raise RedisError("empty RESP line")
    prefix, body = chr(line[0]), line[1:]
    if prefix == "+":
        return body.decode("utf-8")
    if prefix == "-":
        raise RedisError(body.decode("utf-8"))
    if prefix == ":":
        return int(body)
    if prefix == "$":
        length = int(body)
        if length == -1:
            return None
        payload = reader.read_exact(length)
        crlf = reader.read_exact(2)
        if crlf != b"\r\n":
            raise RedisError("missing CRLF after bulk string")
        return payload.decode("utf-8")
    if prefix == "*":
        count = int(body)
        if count == -1:
            return None
        return [_read_reply(reader) for _ in range(count)]
    raise RedisError(f"unsupported RESP prefix: {prefix!r}")


class RedisTestClient:
    """Tiny stdlib RESP2 TCP client implementing the subset needed by tests."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0,
                 password: str | None = None, username: str | None = None, timeout: float = 3.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._reader = _SocketReader(self._sock)
        if password is not None:
            if username:
                self.command("AUTH", username, password)
            else:
                self.command("AUTH", password)
        if db:
            self.command("SELECT", db)

    @classmethod
    def from_url(cls, url: str, *, timeout: float = 3.0) -> "RedisTestClient":
        parsed = urlparse(url)
        if parsed.scheme not in ("redis", ""):
            raise ValueError(f"unsupported REDIS_URL scheme: {parsed.scheme!r}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 6379
        db = int(parsed.path.lstrip("/") or "0")
        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None
        return cls(host=host, port=port, db=db, password=password, username=username, timeout=timeout)

    def command(self, *args: object):
        self._sock.sendall(_encode_command(*args))
        return _read_reply(self._reader)

    def ping(self) -> bool:
        return self.command("PING") == "PONG"

    def flushdb(self) -> None:
        self.command("FLUSHDB")

    def sadd(self, key: str, *members: str) -> int:
        if not members:
            return 0
        return int(self.command("SADD", key, *members))

    def smembers(self, key: str) -> set[str]:
        return set(self.command("SMEMBERS", key) or ())

    def sinter(self, *keys: str) -> set[str]:
        return set(self.command("SINTER", *keys) or ())

    def sdiff(self, key: str, *others: str) -> set[str]:
        return set(self.command("SDIFF", key, *others) or ())

    def set(self, key: str, value: str) -> None:
        self.command("SET", key, value)

    def get(self, key: str) -> str | None:
        return self.command("GET", key)

    def hset(self, key: str, field: str, value: str) -> int:
        return int(self.command("HSET", key, field, value))

    def hgetall(self, key: str) -> dict[str, str]:
        flat = self.command("HGETALL", key) or []
        return {flat[i]: flat[i + 1] for i in range(0, len(flat), 2)}

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> "RedisTestClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class FakeRedis:
    """In-memory Redis-compatible test store used when REDIS_URL is unset."""

    def __init__(self):
        self._sets: dict[str, set[str]] = {}
        self._strings: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    def ping(self) -> bool:
        return True

    def flushdb(self) -> None:
        self._sets.clear()
        self._strings.clear()
        self._hashes.clear()

    def sadd(self, key: str, *members: str) -> int:
        target = self._sets.setdefault(key, set())
        before = len(target)
        target.update(str(m) for m in members)
        return len(target) - before

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    def sinter(self, *keys: str) -> set[str]:
        if not keys:
            return set()
        sets = [self._sets.get(k, set()) for k in keys]
        return set.intersection(*sets)

    def sdiff(self, key: str, *others: str) -> set[str]:
        result = set(self._sets.get(key, set()))
        for other in others:
            result -= self._sets.get(other, set())
        return result

    def set(self, key: str, value: str) -> None:
        self._strings[key] = str(value)

    def get(self, key: str) -> str | None:
        return self._strings.get(key)

    def hset(self, key: str, field: str, value: str) -> int:
        table = self._hashes.setdefault(key, {})
        is_new = field not in table
        table[field] = str(value)
        return 1 if is_new else 0

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeRedis":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def open_test_redis(env_var: str = "REDIS_URL"):
    """Return ``(client, is_live_redis)`` using REDIS_URL if set, else FakeRedis."""
    url = os.environ.get(env_var, "").strip()
    if url:
        return RedisTestClient.from_url(url), True
    return FakeRedis(), False
