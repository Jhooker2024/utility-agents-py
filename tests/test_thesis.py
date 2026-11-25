"""The thesis in the advice deck: structured output checked by code, never text matching."""

import ast
from pathlib import Path

PROJECT = Path(__file__).parent.parent
REGEX_MODULES = {"re", "regex"}


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


def _modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]

    return []
