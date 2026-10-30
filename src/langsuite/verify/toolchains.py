"""The 20 pinned verifier toolchains (SPEC §8: images pinned by digest).

Each toolchain names an official image by tag **and** sha256 digest. The verifier
refuses to run an image whose digest does not match (see `sandbox.resolve_image`).
Digests were resolved from Docker Hub on 2026-10-30 with `scripts/pin_toolchains.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from langsuite.core.errors import UsageError


@dataclass(frozen=True)
class Toolchain:
    lang: str  # KB language id
    name: str
    image: str  # repository, e.g. "python"
    tag: str
    digest: str  # sha256:...
    filename: str  # where the source is mounted, under /src
    command: str  # run inside `sh -c`; compile steps write to /tmp
    timeout_s: float = 10.0
    env: tuple[tuple[str, str], ...] = field(default=())
    # Rosetta snippets often omit boilerplate; a prelude is added when `unless` is absent.
    # Each (text, unless) pair is prepended when `unless` does not occur in the code;
    # applied last-first, so the first pair ends up on top.
    preludes: tuple[tuple[str, str], ...] = ()

    def prepare(self, code: str) -> str:
        for text, unless in reversed(self.preludes):
            if unless not in code:
                code = text + code
        return code

    @property
    def ref(self) -> str:
        return f"{self.image}:{self.tag}"

    @property
    def pinned(self) -> str:
        return f"{self.image}@{self.digest}"

    def with_prelude(self, *pairs: tuple[str, str]) -> Toolchain:
        return replace(self, preludes=pairs)

    def to_json(self) -> dict[str, object]:
        return {
            "lang": self.lang,
            "name": self.name,
            "image": self.ref,
            "digest": self.digest,
            "timeout_s": self.timeout_s,
        }


def _tc(
    lang: str,
    name: str,
    ref: str,
    digest: str,
    filename: str,
    command: str,
    timeout_s: float = 10.0,
    **env: str,
) -> Toolchain:
    image, tag = ref.rsplit(":", 1)
    return Toolchain(
        lang, name, image, tag, digest, filename, command, timeout_s, tuple(sorted(env.items()))
    )


TOOLCHAINS: tuple[Toolchain, ...] = (
    _tc("python", "Python 3.12", "python:3.12-alpine",
        "sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8",
        "main.py", "python3 /src/main.py", PYTHONDONTWRITEBYTECODE="1"),
    _tc("javascript", "Node.js 22", "node:22-alpine",
        "sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914",
        "main.js", "node /src/main.js"),
    _tc("typescript", "Deno 2.1", "denoland/deno:alpine-2.1.4",
        "sha256:bbbc64e254c4fbd928da597faae8633e2302c630386f3469595444c0b29e14d6",
        "main.ts", "deno run --no-prompt --quiet /src/main.ts", 20.0, DENO_DIR="/tmp/deno"),
    _tc("ruby", "Ruby 3.3", "ruby:3.3-alpine",
        "sha256:24ea89e8103548bc02b53ae5212313afaccc79d11c5f93982bd4de298ec0934d",
        "main.rb", "ruby /src/main.rb"),
    _tc("perl", "Perl 5.40", "perl:5.40-slim",
        "sha256:e2b9469bfe29c1e61a72da181136bdca7c67e27ecffd0862154091db8539e704",
        "main.pl", "perl /src/main.pl"),
    _tc("php", "PHP 8.3", "php:8.3-cli-alpine",
        "sha256:86a7a8f46bbf73120a19cf72246f606b6de9aaa84a00971c25d187fbae44c211",
        "main.php", "php /src/main.php"),
    _tc("bash", "Bash 5.2", "bash:5.2",
        "sha256:e900b34300c5bca37879a980687da197234b65325044647e76198a4cd3c0abb7",
        "main.sh", "bash /src/main.sh"),
    _tc("c", "GCC 14 (C)", "gcc:14",
        "sha256:435c3cbc2ad1c25fbc1684c367808ff0ca2035a1bed56734a40165ab5cd7e3bd",
        "main.c", "gcc -O1 -o /tmp/a.out /src/main.c -lm && /tmp/a.out", 30.0),
    _tc("cpp", "GCC 14 (C++)", "gcc:14",
        "sha256:435c3cbc2ad1c25fbc1684c367808ff0ca2035a1bed56734a40165ab5cd7e3bd",
        "main.cpp", "g++ -O1 -std=c++20 -o /tmp/a.out /src/main.cpp && /tmp/a.out", 45.0),
    _tc("go", "Go 1.23", "golang:1.23-alpine",
        "sha256:383395b794dffa5b53012a212365d40c8e37109a626ca30d6151c8348d380b5f",
        "main.go", "cd /tmp && go run /src/main.go", 60.0,
        GOCACHE="/tmp/gocache", GOPATH="/tmp/go", GOFLAGS="-mod=mod", GO111MODULE="off"),
    _tc("rust", "Rust 1.83", "rust:1.83-alpine",
        "sha256:0ac946ed7597a9f053a1be2ce38c09aa88b3d7079a91ea491493615294b1f699",
        "main.rs", "rustc -O -o /tmp/a.out /src/main.rs && /tmp/a.out", 60.0),
    _tc("java", "Java 21 (Temurin)", "eclipse-temurin:21-jdk-alpine",
        "sha256:b78a1d385da875588e21207f07dddf9a1418849971ae857fb24c8f3a7d441a72",
        "Main.java", "java -Xmx128m -XX:TieredStopAtLevel=1 /src/Main.java", 30.0),
    _tc("haskell", "GHC 9.10", "haskell:9.10-slim-bullseye",
        "sha256:1e6ffb83340649e724f5b45396ff739433ff146a8e85aef86e28b1e999124153",
        "main.hs", "runghc /src/main.hs", 45.0),
    _tc("erlang", "Erlang/OTP 27", "erlang:27-alpine",
        "sha256:130ac3712786ae682b38ef2795d87153c9993f1a33091ec340bc3d8fd7a13476",
        "main.erl", "escript /src/main.erl", 20.0)
    .with_prelude(("#!/usr/bin/env escript\n", "#!"), ("main(_) -> ", "main(")),
    _tc("elixir", "Elixir 1.17", "elixir:1.17-alpine",
        "sha256:a18ff0994d093a7ffb29ee264412e18986287554b6b1faf2c7dab11c15059189",
        "main.exs", "elixir /src/main.exs", 20.0),
    _tc("julia", "Julia 1.11", "julia:1.11",
        "sha256:4b3206ed4b7e0a29ef01a48794c7be0330491fcb27a38c0b8ac31ab4c005baf2",
        "main.jl", "julia --startup-file=no /src/main.jl", 45.0,
        JULIA_DEPOT_PATH="/tmp/julia:"),
    _tc("r", "R 4.4", "r-base:4.4.2",
        "sha256:fe9b29520eeb5292d814b0958783c0ddfcdab37402967a3e67307604354f98d7",
        "main.R", "Rscript --vanilla /src/main.R", 30.0),
    _tc("racket", "Racket 8.15", "racket/racket:8.15",
        "sha256:e0bb81dba6027e26b8c4a5a546d4b7b62003f9d1f0e32e2bef0c372c4f9cc069",
        "main.rkt", "racket /src/main.rkt", 30.0, PLTUSERHOME="/tmp/racket")
    .with_prelude(("#lang racket\n", "#lang")),
    _tc("common-lisp", "SBCL", "clfoundation/sbcl:latest",
        "sha256:cceb8e98066cdc56130b0d21d160618ea7eb8033de62f550bd2baefc5bcabf06",
        "main.lisp", "sbcl --script /src/main.lisp", 20.0),
    _tc("dart", "Dart 3.6", "dart:3.6",
        "sha256:7a6a4ad2560e46cb6979bd73f46edec0fa7bc092146f5fafefdf3c6568a77e75",
        "main.dart", "dart run /src/main.dart", 45.0, PUB_CACHE="/tmp/pub"),
)  # fmt: skip

BY_LANG: dict[str, Toolchain] = {t.lang: t for t in TOOLCHAINS}


def toolchain_for(lang_id: str) -> Toolchain:
    tc = BY_LANG.get(lang_id)
    if tc is None:
        raise UsageError(
            f"No verifier toolchain for `{lang_id}`.",
            hint="See `langsuite verify --toolchains` for the 20 supported languages.",
        )
    return tc
