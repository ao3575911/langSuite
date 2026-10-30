"""Docker sandbox verifier (SPEC §8): no network, read-only root, non-root user,
all capabilities dropped, Docker's default seccomp profile, no-new-privileges,
CPU/memory/pids/time/output caps, and images pinned by digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from langsuite.core.errors import DataError, LangsuiteError
from langsuite.core.paths import data_home
from langsuite.verify.toolchains import Toolchain

METHOD = "docker-sandbox/1"
MEMORY = "256m"
PIDS = 64
CPUS = "1"
TMPFS = "/tmp:rw,exec,nosuid,size=256m,mode=1777"
USER = "65534:65534"
OUTPUT_CAP = 64 * 1024


class Status(StrEnum):
    PASS = "pass"  # noqa: S105 - exit 0 and output matched (or no expected output given)
    FAIL = "fail"  # non-zero exit, or output differs from expected
    TIMEOUT = "timeout"
    MEMORY = "memory"  # killed by the memory cap
    REFUSED = "refused"  # image digest did not match the pin, or image missing
    ERROR = "error"  # docker itself failed


class DigestMismatchError(DataError):
    """The local image does not carry the pinned digest; we refuse to run it."""


class DockerUnavailableError(LangsuiteError):
    def __init__(self) -> None:
        super().__init__(
            "Docker is not available, so code cannot be verified.",
            hint="Install Docker (or start it) and retry. `docker info` should work.",
        )


@dataclass(frozen=True)
class Proc:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


class Docker(Protocol):
    def __call__(
        self, args: Sequence[str], timeout: float | None = None, stdin: bytes | None = None
    ) -> Proc: ...


def docker_bin() -> list[str]:
    raw = os.environ.get("LANGSUITE_DOCKER", "docker")
    return raw.split()


def cli_docker(
    args: Sequence[str], timeout: float | None = None, stdin: bytes | None = None
) -> Proc:
    """Run the docker CLI. Missing binary raises DockerUnavailableError."""
    exe = docker_bin()
    if shutil.which(exe[0]) is None:
        raise DockerUnavailableError()
    try:
        cp = subprocess.run(
            [*exe, *args], input=stdin, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        return Proc(124, exc.stdout or b"", exc.stderr or b"", timed_out=True)
    return Proc(cp.returncode, cp.stdout, cp.stderr)


DOCKER: Docker = cli_docker  # swapped in tests


def _docker(docker: Docker | None) -> Docker:
    return docker if docker is not None else DOCKER


def docker_available(docker: Docker | None = None) -> bool:
    try:
        return (
            _docker(docker)(["version", "--format", "{{.Server.Version}}"], timeout=10).returncode
            == 0
        )
    except DockerUnavailableError:
        return False


@dataclass(frozen=True)
class Limits:
    memory: str = MEMORY
    pids: int = PIDS
    cpus: str = CPUS
    output_cap: int = OUTPUT_CAP
    timeout_s: float | None = None  # None → toolchain default


@dataclass
class VerifyResult:
    status: Status
    lang: str
    toolchain: str
    image: str
    digest: str
    code_sha256: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    expected_checked: bool
    truncated: bool = False
    reason: str = ""
    cached: bool = False
    method: str = METHOD
    limits: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is Status.PASS

    @property
    def evidence_id(self) -> str:
        return (
            "vr-"
            + hashlib.sha1(  # noqa: S324 - id, not security
                f"{self.digest}|{self.code_sha256}|{self.status}".encode()
            ).hexdigest()[:12]
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "lang": self.lang,
            "toolchain": self.toolchain,
            "image": self.image,
            "digest": self.digest,
            "code_sha256": self.code_sha256,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "expected_checked": self.expected_checked,
            "truncated": self.truncated,
            "reason": self.reason,
            "cached": self.cached,
            "method": self.method,
            "limits": self.limits,
            "evidence_id": self.evidence_id,
        }

    def canonical(self) -> dict[str, Any]:
        """The reproducible part: no timing, no cache flag."""
        data = self.to_json()
        for key in ("duration_ms", "cached"):
            data.pop(key)
        return data

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> VerifyResult:
        keys = {k: v for k, v in d.items() if k not in {"evidence_id", "status"}}
        return cls(status=Status(d["status"]), **keys)


def sandbox_args(
    tc: Toolchain, image_id: str, src_dir: Path, name: str, limits: Limits
) -> list[str]:
    """The exact `docker run` arguments. Kept pure so tests can assert every cap."""
    args = [
        "run",
        "--name", name,
        "--network", "none",
        "--read-only",
        "--tmpfs", TMPFS,
        "--user", USER,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", str(limits.pids),
        "--memory", limits.memory,
        "--memory-swap", limits.memory,
        "--cpus", limits.cpus,
        "--ulimit", "nofile=256:256",
        "--ulimit", "fsize=67108864:67108864",
        "--workdir", "/tmp",
        "--env", "HOME=/tmp",
        "--log-driver", "none",
        "-i",
        "-v", f"{src_dir}:/src:ro",
    ]  # fmt: skip
    for key, value in tc.env:
        args += ["--env", f"{key}={value}"]
    args += ["--entrypoint", "/bin/sh", image_id, "-c", tc.command]
    return args


def _same_ref(repo_digest: str, pinned: str) -> bool:
    def norm(ref: str) -> str:
        for prefix in ("docker.io/", "library/"):
            ref = ref.removeprefix(prefix)
        return ref

    return norm(repo_digest) == norm(pinned)


def resolve_image(tc: Toolchain, docker: Docker | None = None, pull: bool = True) -> str:
    """Return the local image id for the pinned digest, pulling it on demand.

    Refuses (DigestMismatchError) when the local tag points at a different digest,
    or when the image is missing and pulling is off.
    """
    docker = _docker(docker)

    def inspect(ref: str) -> dict[str, Any] | None:
        p = docker(["image", "inspect", ref], timeout=30)
        if p.returncode != 0:
            return None
        data: list[dict[str, Any]] = json.loads(p.stdout or b"[]")
        return data[0] if data else None

    def has_digest(info: dict[str, Any]) -> bool:
        return any(_same_ref(rd, tc.pinned) for rd in info.get("RepoDigests") or [])

    info = inspect(tc.pinned)
    if info is not None and has_digest(info):
        return str(info["Id"])
    tagged = inspect(tc.ref)
    if tagged is not None and not has_digest(tagged):
        raise DigestMismatchError(
            f"Image {tc.ref} does not match its pinned digest {tc.digest[:19]}…; refusing to run.",
            hint=f"Remove the local image so the pinned one is pulled: `docker rmi {tc.ref}`.",
        )
    if not pull:
        raise DigestMismatchError(
            f"Pinned image {tc.pinned[:40]}… is not present and pulling is off.",
            hint="Retry without --no-pull.",
        )
    p = docker(["pull", "--quiet", tc.pinned], timeout=1800)
    if p.returncode != 0:
        raise DataError(
            f"Could not pull {tc.ref}: {p.stderr.decode(errors='replace').strip()[:200]}",
            hint="Check your network, then retry.",
        )
    info = inspect(tc.pinned)
    if info is None or not has_digest(info):
        raise DigestMismatchError(f"Pulled image for {tc.ref} has an unexpected digest.")
    return str(info["Id"])


def _norm_output(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def outputs_match(actual: str, expected: str) -> bool:
    """Trailing whitespace and trailing blank lines are ignored."""
    return _norm_output(actual) == _norm_output(expected)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def cache_key(tc: Toolchain, code: str, stdin: str, expected: str | None, limits: Limits) -> str:
    raw = json.dumps(
        [METHOD, tc.lang, tc.digest, tc.command, code, stdin, expected, limits.__dict__],
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "verify" / "cache"


def _cap(data: bytes, cap: int) -> tuple[str, bool]:
    if len(data) > cap:
        return data[:cap].decode(errors="replace"), True
    return data.decode(errors="replace"), False


def run_code(
    tc: Toolchain,
    code: str,
    *,
    stdin: str = "",
    expected: str | None = None,
    limits: Limits | None = None,
    docker: Docker | None = None,
    pull: bool = True,
    home: Path | None = None,
    use_cache: bool = True,
) -> VerifyResult:
    """Verify `code` with toolchain `tc`. Results are cached by content hash."""
    docker = _docker(docker)
    limits = limits or Limits()
    key = cache_key(tc, code, stdin, expected, limits)
    cfile = cache_dir(home) / f"{key}.json"
    if use_cache and cfile.exists():
        res = VerifyResult.from_json(json.loads(cfile.read_text()))
        res.cached = True
        return res
    base = {
        "lang": tc.lang,
        "toolchain": tc.name,
        "image": tc.ref,
        "digest": tc.digest,
        "code_sha256": code_hash(code),
        "expected_checked": expected is not None,
        "limits": {
            "memory": limits.memory,
            "pids": limits.pids,
            "cpus": limits.cpus,
            "timeout_s": limits.timeout_s or tc.timeout_s,
            "network": "none",
        },
    }
    try:
        image_id = resolve_image(tc, docker, pull=pull)
    except DigestMismatchError as refusal:
        return VerifyResult(
            status=Status.REFUSED, exit_code=None, stdout="", stderr="", duration_ms=0,
            reason=refusal.message, **base,  # type: ignore[arg-type]
        )  # fmt: skip
    timeout = limits.timeout_s or tc.timeout_s
    name = f"langsuite-verify-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="langsuite-src-") as tmp:
        src = Path(tmp)
        (src / tc.filename).write_text(code)
        os.chmod(src, 0o755)  # noqa: S103 - the sandbox user must read the source
        os.chmod(src / tc.filename, 0o644)
        start = time.monotonic()
        proc = docker(
            sandbox_args(tc, image_id, src, name, limits),
            timeout=timeout,
            stdin=stdin.encode(),
        )
        duration = int((time.monotonic() - start) * 1000)
        oom = False
        if proc.timed_out:
            docker(["kill", name], timeout=30)
        else:
            st = docker(["inspect", "--format", "{{.State.OOMKilled}}", name], timeout=30)
            oom = st.stdout.strip() == b"true"
        docker(["rm", "-f", name], timeout=30)
    out, t1 = _cap(proc.stdout, limits.output_cap)
    err, t2 = _cap(proc.stderr, limits.output_cap)
    if proc.timed_out:
        status, reason = Status.TIMEOUT, f"killed after {timeout:g}s"
    elif oom or (proc.returncode == 137 and not out):
        status, reason = Status.MEMORY, f"killed by the {limits.memory} memory cap"
    elif proc.returncode == 125:
        status, reason = Status.ERROR, "docker could not start the container"
    elif proc.returncode != 0:
        status, reason = Status.FAIL, f"exit code {proc.returncode}"
    elif expected is not None and not outputs_match(out, expected):
        status, reason = Status.FAIL, "output differs from expected"
    else:
        status, reason = Status.PASS, "exit 0" + (", output matched" if expected else "")
    res = VerifyResult(
        status=status,
        exit_code=None if proc.timed_out else proc.returncode,
        stdout=out,
        stderr=err,
        duration_ms=duration,
        truncated=t1 or t2,
        reason=reason,
        **base,  # type: ignore[arg-type]
    )
    if use_cache and status in {Status.PASS, Status.FAIL, Status.TIMEOUT, Status.MEMORY}:
        cfile.parent.mkdir(parents=True, exist_ok=True)
        tmpf = cfile.with_name(f".{uuid.uuid4().hex}.tmp")
        tmpf.write_text(json.dumps(res.to_json(), sort_keys=True))
        tmpf.replace(cfile)
    return res
