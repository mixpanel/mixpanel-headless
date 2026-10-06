"""Repository guards for the code reviewer configuration.

Copilot code review reads ``.github/instructions/*.instructions.md`` by their
``applyTo`` globs. Greptile reads the same files through scoped entries in
``.greptile/files.json``. Copilot code review also loads the review skill in
``.github/skills/code-review/``. These guards keep the reviewers in step. They
compare structure (paths, scopes, rule ids, skill names), not prose. Every
guard is offline and reports every violation in one assertion message.

| Guard | Fails when |
| --- | --- |
| Front matter | An instruction file has no ``applyTo`` key. |
| Context paths | A ``path`` in a ``.greptile/files.json`` does not exist. |
| Coverage | An instruction file has no entry in ``.greptile/files.json``. |
| Scopes | An entry's ``scope`` differs from the ``applyTo`` globs of its file. |
| Rule ids | An instruction file names a Greptile rule id that no config defines. |
| Pointers | A ``.greptile`` ``instructions`` string names a missing file. |
| Review skill | The ``code-review`` skill is absent, or a skill's ``name`` breaks the rules. |
| Skill paths | A skill names a repository path that does not exist. |
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tests.unit.plugin._content import parse_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]
"""Repository root (``tests/unit/test_reviewer_config.py`` → two levels up)."""

INSTRUCTIONS_DIR = REPO_ROOT / ".github" / "instructions"
"""Folder that holds the path-specific Copilot instruction files."""

ROOT_FILES_JSON = REPO_ROOT / ".greptile" / "files.json"
"""Greptile context-file list that registers the instruction files."""

SKILLS_DIR = REPO_ROOT / ".github" / "skills"
"""Folder that holds the Copilot agent skills, one sub-folder per skill."""

REVIEW_SKILL = SKILLS_DIR / "code-review" / "SKILL.md"
"""Skill that Copilot code review loads for review tasks in this repository."""

GREPTILE_SEARCH_ROOTS = (
    "src",
    "tests",
    "conformance",
    "specs",
    "docs",
    "mixpanel-plugin",
)
"""Top-level folders searched for nested ``.greptile`` folders.

The search skips build output, virtual environments, and mutation-testing
copies, which can hold stale ``.greptile`` folders.
"""

_RULE_LINE = re.compile(r"Greptile rules? for this area:(?P<ids>.*)", re.DOTALL)
"""Matches the trailing rule-id line of an instruction file."""

_INSTRUCTION_PATH = re.compile(r"\.github/instructions/[\w.-]+\.instructions\.md")
"""Matches a repository path to one instruction file."""

_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
"""A skill name: lowercase words joined by single hyphens."""

_BACKTICKED_PATH = re.compile(r"`((?:\.?[\w-]+/)+[\w.-]*|[\w.-]+\.md)`")
"""Matches a backticked repository path, such as ``tests/live/`` or ``REVIEW.md``."""


def _report(title: str, violations: list[str]) -> str:
    """Format violations as one assertion message.

    Args:
        title: The guard name.
        violations: One line per violation.

    Returns:
        The title followed by one indented line per violation.
    """
    return "\n".join([f"{title}: {len(violations)} violation(s)", *violations])


def _instruction_files() -> list[Path]:
    """List the path-specific instruction files.

    Returns:
        Every ``*.instructions.md`` file, sorted by name.
    """
    return sorted(INSTRUCTIONS_DIR.glob("*.instructions.md"))


def _apply_to(path: Path) -> list[str] | None:
    """Read the ``applyTo`` globs of one instruction file.

    Args:
        path: The instruction file.

    Returns:
        The comma-separated globs, stripped, or ``None`` when the file has no
        front matter or no ``applyTo`` key.
    """
    frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
    if frontmatter is None or "applyTo" not in frontmatter:
        return None
    return [glob.strip() for glob in frontmatter["applyTo"].split(",")]


def _greptile_dirs() -> list[Path]:
    """List the root ``.greptile`` folder and every nested one.

    Returns:
        The root folder first, then nested folders under
        ``GREPTILE_SEARCH_ROOTS``, sorted.
    """
    nested = sorted(
        found
        for top in GREPTILE_SEARCH_ROOTS
        for found in (REPO_ROOT / top).rglob(".greptile")
        if found.is_dir()
    )
    return [REPO_ROOT / ".greptile", *nested]


def _load_json(path: Path) -> dict[str, Any]:
    """Load one Greptile JSON file.

    Args:
        path: The JSON file.

    Returns:
        The parsed object.
    """
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _rel(path: Path) -> str:
    """Show a path relative to the repository root.

    Args:
        path: An absolute path inside the repository.

    Returns:
        The POSIX path relative to ``REPO_ROOT``.
    """
    return path.relative_to(REPO_ROOT).as_posix()


class TestInstructionFrontMatter:
    """Every instruction file declares where it applies."""

    def test_instruction_files_exist(self) -> None:
        """The instruction folder holds at least one file, so the guards run."""
        assert _instruction_files(), f"no files in {_rel(INSTRUCTIONS_DIR)}"

    def test_every_file_has_apply_to(self) -> None:
        """Each file has front matter with an ``applyTo`` key (Copilot ignores it otherwise)."""
        violations = [
            f"{_rel(path)}: no applyTo in front matter"
            for path in _instruction_files()
            if _apply_to(path) is None
        ]
        assert not violations, _report("applyTo present", violations)


class TestGreptileContextFiles:
    """Greptile context entries exist and match the Copilot scopes."""

    def test_context_paths_exist(self) -> None:
        """Each ``path`` in every ``files.json`` exists, relative to its folder."""
        violations: list[str] = []
        for folder in _greptile_dirs():
            files_json = folder / "files.json"
            if not files_json.is_file():
                continue
            for entry in _load_json(files_json)["files"]:
                if not (folder.parent / entry["path"]).exists():
                    violations.append(f"{_rel(files_json)}: missing {entry['path']}")
        assert not violations, _report("Context paths exist", violations)

    def test_every_instruction_file_is_registered(self) -> None:
        """Each instruction file has an entry in the root ``files.json``."""
        registered = {entry["path"] for entry in _load_json(ROOT_FILES_JSON)["files"]}
        violations = [
            f"{_rel(path)}: not in {_rel(ROOT_FILES_JSON)}"
            for path in _instruction_files()
            if _rel(path) not in registered
        ]
        assert not violations, _report("Instruction files registered", violations)

    def test_scope_matches_apply_to(self) -> None:
        """An entry's ``scope`` holds the same globs as its file's ``applyTo``."""
        violations: list[str] = []
        for entry in _load_json(ROOT_FILES_JSON)["files"]:
            if not _INSTRUCTION_PATH.fullmatch(entry["path"]):
                continue
            path = REPO_ROOT / entry["path"]
            if not path.is_file():
                continue  # test_context_paths_exist reports it
            apply_to = _apply_to(path) or []
            scope = entry.get("scope", [])
            if sorted(scope) != sorted(apply_to):
                violations.append(
                    f"{entry['path']}: scope {scope} != applyTo {apply_to}"
                )
        assert not violations, _report("Scope matches applyTo", violations)


class TestGreptileRuleIds:
    """Rule ids named in instruction files exist in a Greptile config."""

    def test_named_rule_ids_exist(self) -> None:
        """Each id on a "Greptile rules for this area" line is defined in a ``config.json``."""
        defined = {
            rule["id"]
            for folder in _greptile_dirs()
            if (folder / "config.json").is_file()
            for rule in _load_json(folder / "config.json").get("rules", [])
            if "id" in rule
        }
        violations: list[str] = []
        for path in _instruction_files():
            match = _RULE_LINE.search(path.read_text(encoding="utf-8"))
            if match is None:
                continue
            for rule_id in re.findall(r"`([a-z0-9-]+)`", match.group("ids")):
                if rule_id not in defined:
                    violations.append(f"{_rel(path)}: unknown rule id {rule_id}")
        assert not violations, _report("Rule ids exist", violations)


class TestGreptilePointers:
    """Instruction pointers in Greptile configs name real files."""

    def test_pointed_files_exist(self) -> None:
        """Each instruction-file path in an ``instructions`` string exists."""
        violations: list[str] = []
        for folder in _greptile_dirs():
            config = folder / "config.json"
            if not config.is_file():
                continue
            text = _load_json(config).get("instructions", "")
            for pointed in _INSTRUCTION_PATH.findall(text):
                if not (REPO_ROOT / pointed).is_file():
                    violations.append(f"{_rel(config)}: missing {pointed}")
        assert not violations, _report("Pointed files exist", violations)


def _skill_files() -> list[Path]:
    """List the Copilot agent skill files.

    Returns:
        Every ``SKILL.md`` one level under ``SKILLS_DIR``, sorted.
    """
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


class TestReviewSkill:
    """The Copilot review skill exists and every skill has valid front matter."""

    def test_review_skill_exists(self) -> None:
        """Copilot code review finds its skill at ``.github/skills/code-review/``."""
        assert REVIEW_SKILL.is_file(), f"missing {_rel(REVIEW_SKILL)}"

    def test_skill_front_matter(self) -> None:
        """Each skill has a ``description`` and a lowercase hyphenated ``name`` equal to its folder."""
        violations: list[str] = []
        for path in _skill_files():
            frontmatter = parse_frontmatter(path.read_text(encoding="utf-8")) or {}
            name = frontmatter.get("name", "")
            if not _SKILL_NAME.fullmatch(name):
                violations.append(
                    f"{_rel(path)}: name {name!r} is not lowercase-hyphen"
                )
            if name != path.parent.name:
                violations.append(
                    f"{_rel(path)}: name {name!r} != folder {path.parent.name!r}"
                )
            if not frontmatter.get("description", "").strip():
                violations.append(f"{_rel(path)}: no description")
        assert not violations, _report("Skill front matter", violations)

    def test_skill_paths_exist(self) -> None:
        """Each backticked repository path in a skill exists."""
        violations = [
            f"{_rel(path)}: missing {named}"
            for path in _skill_files()
            for named in _BACKTICKED_PATH.findall(path.read_text(encoding="utf-8"))
            if not (REPO_ROOT / named).exists()
        ]
        assert not violations, _report("Skill paths exist", violations)
