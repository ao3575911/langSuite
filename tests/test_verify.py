"""M4: Rosetta pack + Docker verifier (SPEC §10 M4).

Unit tests use a fake docker; the `docker` tests run real containers and cover the
acceptance list: known-good passes, bad fails, network blocked, timeout, memory and
fork-bomb caps enforced, image digest mismatch refused.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from langsuite.cli.app import main
from langsuite.core.errors import NoResultError, UsageError
from langsuite.core.workspace import Workspace
from langsuite.verify import evidence as vev
from langsuite.verify import rosetta, sandbox
from langsuite.verify.sandbox import (
    DigestMismatchError,
    Limits,
    Proc,
    Status,
    VerifyResult,
    outputs_match,
    resolve_image,
    run_code,
    sandbox_args,
)
from langsuite.verify.toolchains import BY_LANG, TOOLCHAINS, toolchain_for

HELLO = Path(__file__).parent / "fixtures" / "verify" / "hello"
PY = BY_LANG["python"]


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        main(args)
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def data(out: str) -> Any:
    return json.loads(out)["data"]


class FakeDocker:
    """Records calls; answers like the docker CLI would."""

    def __init__(
        self,
        *,
        digests: dict[str, list[str]] | None = None,
        run: Proc | None = None,
        oom: bool = False,
        pull_ok: bool = True,
    ) -> None:
        self.calls: list[list[str]] = []
        self.images = {k: v for k, v in (digests or {}).items()}  # ref -> RepoDigests
        self.run = run or Proc(0, b"Hello world!\n", b"")
        self.oom = oom
        self.pull_ok = pull_ok

    def __call__(
        self, args: Sequence[str], timeout: float | None = None, stdin: bytes | None = None
    ) -> Proc:
        args = list(args)
        self.calls.append(args)
        if args[0] == "version":
            return Proc(0, b"27.3.1\n", b"")
        if args[:2] == ["image", "inspect"]:
            ref = args[2]
            if ref in self.images:
                info = [{"Id": "sha256:" + "a" * 64, "RepoDigests": self.images[ref]}]
                return Proc(0, json.dumps(info).encode(), b"")
            return Proc(1, b"[]", b"No such image")
        if args[0] == "pull":
            if not self.pull_ok:
                return Proc(1, b"", b"pull access denied")
            ref = args[-1]
            self.images[ref] = [ref.replace("docker.io/", "")]
            return Proc(0, b"", b"")
        if args[0] == "run":
            return self.run
        if args[0] == "inspect":
            return Proc(0, b"true\n" if self.oom else b"false\n", b"")
        return Proc(0, b"", b"")

    def ran(self) -> int:
        return sum(1 for c in self.calls if c[0] == "run")


def pinned_fake(**kw: Any) -> FakeDocker:
    return FakeDocker(digests={PY.pinned: [PY.pinned]}, **kw)


# ----- toolchains --------------------------------------------------------------------


def test_twenty_pinned_toolchains() -> None:
    assert len(TOOLCHAINS) == 20
    assert len({t.lang for t in TOOLCHAINS}) == 20
    for t in TOOLCHAINS:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", t.digest), t.lang
        assert t.pinned == f"{t.image}@{t.digest}"
        assert (HELLO / t.filename).is_file(), f"known-good fixture for {t.lang}"
        assert t.to_json()["image"] == t.ref
    with pytest.raises(UsageError, match="No verifier toolchain"):
        toolchain_for("cobol")


def test_preludes_add_missing_boilerplate_only() -> None:
    racket, erlang = BY_LANG["racket"], BY_LANG["erlang"]
    assert racket.prepare("(displayln 1)") == "#lang racket\n(displayln 1)"
    assert racket.prepare("#lang racket/base\n(x)") == "#lang racket/base\n(x)"
    wrapped = erlang.prepare('io:format("x").')
    assert wrapped.startswith("#!/usr/bin/env escript\nmain(_) -> io:format")
    assert erlang.prepare("#!/x\nmain(_) -> ok.") == "#!/x\nmain(_) -> ok."
    assert PY.prepare("print(1)") == "print(1)"


# ----- sandbox -----------------------------------------------------------------------


def test_sandbox_args_enforce_every_cap(tmp_path: Path) -> None:
    args = sandbox_args(PY, "sha256:abc", tmp_path, "n1", Limits())
    joined = " ".join(args)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 64",
        "--memory 256m",
        "--memory-swap 256m",
        "--cpus 1",
        "--user 65534:65534",
        f"-v {tmp_path}:/src:ro",
        "--log-driver none",
    ):
        assert flag in joined, flag
    assert "--privileged" not in joined and "/var/run/docker.sock" not in joined
    assert args[-4:] == ["sha256:abc", "-c", PY.command][-4 + 1 :] or args[-3] == "sha256:abc"
    assert tuple(
        args[
            args.index("PYTHONDONTWRITEBYTECODE=1") - 1 : args.index("PYTHONDONTWRITEBYTECODE=1")
            + 1
        ]
    ) == ("--env", "PYTHONDONTWRITEBYTECODE=1")


def test_outputs_match_ignores_trailing_space_only() -> None:
    assert outputs_match("a  \nb\n\n", "a\nb")
    assert outputs_match("a\r\nb\r\n", "a\nb\n")
    assert not outputs_match("A\nb", "a\nb")
    assert not outputs_match(" a", "a")


def test_resolve_image_accepts_pinned_digest() -> None:
    fake = pinned_fake()
    assert resolve_image(PY, fake) == "sha256:" + "a" * 64
    assert not any(c[0] == "pull" for c in fake.calls)


def test_resolve_image_pulls_on_demand() -> None:
    fake = FakeDocker()
    resolve_image(PY, fake)
    assert ["pull", "--quiet", PY.pinned] in fake.calls


def test_digest_mismatch_is_refused_before_running(tmp_path: Path) -> None:
    other = "python@sha256:" + "0" * 64
    fake = FakeDocker(digests={PY.ref: [other]})  # local tag moved to another digest
    with pytest.raises(DigestMismatchError, match="does not match its pinned digest"):
        resolve_image(PY, fake)
    res = run_code(PY, "print(1)", docker=fake, home=tmp_path)
    assert res.status is Status.REFUSED and fake.ran() == 0
    assert "refusing to run" in res.reason


def test_other_repo_with_same_digest_is_refused() -> None:
    evil = replace(PY, image="example/evil")
    fake = FakeDocker(digests={evil.ref: [PY.pinned]})
    with pytest.raises(DigestMismatchError):
        resolve_image(evil, fake)


def test_missing_image_without_pull_is_refused(tmp_path: Path) -> None:
    res = run_code(PY, "print(1)", docker=FakeDocker(), pull=False, home=tmp_path)
    assert res.status is Status.REFUSED and "pulling is off" in res.reason


def test_failed_pull_is_a_data_error() -> None:
    from langsuite.core.errors import DataError

    with pytest.raises(DataError, match="Could not pull"):
        resolve_image(PY, FakeDocker(pull_ok=False))


@pytest.mark.parametrize(
    ("proc", "oom", "expected", "status"),
    [
        (Proc(0, b"Hello world!\n", b""), False, "Hello world!", Status.PASS),
        (Proc(0, b"hello\n", b""), False, "Hello world!", Status.FAIL),
        (Proc(3, b"", b"boom"), False, None, Status.FAIL),
        (Proc(124, b"", b"", timed_out=True), False, None, Status.TIMEOUT),
        (Proc(137, b"", b""), True, None, Status.MEMORY),
        (Proc(125, b"", b"bad flag"), False, None, Status.ERROR),
    ],
)
def test_status_mapping(
    tmp_path: Path, proc: Proc, oom: bool, expected: str | None, status: Status
) -> None:
    fake = pinned_fake(run=proc, oom=oom)
    res = run_code(PY, "x", expected=expected, docker=fake, home=tmp_path)
    assert res.status is status
    assert any(c[:2] == ["rm", "-f"] for c in fake.calls)  # never leaves containers behind
    if status is Status.TIMEOUT:
        assert any(c[0] == "kill" for c in fake.calls)


def test_output_is_capped(tmp_path: Path) -> None:
    fake = pinned_fake(run=Proc(0, b"x" * 100, b""))
    res = run_code(PY, "x", docker=fake, home=tmp_path, limits=Limits(output_cap=10))
    assert res.stdout == "x" * 10 and res.truncated


def test_results_are_cached_by_content(tmp_path: Path) -> None:
    fake = pinned_fake()
    first = run_code(PY, "print(1)", docker=fake, home=tmp_path)
    again = run_code(PY, "print(1)", docker=fake, home=tmp_path)
    assert fake.ran() == 1 and again.cached and not first.cached
    assert again.canonical() == first.canonical()
    assert again.evidence_id == first.evidence_id
    run_code(PY, "print(2)", docker=fake, home=tmp_path)
    assert fake.ran() == 2
    run_code(PY, "print(1)", docker=fake, home=tmp_path, use_cache=False)
    assert fake.ran() == 3
    assert VerifyResult.from_json(first.to_json()).canonical() == first.canonical()


def test_docker_missing_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSUITE_DOCKER", "langsuite-no-such-binary")
    assert not sandbox.docker_available()
    with pytest.raises(sandbox.DockerUnavailableError):
        sandbox.cli_docker(["version"])


# ----- Rosetta pack ------------------------------------------------------------------

WIKI = """{{task}}
==Intro==
text
=={{header|Python}}==
<syntaxhighlight lang="python">print("Hello world!")</syntaxhighlight>
<syntaxhighlight lang="python">print('Hello world!')</syntaxhighlight>
=={{header|C++}}==
<lang cpp>#include &lt;iostream&gt;
int main() { std::cout << "Hello world!\\n"; }</lang>
=={{header|Common Lisp}}==
no code here
=={{header|Quux|lang=x}}==
<syntaxhighlight lang="q">say hi</syntaxhighlight>
"""


def test_parse_wikitext_keeps_every_variant() -> None:
    sols = rosetta.parse_wikitext(WIKI)
    assert set(sols) == {"python", "cpp", "quux"}
    assert sols["python"].variants == ('print("Hello world!")\n', "print('Hello world!')\n")
    assert "#include <iostream>" in sols["cpp"].code  # entities unescaped
    assert sols["cpp"].header == "C++"
    resolved = rosetta.parse_wikitext(WIKI, resolve=lambda h: "py3" if h == "Python" else None)
    assert "py3" in resolved


def test_repo_pack_is_attributed_and_has_oracles() -> None:
    tasks = rosetta.load_tasks()
    assert len(tasks) >= 7
    fizz = rosetta.find_task(tasks, "fizzbuzz")
    assert fizz.expected is not None and len(fizz.expected.splitlines()) == 100
    assert "GFDL-1.2" in fizz.attribution and f"oldid={fizz.revid}" in fizz.attribution
    covered = set().union(*(set(t.solutions) & set(BY_LANG) for t in tasks.values()))
    assert len(covered) == 20  # every toolchain has Rosetta evidence
    raw = json.loads((Path("data-packs/rosetta/tasks/fizzbuzz.json")).read_text())
    assert raw["licence"] == "GFDL-1.2" and raw["attribution"] == fizz.attribution


def test_find_task_errors() -> None:
    tasks = rosetta.load_tasks()
    assert rosetta.find_task(tasks, "Loops/For").title == "Loops/For"
    with pytest.raises(NoResultError, match="No single Rosetta task"):
        rosetta.find_task(tasks, "loops")  # ambiguous
    with pytest.raises(NoResultError, match="No Rosetta pack"):
        rosetta.find_task({}, "x")


def test_user_pack_overrides_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSUITE_PACKS", str(tmp_path))
    task = rosetta.Task("FizzBuzz", 1, "2026-10-30T00:00:00Z", {})
    rosetta.save_task(task, rosetta.user_pack_dir())
    assert rosetta.load_tasks()["fizzbuzz"].revid == 1
    (rosetta.user_pack_dir() / "tasks" / "bad.json").write_text("{")
    from langsuite.core.errors import DataError

    with pytest.raises(DataError, match="unreadable"):
        rosetta.load_tasks()


def test_fetch_task_parses_api(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {
        "query": {
            "pages": [
                {
                    "title": "Hello world/Text",
                    "revisions": [{"revid": 7, "slots": {"main": {"content": WIKI}}}],
                }
            ]
        }
    }
    monkeypatch.setattr(rosetta, "_get", lambda params: page)
    task = rosetta.fetch_task("Hello world/Text")
    assert task.revid == 7 and "python" in task.solutions
    monkeypatch.setattr(rosetta, "_get", lambda params: {"query": {"pages": [{"missing": True}]}})
    with pytest.raises(NoResultError):
        rosetta.fetch_task("Nope")


def test_check_solution_tries_variants(tmp_path: Path) -> None:
    task = rosetta.Task(
        "Hello world/Text",
        1,
        "t",
        {"python": rosetta.Solution("python", "Python", ("bad\n", "good\n"))},
    )

    class ByCode(FakeDocker):
        def __call__(
            self, args: Sequence[str], timeout: float | None = None, stdin: bytes | None = None
        ) -> Proc:
            if args[0] == "run":
                src = Path(args[args.index("-v") + 1].split(":")[0]) / "main.py"
                ok = src.read_text() == "good\n"
                self.calls.append(list(args))
                return Proc(0, b"Hello world!\n" if ok else b"nope\n", b"")
            return super().__call__(args, timeout, stdin)

    fake = ByCode(digests={PY.pinned: [PY.pinned]})
    check = vev.check_solution(task, "python", docker=fake, home=tmp_path)
    assert check.verified and check.variant == 1 and check.tried == 2 and check.code == "good\n"
    rates = vev.verified_rate([check])
    assert rates == {"python": (1, 1)}
    refused = vev.check_solution(
        task, "python", docker=FakeDocker(), pull=False, home=tmp_path / "other"
    )
    assert not refused.verified and refused.tried == 1 and refused.result.status is Status.REFUSED


# ----- CLI ---------------------------------------------------------------------------


def test_cli_toolchains(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--json", "verify", "--toolchains"], capsys)
    assert code == 0 and len(data(out)) == 20
    code, out, _ = run(["--plain", "v", "--toolchains"], capsys)
    assert "20 toolchains" in out and "no network" in out


def test_cli_snippet_without_docker_is_marked_unverified(
    kb_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(["--plain", "snippet", "fizzbuzz", "--lang", "python"], capsys)
    assert code == 0
    assert "unverified · Docker not available" in out and "verified ✓" not in out
    assert "Rosetta Code, “FizzBuzz”" in out and "GFDL-1.2" in out
    code, out, _ = run(["--json", "sn", "fizzbuzz", "--lang", "python,c", "--no-verify"], capsys)
    items = data(out)
    assert [i["lang"] for i in items] == ["python", "c"]
    assert all(i["verified"] is False and "GFDL-1.2" in i["attribution"] for i in items)


def test_cli_snippet_tasks_and_errors(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "snippet", "--tasks"], capsys)
    assert code == 0 and "fizzbuzz" in out and "share-alike" in out
    code, out, _ = run(["--json", "snippet", "--tasks"], capsys)
    assert any(t["slug"] == "loops-for" for t in data(out))
    code, _, err = run(["--plain", "snippet"], capsys)
    assert code == 2 and "Name a task" in err
    code, out, err = run(["--plain", "snippet", "fizzbuzz", "--lang", "scheme"], capsys)
    assert code in (0, 2)


def test_cli_verify_needs_docker(
    kb_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "x.py"
    src.write_text("print(1)\n")
    code, _, err = run(["--plain", "verify", str(src)], capsys)
    assert code == 3 and "Docker is not available" in err
    code, _, err = run(["--plain", "verify"], capsys)
    assert code == 2 and "Give a file" in err
    code, _, err = run(["--plain", "verify", str(tmp_path / "x.unknown")], capsys)
    assert code == 2


def test_cli_verify_and_snippet_with_fake_docker(
    kb_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker(digests={t.pinned: [t.pinned] for t in TOOLCHAINS})
    monkeypatch.setattr(sandbox, "DOCKER", fake)
    src = tmp_path / "hello.py"
    src.write_text('print("Hello world!")\n')
    code, out, _ = run(["--plain", "verify", str(src), "--expect", "Hello world!"], capsys)
    assert code == 0 and "✓ verified" in out and "vr-" in out
    code, out, _ = run(["--json", "verify", str(src), "--expect", "nope"], capsys)
    assert code == 1 and data(out)["status"] == "fail"
    # extract the last verify run into a reproducible finding
    code, out, _ = run(["--plain", "extract"], capsys)
    assert code == 0 and "Verify python code" in out
    ws = Workspace.open()
    f = ws.findings()[-1]
    assert f.kind == "verify" and ws.verify(f.id).ok
    # snippet: python FizzBuzz verifies against the fake's output only if it matches
    fake.run = Proc(0, ("\n".join(rosetta.ORACLES["FizzBuzz"].splitlines()) + "\n").encode(), b"")
    code, out, _ = run(["--plain", "snippet", "fizzbuzz", "--lang", "python"], capsys)
    assert code == 0 and "✓ verified" in out and "output checked" in out
    code, out, _ = run(["--plain", "x", "--title", "FizzBuzz in Python"], capsys)
    assert code == 0
    f = Workspace.open().findings()[-1]
    assert f.kind == "snippet" and f.result["verified"] and f.evidence[0].startswith("vr-")
    code, out, _ = run(["--plain", "finding", "export", f.id, "--format", "md"], capsys)
    assert "verified ✓" in out and "```python" in out and "GFDL-1.2" in out
    code, out, _ = run(["--plain", "verify", "--task", "fizzbuzz", "--lang", "python,c"], capsys)
    assert code == 0 and "of 2 verified" in out
    code, out, _ = run(["--json", "verify", "--task", "fizzbuzz", "--lang", "python"], capsys)
    assert data(out)["checks"][0]["verified"] is True
    code, out, _ = run(["--plain", "finding", "save", "snippet", "fizzbuzz", "--lang", "c"], capsys)
    assert code == 0
    code, _, err = run(["--plain", "finding", "save", "snippet", "fizzbuzz"], capsys)
    assert code == 2 and "--lang" in err


def test_snippet_fetch_writes_user_pack(
    kb_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSUITE_PACKS", str(tmp_path / "packs"))

    def fake_fetch(title: str, resolve: Any = None) -> rosetta.Task:
        sols = rosetta.parse_wikitext(WIKI, resolve)
        return rosetta.Task(title, 9, "2026-10-30T00:00:00Z", sols)

    monkeypatch.setattr(rosetta, "fetch_task", fake_fetch)
    code, out, _ = run(["--plain", "snippet", "--fetch", "Hello world/Text"], capsys)
    assert code == 0 and "rev 9" in out
    saved = json.loads(
        (tmp_path / "packs" / "rosetta" / "tasks" / "hello-world-text.json").read_text()
    )
    assert set(saved["solutions"]) == {"python"}  # unknown languages are not kept
    code, out, _ = run(["--json", "snippet", "--fetch", "Hello world/Text"], capsys)
    assert data(out)[0]["revid"] == 9


# ----- real containers (acceptance) ----------------------------------------------------


def _docker_ready() -> bool:
    os.environ.pop("LANGSUITE_DOCKER", None)
    return shutil.which("docker") is not None and sandbox.docker_available()


@pytest.fixture
def real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSUITE_DOCKER", raising=False)
    if not _docker_ready():
        if os.environ.get("LANGSUITE_REQUIRE_DOCKER") == "1":
            pytest.fail("Docker is required here (LANGSUITE_REQUIRE_DOCKER=1) but not available")
        pytest.skip("Docker not available")


def _py(code: str, tmp_path: Path, **kw: Any) -> VerifyResult:
    return run_code(PY, code, home=tmp_path, use_cache=False, **kw)


@pytest.mark.docker
@pytest.mark.timeout(600)
def test_real_known_good_passes_and_bad_fails(real_docker: None, tmp_path: Path) -> None:
    good = _py((HELLO / "main.py").read_text(), tmp_path, expected="Hello world!")
    assert good.status is Status.PASS, good.stderr
    bad = _py("import sys\nprint('oops')\nsys.exit(3)\n", tmp_path)
    assert bad.status is Status.FAIL and bad.exit_code == 3
    wrong = _py("print('Hello, World')", tmp_path, expected="Hello world!")
    assert wrong.status is Status.FAIL and "differs" in wrong.reason


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_real_network_is_blocked(real_docker: None, tmp_path: Path) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\n"
        "except OSError:\n"
        "    print('blocked')\n"
    )
    res = _py(code, tmp_path)
    assert res.stdout.strip() == "blocked"


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_real_timeout_is_enforced(real_docker: None, tmp_path: Path) -> None:
    res = _py("import time\ntime.sleep(60)\n", tmp_path, limits=Limits(timeout_s=3))
    assert res.status is Status.TIMEOUT and res.duration_ms < 20_000


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_real_memory_cap_is_enforced(real_docker: None, tmp_path: Path) -> None:
    res = _py("b = bytearray(1024 * 1024 * 1024)\nprint(len(b))\n", tmp_path)
    assert res.status is Status.MEMORY, (res.status, res.reason, res.stderr[-300:])


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_real_fork_bomb_is_capped(real_docker: None, tmp_path: Path) -> None:
    code = (
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    while True:\n"
        "        if os.fork() == 0:\n"
        "            time.sleep(5)\n"
        "            os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    print('capped', n)\n"
    )
    res = _py(code, tmp_path, limits=Limits(timeout_s=30))
    assert res.stdout.startswith("capped"), (res.status, res.stdout, res.stderr[-300:])
    assert int(res.stdout.split()[1]) < sandbox.PIDS


@pytest.mark.docker
@pytest.mark.timeout(300)
def test_real_sandbox_is_read_only_and_unprivileged(real_docker: None, tmp_path: Path) -> None:
    code = (
        "import os\n"
        "print(os.getuid())\n"
        "try:\n"
        "    open('/etc/x', 'w')\n"
        "except OSError as e:\n"
        "    print('ro', e.errno)\n"
    )
    res = _py(code, tmp_path)
    assert res.stdout.split() == ["65534", "ro", "30"]


@pytest.mark.docker
@pytest.mark.timeout(600)
def test_real_digest_mismatch_is_refused(real_docker: None, tmp_path: Path) -> None:
    resolve_image(PY)  # make sure python:3.12-alpine exists locally under its tag
    sandbox.DOCKER(["tag", PY.pinned, PY.ref], timeout=60)
    tampered = replace(PY, digest="sha256:" + "0" * 64)
    res = run_code(tampered, "print(1)", home=tmp_path, use_cache=False)
    assert res.status is Status.REFUSED and "does not match" in res.reason


@pytest.mark.docker
@pytest.mark.timeout(3600)
@pytest.mark.skipif(os.environ.get("LANGSUITE_VERIFY_ALL") != "1", reason="all 20 images: slow")
@pytest.mark.parametrize("lang", sorted(BY_LANG))
def test_real_all_toolchains_known_good(real_docker: None, tmp_path: Path, lang: str) -> None:
    tc = BY_LANG[lang]
    res = run_code(tc, (HELLO / tc.filename).read_text(), expected="Hello world!", home=tmp_path)
    assert res.status is Status.PASS, (res.reason, res.stderr[-500:])
