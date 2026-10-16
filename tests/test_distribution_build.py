"""Build the sdist and wheel and check the files that would be published.

Nothing here uploads to TestPyPI or PyPI. A release still needs the remaining
issue #1 gates and Bob's explicit approval.
"""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PREFIX = "codex_task_broker"
FORBIDDEN_MEMBER_PARTS = (
    ".env",
    ".github/",
    ".pem",
    "AGENTS.md",
    "docs/",
    "examples/",
    "id_rsa",
    "schemas/",
    "secrets",
    "skills/",
)
def _secret_markers() -> tuple[str, ...]:
    """Markers joined in code so this file can itself be inside the sdist."""
    return (
        "BEGIN OPENSSH PRIVATE " + "KEY",
        "BEGIN RSA PRIVATE " + "KEY",
        "PYPI_API_" + "TOKEN",
        "py" + "pi-",
    )


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]


def _generated_build_paths() -> set[Path]:
    found = set((ROOT / "src").glob("*.egg-info"))
    for name in ("build", "dist"):
        path = ROOT / name
        if path.exists():
            found.add(path)
    return found


def _package_modules() -> set[str]:
    package = ROOT / "src" / PACKAGE_PREFIX
    return {
        path.relative_to(ROOT / "src").as_posix()
        for path in package.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _metadata(text: str) -> email.message.Message:
    return email.message_from_string(text, policy=policy.default)


def _assert_core_metadata(text: str, project: dict) -> None:
    message = _metadata(text)
    assert message["Name"] == project["name"] == "codex-task-broker"
    assert message["Name"] != "codex-workbuddy-coordinator"
    assert message["Version"] == project["version"]
    assert message["Summary"] == project["description"]
    assert message["Author"] == "Bob Zhang"
    assert message["Author-email"] is None
    assert message["License-Expression"] == "MIT"
    assert message["Requires-Python"] == ">=3.11"
    assert message["Description-Content-Type"] == "text/markdown"
    urls = message.get_all("Project-URL")
    assert urls is not None
    parsed = dict(item.split(", ", 1) for item in urls)
    assert parsed == {
        "Homepage": "https://github.com/bobbanga/codex-task-broker",
        "Repository": "https://github.com/bobbanga/codex-task-broker",
        "Issues": "https://github.com/bobbanga/codex-task-broker/issues",
        "Changelog": "https://github.com/bobbanga/codex-task-broker/blob/main/CHANGELOG.md",
    }
    assert set(message.get_all("Classifier")) == set(project["classifiers"])
    requires = message.get_all("Requires-Dist") or []
    assert requires
    assert all('extra == "dev"' in item for item in requires)
    description = message.get_payload()
    assert isinstance(description, str)
    readme = (ROOT / "README.md").read_text("utf-8")
    assert description == readme
    assert "尚未发布到 PyPI" in description
    for marker in _secret_markers():
        assert marker not in text


def _assert_text_has_no_secrets(text: str, label: str) -> None:
    for marker in _secret_markers():
        assert marker not in text, label
    # Built here so this source file does not contain the literal paths.
    for marker in ("D:" + "\\Code", "/Users" + "/"):
        assert marker not in text, label


def _assert_member_names_are_safe(names: list[str]) -> None:
    for name in names:
        lowered = name.replace("\\", "/").lower()
        for part in FORBIDDEN_MEMBER_PARTS:
            assert part.lower() not in lowered, name
        assert "bob-skills" not in lowered
        assert "d:/code" not in lowered
        assert "/users/" not in lowered


def _sdist_files(archive: tarfile.TarFile, root: str) -> list[str]:
    names = []
    prefix = root + "/"
    for member in archive.getmembers():
        if not member.isfile():
            continue
        assert member.name.startswith(prefix), member.name
        names.append(member.name[len(prefix) :])
    return names


def _assert_sdist_layout(names: list[str], modules: set[str]) -> None:
    allowed_files = {"LICENSE", "PKG-INFO", "README.md", "pyproject.toml", "setup.cfg"}
    for name in names:
        if name in allowed_files:
            continue
        if name.startswith("src/codex_task_broker.egg-info/"):
            assert name.rsplit("/", 1)[-1] in {
                "PKG-INFO",
                "SOURCES.txt",
                "dependency_links.txt",
                "entry_points.txt",
                "requires.txt",
                "top_level.txt",
            }, name
            continue
        if name.startswith("src/"):
            assert name.removeprefix("src/") in modules, name
            continue
        assert (
            name.startswith("tests/test_")
            and name.endswith(".py")
            and name.count("/") == 1
        ), name
    assert "PKG-INFO" in names
    assert "LICENSE" in names
    for module in modules:
        assert f"src/{module}" in names


def test_dev_extra_can_render_the_long_description() -> None:
    dev = _project()["optional-dependencies"]["dev"]
    assert "twine>=5" in dev


def test_built_distributions_carry_metadata_and_install_offline(tmp_path: Path) -> None:
    """The sdist and wheel must match the public package, then install cleanly.

    The build may download its isolated setuptools. The install of the finished
    wheel does not. Artifacts created in the checkout are removed afterwards.
    """
    project = _project()
    version = project["version"]
    before = _generated_build_paths()
    outdir = tmp_path / "dist"
    try:
        built = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(outdir)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert built.returncode == 0, built.stdout + built.stderr
        wheels = sorted(outdir.glob("*.whl"))
        sdists = sorted(outdir.glob("*.tar.gz"))
        assert [path.name for path in wheels] == [
            f"{PACKAGE_PREFIX}-{version}-py3-none-any.whl"
        ]
        assert [path.name for path in sdists] == [f"{PACKAGE_PREFIX}-{version}.tar.gz"]

        checked = subprocess.run(
            [
                sys.executable,
                "-m",
                "twine",
                "check",
                "--strict",
                str(wheels[0]),
                str(sdists[0]),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr

        modules = _package_modules()
        info = f"{PACKAGE_PREFIX}-{version}.dist-info"
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
            _assert_member_names_are_safe(names)
            for name in names:
                _assert_text_has_no_secrets(archive.read(name).decode("utf-8"), name)
            expected = set(modules) | {
                f"{info}/METADATA",
                f"{info}/WHEEL",
                f"{info}/RECORD",
                f"{info}/entry_points.txt",
                f"{info}/top_level.txt",
                f"{info}/licenses/LICENSE",
            }
            assert set(names) == expected
            metadata = archive.read(f"{info}/METADATA").decode("utf-8")
            _assert_core_metadata(metadata, project)
            entry_points = archive.read(f"{info}/entry_points.txt").decode("utf-8")
            assert entry_points.strip() == (
                "[console_scripts]\ncodex-broker = codex_task_broker.cli:main"
            )
            assert archive.read(f"{info}/top_level.txt").decode("utf-8") == (
                "codex_task_broker\n"
            )
            wheel_text = archive.read(f"{info}/WHEEL").decode("utf-8")
            assert "Root-Is-Purelib: true" in wheel_text
            assert "Tag: py3-none-any" in wheel_text
            license_text = archive.read(f"{info}/licenses/LICENSE").decode("utf-8")
            assert "MIT License" in license_text
            assert "Copyright (c) 2026 Bob Zhang" in license_text
            assert not any(name.startswith("tests/") for name in names)

        with tarfile.open(sdists[0]) as archive:
            root = f"{PACKAGE_PREFIX}-{version}"
            relative = _sdist_files(archive, root)
            _assert_member_names_are_safe(relative)
            _assert_sdist_layout(relative, modules)
            for name in relative:
                payload = archive.extractfile(f"{root}/{name}")
                assert payload is not None
                _assert_text_has_no_secrets(payload.read().decode("utf-8"), name)
            payload = archive.extractfile(f"{root}/PKG-INFO")
            assert payload is not None
            _assert_core_metadata(payload.read().decode("utf-8"), project)

        venv_dir = tmp_path / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
        venv_python = scripts / ("python.exe" if os.name == "nt" else "python")
        console = scripts / ("codex-broker.exe" if os.name == "nt" else "codex-broker")
        install = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                str(wheels[0]),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert install.returncode == 0, install.stdout + install.stderr
        help_result = subprocess.run(
            [str(console), "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
        assert "validate" in help_result.stdout
        assert "run" in help_result.stdout
    finally:
        for path in _generated_build_paths() - before:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
