from pathlib import Path

from grandpa.jarvis.context_resolver import SafeContextResolver, is_protected_path


def test_project_path_resolution(tmp_path: Path) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()

    resolver = SafeContextResolver([tmp_path])

    resolved = resolver.resolve_project("Grandpa")

    assert resolved is not None
    assert resolved.path == project.resolve(strict=False)


def test_protected_folder_skipping(tmp_path: Path) -> None:
    protected = tmp_path / ".ssh"
    protected.mkdir()
    project = protected / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()

    resolver = SafeContextResolver([protected])

    assert is_protected_path(protected)
    assert resolver.resolve_project("Grandpa") is None


def test_grandpa_project_name_variants(tmp_path: Path) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='grandpa'\n", encoding="utf-8"
    )

    resolver = SafeContextResolver([tmp_path])

    assert resolver.resolve_project("Grandpa project") is not None
