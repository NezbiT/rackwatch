"""Docker Engine adapter.

Uses the official Docker SDK against DOCKER_HOST (the socket is
mounted read-write in Compose so we can restart). All SDK calls are
blocking, so they run in a thread via `asyncio.to_thread`.

Restart is denylisted for core stack names (see AUTO_RESTART_DENYLIST)
even when an operator clicks "Restart" — those names require an
explicit override query param used only from the Services page
confirm dialog (`force=1`).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import posixpath
import shlex
import sys
import tarfile
import time
from typing import Any

from app.config import Settings
from app.schemas import ContainerMetrics
from app.services.status import container_severity

log = logging.getLogger("rackwatch.docker")

MAX_FILE_READ_BYTES = 1024 * 1024  # 1 MB
MAX_FILE_WRITE_BYTES = 1024 * 1024  # 1 MB
MAX_EXEC_OUTPUT_CHARS = 65536  # 64 KB
EXEC_TIMEOUT_SECONDS = 15.0

SENSITIVE_PATH_PREFIXES = ("/proc", "/sys", "/dev")
SENSITIVE_FILES = ("/etc/shadow", "/etc/gshadow", "/etc/sudoers")


class DockerControl:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._fail_until = 0.0

    def _base_url(self) -> str:
        host = self.settings.docker_host
        # Compose sets unix://… which does not exist on Windows. Docker Desktop
        # exposes a named pipe instead.
        if sys.platform == "win32" and host.startswith("unix://"):
            return "npipe:////./pipe/docker_engine"
        return host

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        now = time.time()
        if now < self._fail_until:
            return None
        try:
            import docker

            # 2s timeout so a missing socket cannot stall the 3s collector tick.
            self._client = docker.DockerClient(base_url=self._base_url(), timeout=2)
            self._client.ping()
            return self._client
        except Exception as exc:
            log.warning("docker unavailable: %s", exc)
            self._client = None
            self._fail_until = now + 15
            return None

    async def ready(self) -> bool:
        client = await asyncio.to_thread(self._connect)
        return client is not None

    async def list_containers(self, usage: dict[str, dict[str, float]] | None = None) -> list[ContainerMetrics]:
        return await asyncio.to_thread(self._list_sync, usage or {})

    def _list_sync(self, usage: dict[str, dict[str, float]]) -> list[ContainerMetrics]:
        client = self._connect()
        if client is None:
            return []
        out: list[ContainerMetrics] = []
        try:
            for c in client.containers.list(all=True):
                labels = c.labels or {}
                name = (c.name or "").lstrip("/")
                health = ""
                state = c.attrs.get("State") or {}
                if "Health" in state:
                    health = (state["Health"] or {}).get("Status") or ""
                started = state.get("StartedAt") or ""
                stats = usage.get(name, {})
                item = ContainerMetrics(
                    id=c.short_id,
                    name=name,
                    image=_image_name(c),
                    status=(c.status or "").lower(),
                    health=health,
                    cpu_percent=stats.get("cpu"),
                    memory_percent=stats.get("memory_percent"),
                    memory_bytes=int(stats["memory_bytes"]) if "memory_bytes" in stats else None,
                    restart_count=int(state.get("RestartCount") or 0),
                    started_at=started,
                    compose_project=labels.get("com.docker.compose.project", ""),
                    host=self.settings.instance_name,
                )
                item.severity = container_severity(item.status, item.health)
                out.append(item)
        except Exception as exc:
            log.warning("docker list failed: %s", exc)
            self._client = None
        return sorted(out, key=lambda x: (x.severity != "error", x.name))

    async def logs(self, name_or_id: str, lines: int = 80) -> tuple[bool, str]:
        return await asyncio.to_thread(self._logs_sync, name_or_id, lines)

    def _logs_sync(self, name_or_id: str, lines: int) -> tuple[bool, str]:
        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            raw = container.logs(tail=max(1, min(lines, 500)), timestamps=True)
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            return True, text[-32000:]
        except Exception as exc:
            return False, str(exc)

    async def restart(self, name_or_id: str, *, force: bool = False) -> tuple[bool, str]:
        return await asyncio.to_thread(self._action_sync, name_or_id, force, "restart")

    async def start(self, name_or_id: str, *, force: bool = False) -> tuple[bool, str]:
        return await asyncio.to_thread(self._action_sync, name_or_id, force, "start")

    async def stop(self, name_or_id: str, *, force: bool = False) -> tuple[bool, str]:
        return await asyncio.to_thread(self._action_sync, name_or_id, force, "stop")

    async def exec(self, name_or_id: str, command: str, *, force: bool = False) -> tuple[bool, dict[str, Any] | str]:
        if not force and self.is_denied(name_or_id):
            return False, f"{name_or_id} is on the denylist (override requires force=True)"
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._exec_sync, name_or_id, command),
                timeout=EXEC_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return False, f"command execution timed out after {int(EXEC_TIMEOUT_SECONDS)}s"

    async def get_file(self, name_or_id: str, path: str, *, force: bool = False) -> tuple[bool, str]:
        if not force and self.is_denied(name_or_id):
            return False, f"{name_or_id} is on the denylist (override requires force=True)"
        return await asyncio.to_thread(self._get_file_sync, name_or_id, path)

    async def put_file(self, name_or_id: str, path: str, content: str, *, force: bool = False) -> tuple[bool, str]:
        if "rackwatch" in name_or_id.lower():
            return False, "file modification of rackwatch container is prohibited"
        if not force and self.is_denied(name_or_id):
            return False, f"{name_or_id} is on the denylist (override requires force=True)"
        return await asyncio.to_thread(self._put_file_sync, name_or_id, path, content)

    async def inspect(self, name_or_id: str) -> tuple[bool, dict[str, Any] | str]:
        return await asyncio.to_thread(self._inspect_sync, name_or_id)

    def _exec_sync(self, name_or_id: str, command: str) -> tuple[bool, dict[str, Any] | str]:
        cmd_clean = command.strip()
        if not cmd_clean or len(cmd_clean) > 500:
            return False, "command must be between 1 and 500 characters"
        try:
            argv = shlex.split(cmd_clean, posix=True)
        except ValueError as exc:
            return False, f"invalid command syntax: {exc}"
        if not argv or any(token in cmd_clean for token in (";", "&&", "||", "|", ">", "<", "`", "$", "\\")):
            return False, "shell operators are not allowed"
        executable = os.path.basename(argv[0]).lower()
        if executable in {"sh", "bash", "ash", "zsh", "dash", "cmd", "powershell", "pwsh"}:
            return False, "shell interpreters are not allowed"
        if executable not in self.settings.exec_allowlist:
            return False, f"command '{executable}' is not on the exec allow-list"
        if any(arg in {"-c", "--command", "--exec"} for arg in argv[1:]):
            return False, "command interpreters are not allowed"
        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            result = container.exec_run(argv, stdout=True, stderr=True, demux=False)
            output = result.output
            if isinstance(output, tuple):
                output = b"".join(part or b"" for part in output)
            text = output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output or "")
            return True, {"exit_code": result.exit_code, "output": text[-MAX_EXEC_OUTPUT_CHARS:]}
        except Exception as exc:
            return False, str(exc)

    def _validate_path(self, raw_path: str) -> tuple[bool, str]:
        path = raw_path.strip()
        if not path:
            return False, "path cannot be empty"
        clean = posixpath.normpath(path)
        if not clean.startswith("/"):
            return False, "path must be absolute (start with /)"
        parts = clean.split("/")
        if ".." in parts:
            return False, "path traversal is not allowed"
        for prefix in SENSITIVE_PATH_PREFIXES:
            if clean == prefix or clean.startswith(prefix + "/"):
                return False, f"access to '{prefix}' is restricted"
        if clean in SENSITIVE_FILES:
            return False, f"access to '{clean}' is restricted"
        return True, clean

    def _get_file_sync(self, name_or_id: str, path: str) -> tuple[bool, str]:
        ok, clean_path = self._validate_path(path)
        if not ok:
            return False, clean_path

        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            bits, _ = container.get_archive(clean_path)
            tar_bytes = bytearray()
            for chunk in bits:
                tar_bytes.extend(chunk)
                if len(tar_bytes) > MAX_FILE_READ_BYTES + 8192:
                    return False, f"file archive exceeds read limit of {MAX_FILE_READ_BYTES} bytes"

            with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
                member = tar.next()
                if member is None:
                    return False, "empty archive"
                if not member.isreg():
                    return False, f"target '{clean_path}' is not a regular file"
                if member.size > MAX_FILE_READ_BYTES:
                    return False, f"file size ({member.size} bytes) exceeds limit of {MAX_FILE_READ_BYTES} bytes"
                f = tar.extractfile(member)
                if f is None:
                    return False, "could not extract file"
                content = f.read(MAX_FILE_READ_BYTES + 1).decode("utf-8", "replace")
                return True, content
        except Exception as exc:
            return False, str(exc)

    def _put_file_sync(self, name_or_id: str, path: str, content: str) -> tuple[bool, str]:
        ok, clean_path = self._validate_path(path)
        if not ok:
            return False, clean_path

        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            dirname = posixpath.dirname(clean_path) or "/"
            basename = posixpath.basename(clean_path)
            if not basename or "/" in basename or "\\" in basename or basename in {".", ".."}:
                return False, "invalid destination filename"

            data = content.encode("utf-8")
            if len(data) > MAX_FILE_WRITE_BYTES:
                return False, f"content size ({len(data)} bytes) exceeds limit of {MAX_FILE_WRITE_BYTES} bytes"

            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                ti = tarfile.TarInfo(name=basename)
                ti.size = len(data)
                ti.mtime = int(time.time())
                ti.mode = 0o644
                tar.addfile(ti, io.BytesIO(data))
            tar_buf.seek(0)
            container.put_archive(dirname, tar_buf)
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    def _inspect_sync(self, name_or_id: str) -> tuple[bool, dict[str, Any] | str]:
        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            attrs = container.attrs
            state = attrs.get("State") or {}
            health = (state.get("Health") or {}).get("Status", "")
            ports = (attrs.get("NetworkSettings") or {}).get("Ports") or {}
            return True, {
                "id": container.short_id,
                "name": (container.name or "").lstrip("/"),
                "image": _image_name(container),
                "status": state.get("Status", ""),
                "health": health,
                "restart_count": state.get("RestartCount", 0),
                "started_at": state.get("StartedAt", ""),
                "entrypoint": (attrs.get("Config") or {}).get("Entrypoint") or [],
                "command": (attrs.get("Config") or {}).get("Cmd") or [],
                "ports": ports,
                "mount_count": len(attrs.get("Mounts") or []),
            }
        except Exception as exc:
            return False, str(exc)

    def _guard(self, name_or_id: str, force: bool) -> str:
        if not force and self.is_denied(name_or_id):
            return f"{name_or_id} is on the restart denylist"
        if not force and self.allowlist_blocks(name_or_id):
            return f"{name_or_id} is not on the restart allow-list"
        return ""

    def _action_sync(self, name_or_id: str, force: bool, action: str) -> tuple[bool, str]:
        blocked = self._guard(name_or_id, force)
        if blocked:
            return False, blocked
        client = self._connect()
        if client is None:
            return False, "Docker engine is not reachable"
        try:
            container = client.containers.get(name_or_id)
            if action == "start":
                container.start()
                return True, "started"
            if action == "stop":
                container.stop(timeout=20)
                return True, "stopped"
            container.restart(timeout=20)
            return True, "restarted"
        except Exception as exc:
            return False, str(exc)

    def is_denied(self, name: str) -> bool:
        lowered = name.lower()
        return any(token and token in lowered for token in self.settings.denylist)

    def allowlist_blocks(self, name: str) -> bool:
        allow = self.settings.allowlist
        if not allow:
            return False
        lowered = name.lower()
        return not any(token and token in lowered for token in allow)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def _image_name(container: Any) -> str:
    try:
        tags = container.image.tags
        if tags:
            return tags[0]
    except Exception:
        pass
    return (container.attrs.get("Config") or {}).get("Image", "")
