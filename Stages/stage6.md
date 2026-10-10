Implement Stage 6: code-aware context engineering.

## Objective

Reduce unnecessary coding-model input by retrieving the smallest relevant set of source code and engineering evidence needed for a task.

## Requirements

1. Inspect the existing repository and language stack.
2. Start with Git diffs, filename search, symbol search and test-failure retrieval.
3. Add AST-based extraction only where supported by suitable parsers.
4. Identify relevant functions, classes, imports, call sites and direct dependencies.
5. Rank retrieved items using deterministic relevance signals before introducing model-based ranking.
6. Build a compact context package containing:
   - Task objective.
   - Relevant code snippets.
   - File paths and line ranges.
   - Dependency relationships.
   - Relevant test results.
   - Constraints and unresolved questions.
7. Apply a configurable context budget and reserve space for the model's response.
8. Deduplicate repeated snippets and avoid sending unchanged summaries.
9. Include provenance so each fact can be traced to a file, revision or test result.
10. Never silently omit mandatory requirements or security-critical evidence just to meet a token budget.

## Token accounting

Measure context size using the target model's tokenizer when available. Otherwise label estimates clearly.

Compare full-file retrieval with targeted retrieval on the same tasks.

## Acceptance criteria

Demonstrate that targeted retrieval reduces input size on suitable tasks while preserving the context needed to solve them.

Include tests for stale Git revisions, missing files, large files and retrieval-budget exhaustion.

Do not introduce embeddings or a vector database unless the benchmark demonstrates a need.