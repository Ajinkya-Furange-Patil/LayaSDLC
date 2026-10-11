"""Stage 6: code-aware context engineering tests.

Covers the required scenarios: stale git revisions, missing files, large
files, budget exhaustion, deduplication, provenance, and the guarantee that
mandatory items are never dropped.
"""

from __future__ import annotations

import subprocess

import pytest

from layasdlc.context import (
    ContextItem,
    ContextPackage,
    ItemKind,
    Source,
    build_package,
    compact_context,
    deduplicate,
    estimate_tokens,
    from_filename_search,
    from_git_diff,
    from_symbol_search,
    from_test_failures,
    from_python_ast,
    load_tiktoken,
    measure_tokens,
    microcompact,
    rank_items,
)


# ======================================================================================
# Token accounting
# ======================================================================================


def test_estimate_tokens_is_positive():
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("a" * 400) >= 100


def test_measure_tokens_without_tokenizer_returns_estimate():
    count, measured = measure_tokens("hello world")
    assert count == estimate_tokens("hello world")
    assert measured is False


def test_measure_tokens_with_tokenizer_returns_measured():
    class FakeTokenizer:
        def encode(self, text):
            return list(range(len(text)))

    count, measured = measure_tokens("hello", tokenizer=FakeTokenizer())
    assert count == 5
    assert measured is True


# ======================================================================================
# Git diff retrieval
# ======================================================================================


def test_from_git_diff_returns_empty_for_non_repo(tmp_path):
    result = from_git_diff(str(tmp_path))
    assert result == []


def test_from_git_diff_reads_changed_files(tmp_path):
    """Create a repo with a commit, then modify a file and check the diff."""
    _init_repo(tmp_path)
    (tmp_path / "module.py").write_text("def foo():\n    return 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "module.py").write_text("def foo():\n    return 2\n")
    items = from_git_diff(str(tmp_path))

    assert items
    assert any("module.py" in (item.source.file or "") for item in items)
    assert any("return 2" in item.content for item in items)


def test_from_git_diff_stale_revision_returns_empty(tmp_path):
    """A revision that doesn't exist yields no items, not an error."""
    _init_repo(tmp_path)
    items = from_git_diff(str(tmp_path), revision="deadbeefdeadbeef")
    assert items == []


# ======================================================================================
# Filename search
# ======================================================================================


def test_from_filename_search_finds_matching_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("hello")

    items = from_filename_search(str(tmp_path), ["*.py"])
    assert items
    assert all("main.py" in item.source.file for item in items)


def test_from_filename_search_flags_large_files(tmp_path):
    (tmp_path / "big.py").write_text("x" * 200_000)
    (tmp_path / "small.py").write_text("x = 1")

    items = from_filename_search(str(tmp_path), ["*.py"], max_file_size=1000)
    big = next(i for i in items if "big.py" in i.source.file)
    small = next(i for i in items if "small.py" in i.source.file)
    assert big.score < small.score


# ======================================================================================
# Symbol search
# ======================================================================================


def test_from_symbol_search_finds_definitions(tmp_path):
    (tmp_path / "app.py").write_text("def calculate_total():\n    return 42\n")
    items = from_symbol_search(str(tmp_path), ["calculate_total"])
    assert items
    assert any("calculate_total" in item.content for item in items)


def test_from_symbol_search_returns_empty_for_missing(tmp_path):
    (tmp_path / "app.py").write_text("x = 1")
    items = from_symbol_search(str(tmp_path), ["nonexistent_symbol"])
    assert items == []


# ======================================================================================
# Python AST extraction
# ======================================================================================


def test_from_python_ast_finds_function_definitions(tmp_path):
    (tmp_path / "app.py").write_text(
        "def calculate_total(items):\n"
        "    return sum(items)\n"
        "\n"
        "def other():\n"
        "    pass\n"
    )
    items = from_python_ast(str(tmp_path), ["calculate_total"])
    assert items
    assert any("def calculate_total" in item.content for item in items)
    assert all("def other" not in item.content for item in items)


def test_from_python_ast_finds_class_definitions(tmp_path):
    (tmp_path / "app.py").write_text(
        "class OrderService:\n"
        "    def process(self):\n"
        "        pass\n"
    )
    items = from_python_ast(str(tmp_path), ["OrderService"])
    assert items
    assert any("class OrderService" in item.content for item in items)


def test_from_python_ast_includes_body_when_requested(tmp_path):
    (tmp_path / "app.py").write_text(
        "def foo():\n"
        "    x = 1\n"
        "    return x\n"
    )
    items = from_python_ast(str(tmp_path), ["foo"], include_body=True)
    assert items
    assert any("x = 1" in item.content for item in items)


def test_from_python_ast_excludes_body_by_default(tmp_path):
    (tmp_path / "app.py").write_text(
        "def foo():\n"
        "    x = 1\n"
        "    return x\n"
    )
    items = from_python_ast(str(tmp_path), ["foo"], include_body=False)
    assert items
    assert all("x = 1" not in item.content for item in items)
    assert any("def foo" in item.content for item in items)


def test_from_python_ast_handles_syntax_errors(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n")
    (tmp_path / "good.py").write_text("def fine():\n    pass\n")
    items = from_python_ast(str(tmp_path), ["fine"])
    assert items  # good.py is still parsed


def test_from_python_ast_finds_module_constants(tmp_path):
    (tmp_path / "config.py").write_text(
        "MAX_RETRIES = 3\n"
        "OTHER = 99\n"
    )
    items = from_python_ast(str(tmp_path), ["MAX_RETRIES"])
    assert items
    assert any("MAX_RETRIES" in item.content for item in items)


# ======================================================================================
# Microcompact
# ======================================================================================


def test_microcompact_deduplicates_overlapping_reads():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="line 1",
                    source=Source(file="a.py", line_start=1)),
        ContextItem(kind=ItemKind.SNIPPET, content="line 1 again",
                    source=Source(file="a.py", line_start=1)),
        ContextItem(kind=ItemKind.SNIPPET, content="line 2",
                    source=Source(file="a.py", line_start=2)),
    ]
    result = microcompact(items)
    assert len(result) == 2


def test_microcompact_keeps_distinct_sources():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="x",
                    source=Source(file="a.py", line_start=1)),
        ContextItem(kind=ItemKind.SNIPPET, content="y",
                    source=Source(file="b.py", line_start=1)),
    ]
    result = microcompact(items)
    assert len(result) == 2


# ======================================================================================
# Auto-compaction
# ======================================================================================


def test_compact_context_returns_unchanged_when_under_budget():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="short",
                    source=Source(file="a.py")),
    ]
    result, summarized = compact_context(items, max_tokens=1000)
    assert summarized == 0
    assert len(result) == 1


def test_compact_context_summarizes_low_scoring_items():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="x" * 400,
                    source=Source(file="big.py"), score=0.1),
        ContextItem(kind=ItemKind.CONSTRAINT, content="must",
                    source=Source(file="constraints.md"), score=0.9),
    ]
    result, summarized = compact_context(items, max_tokens=50)
    assert summarized >= 1
    assert any(item.kind is ItemKind.CONSTRAINT for item in result)


# ======================================================================================
# Token counting with tiktoken
# ======================================================================================


def test_load_tiktoken_returns_none_when_not_installed():
    result = load_tiktoken()
    if result is not None:
        assert len(result.encode("hello")) > 0


def test_measure_tokens_with_fake_tokenizer():
    class FakeTokenizer:
        def encode(self, text):
            return list(range(len(text.split())))

    count, measured = measure_tokens("one two three", tokenizer=FakeTokenizer())
    assert count == 3
    assert measured is True


# ======================================================================================
# Test failure retrieval
# ======================================================================================


def test_from_test_failures_parses_pytest_output():
    output = (
        "tests/test_app.py::test_login FAILED\n"
        "tests/test_app.py:42: AssertionError: expected 200, got 500\n"
        "tests/test_app.py:50: ValueError: bad input"
    )
    items = from_test_failures(output)
    assert len(items) == 2
    assert all(item.kind is ItemKind.TEST_RESULT for item in items)
    assert items[0].source.line_start == 42
    assert items[1].source.line_start == 50


# ======================================================================================
# Ranking
# ======================================================================================


def test_rank_items_prioritises_path_overlap():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="x",
                    source=Source(file="src/unrelated.py"), score=0.5),
        ContextItem(kind=ItemKind.SNIPPET, content="y",
                    source=Source(file="src/target.py"), score=0.5),
    ]
    ranked = rank_items(items, objective="fix the target",
                        path_hints=["target.py"])
    assert ranked[0].source.file == "src/target.py"


def test_rank_items_prioritises_test_results():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="x",
                    source=Source(file="a.py"), score=0.9),
        ContextItem(kind=ItemKind.TEST_RESULT, content="y",
                    source=Source(file="b.py"), score=0.5),
    ]
    ranked = rank_items(items, objective="fix")
    assert ranked[0].kind is ItemKind.TEST_RESULT


# ======================================================================================
# Budgeting
# ======================================================================================


def test_build_package_includes_mandatory_items_under_budget_pressure():
    """Constraints and questions are never dropped, even when over budget."""
    items = [
        ContextItem(kind=ItemKind.CONSTRAINT, content="x" * 1000,
                    source=Source(file="constraints.md")),
        ContextItem(kind=ItemKind.QUESTION, content="y" * 1000,
                    source=Source(file="questions.md")),
        ContextItem(kind=ItemKind.SNIPPET, content="z" * 100,
                    source=Source(file="code.py"), score=1.0),
    ]
    package = build_package("objective", items, budget_tokens=200,
                            reserved_tokens=50)
    kinds = {item.kind for item in package.items}
    assert ItemKind.CONSTRAINT in kinds
    assert ItemKind.QUESTION in kinds


def test_build_package_drops_discretionary_first():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="a" * 400,
                    source=Source(file="a.py"), score=0.9),
        ContextItem(kind=ItemKind.SNIPPET, content="b" * 400,
                    source=Source(file="b.py"), score=0.1),
    ]
    package = build_package("objective", items, budget_tokens=200,
                            reserved_tokens=50)
    assert len(package.items) == 1
    assert "a" in package.items[0].content


def test_build_package_marks_unchanged_items():
    item = ContextItem(kind=ItemKind.SNIPPET, content="stable",
                       source=Source(file="a.py"))
    previous = ContextPackage(objective="obj", items=[item])
    package = build_package("obj", [item], budget_tokens=8000,
                            previous=previous)
    assert package.items[0].unchanged is True


def test_build_package_reports_drops_in_note():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="x" * 2000,
                    source=Source(file="big.py"), score=1.0),
    ]
    package = build_package("obj", items, budget_tokens=100,
                            reserved_tokens=50)
    assert package.note is not None
    assert "dropped" in package.note


# ======================================================================================
# Deduplication
# ======================================================================================


def test_deduplicate_merges_identical_content():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="same",
                    source=Source(file="a.py")),
        ContextItem(kind=ItemKind.SNIPPET, content="same",
                    source=Source(file="b.py")),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_deduplicate_keeps_distinct_content():
    items = [
        ContextItem(kind=ItemKind.SNIPPET, content="alpha",
                    source=Source(file="a.py")),
        ContextItem(kind=ItemKind.SNIPPET, content="beta",
                    source=Source(file="b.py")),
    ]
    result = deduplicate(items)
    assert len(result) == 2


# ======================================================================================
# Provenance
# ======================================================================================


def test_source_describe_includes_line_ranges():
    source = Source(file="src/app.py", line_start=10, line_end=15)
    assert "app.py:10-15" in source.describe()


def test_source_describe_single_line():
    source = Source(file="src/app.py", line_start=42, line_end=42)
    assert "app.py:42" in source.describe()


def test_source_describe_test():
    source = Source(test="pytest")
    assert "pytest" in source.describe()


def test_source_describe_file_takes_priority_over_test():
    source = Source(file="test.py", line_start=1, line_end=1, test="pytest")
    assert source.describe() == "test.py:1"


# ======================================================================================
# Package views
# ======================================================================================


def test_package_separates_mandatory_and_discretionary():
    package = ContextPackage(
        objective="test",
        items=[
            ContextItem(kind=ItemKind.CONSTRAINT, content="must",
                        source=Source()),
            ContextItem(kind=ItemKind.SNIPPET, content="optional",
                        source=Source()),
        ],
    )
    assert len(package.mandatory_items) == 1
    assert len(package.discretionary_items) == 1
    assert package.mandatory_items[0].kind is ItemKind.CONSTRAINT


def test_package_to_dict_is_serialisable():
    package = ContextPackage(objective="test", items=[])
    payload = package.to_dict()
    assert payload["objective"] == "test"
    assert payload["items"] == []


# ======================================================================================
# Helpers
# ======================================================================================


def _init_repo(path):
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")


def _git(path, *args):
    return subprocess.run(["git", *args], cwd=str(path),
                          capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    """A git repository with one commit."""
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("initial\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path
