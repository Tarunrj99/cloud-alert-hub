"""Release hygiene tests — guard against the kind of release-time drift
we hit during the v0.5.0–v0.5.3 series.

What this file pins
-------------------

A handful of *checked-in artefacts* must stay synchronised when a new
version is cut:

    pyproject.toml::project.version
    │
    ├── CHANGELOG.md must have a   "## [X.Y.Z]"   release section.
    ├── CHANGELOG.md must have a   "[X.Y.Z]: …"   link reference at the
    │   bottom (the GitHub-style auto-link footer).
    ├── CHANGELOG.md "[Unreleased]: …compare/vX.Y.Z...HEAD" must compare
    │   against the same X.Y.Z (so first-time readers learn what
    │   "since the last release" means relative to the current code).
    └── Every user-facing example / deploy doc pin (READMEs, recipe
        snippets, requirements.txt files) must say "@vX.Y.Z" — anyone
        copying these examples deploys *exactly* the version this
        commit advertises.

Why a test and not a CHANGELOG note
-----------------------------------

Three times during today's release work (v0.5.0, v0.5.2, v0.5.3) one
of the four artefacts above drifted from the others:

- v0.5.0 added ``policy_user_labels`` routing but ``ARCHITECTURE.md``
  didn't mention it for two more releases.
- v0.5.0–v0.5.2 had stale CHANGELOG link refs ([0.4.0] was the
  newest).
- v0.5.3 was cut while example pins still pointed at @v0.5.2 (the
  buggy version) — anyone copy-pasting an example after the release
  would have deployed the bug we just fixed.

Each was caught by a human review. Each could have been caught
automatically. This file exists so the *next* release rolls without
those failure modes silently surfacing in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _pyproject_version() -> str:
    """Return the value of project.version in pyproject.toml.

    We parse with a simple regex rather than tomllib so this test stays
    Python-3.10 compatible (the rest of the codebase targets 3.10+).
    """
    text = _read("pyproject.toml")
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert match, "pyproject.toml has no top-level project.version line"
    return match.group(1)


def _changelog_release_headings() -> list[str]:
    text = _read("CHANGELOG.md")
    # ``## [Unreleased]`` is intentionally excluded; we only care about
    # *cut* releases here.
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.MULTILINE)


def _changelog_link_refs() -> list[str]:
    """Bottom-of-file link references like ``[0.5.3]: https://…``."""
    text = _read("CHANGELOG.md")
    return re.findall(r"^\[(\d+\.\d+\.\d+)\]:", text, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# pyproject ↔ CHANGELOG section
# ---------------------------------------------------------------------------


def test_pyproject_version_has_changelog_release_section() -> None:
    """``pyproject.toml`` says version=X.Y.Z → ``CHANGELOG.md`` must have
    a ``## [X.Y.Z]`` heading describing what shipped.

    Failure mode this catches: someone bumps the version in pyproject
    to cut a release but forgets to write the CHANGELOG entry. The
    public release page on GitHub would then show stale notes.
    """
    py_version = _pyproject_version()
    headings = _changelog_release_headings()
    assert py_version in headings, (
        f"pyproject.toml version is {py_version!r} but CHANGELOG.md has no "
        f"'## [{py_version}]' release section. Released versions found: "
        f"{headings[:5]}…\n"
        "Add a CHANGELOG entry before tagging the release, or roll the "
        "version bump back into Unreleased work."
    )


def test_changelog_link_refs_cover_every_release_section() -> None:
    """Every ``## [X.Y.Z]`` heading must have a matching
    ``[X.Y.Z]: https://…/releases/tag/vX.Y.Z`` link reference at the
    bottom of CHANGELOG.md.

    Failure mode this catches: when v0.5.0 was cut the link-ref footer
    still stopped at [0.4.0]. The release notes rendered fine on
    GitHub (Markdown auto-resolves) but the in-file ``[0.5.0]`` link
    silently became broken text.
    """
    headings = set(_changelog_release_headings())
    refs = set(_changelog_link_refs())
    missing = sorted(headings - refs)
    assert not missing, (
        "CHANGELOG.md has release sections without matching link refs: "
        f"{missing}.\nAdd '[X.Y.Z]: https://github.com/Tarunrj99/cloud-alert-hub/"
        "releases/tag/vX.Y.Z' lines at the bottom of CHANGELOG.md so the "
        "table-of-contents links resolve."
    )


def test_unreleased_link_ref_compares_against_latest_version() -> None:
    """The ``[Unreleased]`` link ref must compare ``vX.Y.Z…HEAD`` where
    X.Y.Z matches ``pyproject.toml``.

    Failure mode this catches: after cutting v0.5.0 we left the footer
    ``[Unreleased]: …compare/v0.4.0...HEAD`` for two releases. Means
    a reader clicking "Unreleased" on the rendered CHANGELOG sees a
    diff that includes the v0.4.0→v0.5.0 *and* the post-v0.5.0
    changes — confusing.
    """
    py_version = _pyproject_version()
    text = _read("CHANGELOG.md")
    match = re.search(
        r"^\[Unreleased\]:\s*https?://[^\s]+/compare/v(\d+\.\d+\.\d+)\.\.\.HEAD",
        text,
        flags=re.MULTILINE,
    )
    assert match, (
        "CHANGELOG.md must have an '[Unreleased]: …/compare/vX.Y.Z...HEAD' "
        "link reference."
    )
    compares_against = match.group(1)
    assert compares_against == py_version, (
        f"[Unreleased] link compares against v{compares_against} but "
        f"pyproject.toml is at {py_version}. Update the [Unreleased] "
        "footer to compare against the latest released tag whenever you "
        "bump pyproject."
    )


# ---------------------------------------------------------------------------
# pyproject ↔ user-facing example pins
# ---------------------------------------------------------------------------


# Files where a pin like ``@vX.Y.Z`` is the canonical "what users
# should deploy" pointer. If pyproject says 0.5.3, every one of these
# must point at @v0.5.3.
_USER_FACING_PIN_FILES: list[str] = [
    "README.md",
    "docs/DEPLOY_GCP.md",
    "docs/DEPLOY_AWS.md",
    "docs/DEPLOY_AZURE.md",
    "examples/gcp-cloud-function/README.md",
    "examples/gcp-cloud-function/requirements.txt",
    "examples/aws-lambda/README.md",
    "examples/aws-lambda/requirements.txt",
    "examples/local-dev/requirements.txt",
]

# Files where ``@vX.Y.Z`` is an *illustrative* example (e.g. "pin to
# a tag like @v0.1.0") rather than the real recommendation. Excluded
# from the strict-version-match scan.
_ILLUSTRATIVE_PIN_FILES: list[str] = [
    "docs/QUICKSTART.md",
    "docs/DEBUG_RUNBOOK.md",
    "CHANGELOG.md",  # historical version refs by definition
]

_PIN_PATTERN = re.compile(
    # cloud-alert-hub[extra]<spaces>@<spaces>git+<url>@vX.Y.Z
    # The extra (e.g. ``[gcp]``) is optional; whitespace around the first
    # ``@`` is also optional (requirements.txt has none, README has it).
    r"cloud-alert-hub(?:\[[^\]]+\])?\s*@\s*git\+[^\s@]+@v(\d+\.\d+\.\d+)"
)
_PIN_PATTERN_BRACKETED = re.compile(r"`@v(\d+\.\d+\.\d+)`")


def _pins_in_file(path: Path) -> list[tuple[int, str]]:
    r"""Return (line_number, version) for every cloud-alert-hub pin in
    a file. Looks at both the canonical
    ``cloud-alert-hub @ git+…@vX.Y.Z`` form and inline mentions like
    ``pin to a tag (\`@vX.Y.Z\`)``.
    """
    out: list[tuple[int, str]] = []
    if not path.exists():
        return out
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for m in _PIN_PATTERN.finditer(line):
            out.append((line_no, m.group(1)))
        for m in _PIN_PATTERN_BRACKETED.finditer(line):
            out.append((line_no, m.group(1)))
    return out


@pytest.mark.parametrize("rel_path", _USER_FACING_PIN_FILES)
def test_user_facing_pin_matches_pyproject_version(rel_path: str) -> None:
    """Every ``@vX.Y.Z`` pin in user-facing examples must equal the
    version in ``pyproject.toml``.

    Failure mode this catches: v0.5.3 was cut while example pins still
    pointed at ``@v0.5.2`` — the buggy version. Anyone copying the
    example *after* the release would have deployed the bug we'd just
    fixed. This test fails in CI for any commit where pyproject is
    bumped without an accompanying pin sweep.
    """
    py_version = _pyproject_version()
    pins = _pins_in_file(REPO_ROOT / rel_path)
    if not pins:
        # The file might not contain a pin at all (e.g. a deploy doc
        # where the snippet was rewritten). That's fine — the
        # parametrised test has many rows and others will catch the
        # version drift.
        pytest.skip(f"{rel_path} contains no pin to verify")
    mismatched = [(line_no, v) for line_no, v in pins if v != py_version]
    assert not mismatched, (
        f"{rel_path} has pins that don't match pyproject.toml@{py_version}:\n"
        + "\n".join(f"  line {ln}: @v{v}" for ln, v in mismatched)
        + "\n\nWhen bumping pyproject.toml, update every user-facing example "
        "pin in the same commit so people copying the examples get the "
        "version this commit advertises."
    )


def test_user_facing_pins_form_a_consistent_set() -> None:
    """Belt-and-braces: every pin across every user-facing file must
    agree, even if pyproject hasn't been bumped yet.

    Catches the case where a contributor bumps the README pin without
    bumping the docs/, or vice-versa. Pyproject is the source of
    truth, but partial bumps are themselves bugs.
    """
    versions: dict[str, list[tuple[str, int]]] = {}
    for rel in _USER_FACING_PIN_FILES:
        for line_no, v in _pins_in_file(REPO_ROOT / rel):
            versions.setdefault(v, []).append((rel, line_no))

    if len(versions) <= 1:
        return  # all pins agree (or no pins at all)

    # Build a human-readable failure summary
    summary_lines = []
    for v in sorted(versions):
        sites = versions[v]
        summary_lines.append(f"  @v{v} (in {len(sites)} place(s)):")
        for rel, line_no in sites:
            summary_lines.append(f"    {rel}:{line_no}")
    raise AssertionError(
        "User-facing pins don't agree on a single version. Bump them all "
        "in the same commit so users copy a consistent set:\n"
        + "\n".join(summary_lines)
    )


# ---------------------------------------------------------------------------
# Self-test: the regexes above are picky. Make sure they actually
# match what they should.
# ---------------------------------------------------------------------------


def test_pin_pattern_recognises_canonical_forms() -> None:
    """If someone refactors the pin format (e.g. using PyPI instead of
    git+https), the parametrised test above could silently start
    skipping every file. Self-test the regex against known forms so
    the scanner can never become a no-op."""
    samples = {
        # canonical requirements.txt pin
        "cloud-alert-hub[gcp] @ git+https://github.com/Tarunrj99/cloud-alert-hub.git@v0.5.3":
            "0.5.3",
        # canonical README snippet (with extra)
        "cloud-alert-hub[aws] @ git+https://github.com/<you>/cloud-alert-hub.git@v0.5.3":
            "0.5.3",
        # bracketed inline reference
        "Pin to a tag (`@v0.5.3`) or commit SHA":
            "0.5.3",
    }
    for line, expected in samples.items():
        canonical = _PIN_PATTERN.findall(line)
        bracketed = _PIN_PATTERN_BRACKETED.findall(line)
        found = canonical + bracketed
        assert expected in found, (
            f"pin pattern failed to find @v{expected} in {line!r}; "
            f"matched={found!r}"
        )
