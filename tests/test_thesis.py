"""The thesis in the advice deck: structured output checked by code, never text matching."""

import ast
from pathlib import Path

PROJECT = Path(__file__).parent.parent
REGEX_MODULES = {"re", "regex"}
REGEX_CALLS = ("match", "search", "sub", "findall", "compile")


def test_no_file_in_the_project_uses_regular_expressions():
    files = [*PROJECT.glob("src/**/*.py"), *PROJECT.glob("tests/**/*.py")]
    imported = {
        (path.name, name)
        for path in files
        for node in ast.walk(ast.parse(path.read_text()))
        for name in _modules(node)
        if name in REGEX_MODULES
    }

    assert len(files) > 20
    assert imported == set()


def test_the_acceptance_search_for_regular_expressions_finds_nothing():
    """The search is a plain text search, so it also finds a harmless import whose first name
    starts with the regex module's name. Such an import is written another way."""
    module = "r" + "e"
    wanted = [f"import {module}", *(f"{module}.{call}(" for call in REGEX_CALLS)]
    files = [*PROJECT.glob("src/**/*.py"), *PROJECT.glob("tests/**/*.py")]
    found = [
        f"{path.name}: {line.strip()}"
        for path in files
        for line in path.read_text().splitlines()
        if any(text in line for text in wanted)
    ]

    assert found == []


def _modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]

    return []
