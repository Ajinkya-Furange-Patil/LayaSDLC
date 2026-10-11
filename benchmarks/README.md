# Real-Provider Benchmark

This directory contains the real-provider benchmarking infrastructure for
LayaSDLC. Unlike the offline benchmark (`python -m layasdlc.benchmark`), this
harness collects **actual usage metadata** from the configured provider.

**Status: IMPLEMENTED, LIVE VALIDATION PENDING.** The runner is complete but
requires a provider API key to produce measured results. Without credentials,
only the offline benchmark can run.

---

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| `LAYA_API_KEY` | Provider authentication (if required by endpoint) |
| `LAYA_BASE_URL` | Endpoint URL |
| `OPENAI_API_KEY` or equivalent | For coding-model calls (if using a real coding adapter) |
| `pip install tiktoken` | For accurate token counting (optional but recommended) |

---

## Quickstart

```bash
# Run with real providers (requires API keys)
export LAYA_API_KEY="your-key"
export LAYA_BASE_URL="https://laya.inference.zaitlabs.com"
python -m layasdlc.benchmark_real run --config layasdlc --repeat 3

# Generate report from saved results
python -m layasdlc.benchmark_real report --results results.json
```

---

## Configuration

Create a benchmark configuration file:

```json
{
  "name": "layasdlc",
  "enabled": true,
  "decision_engine": "laya_http",
  "coding_adapter": "openai",
  "model": "gpt-4o",
  "max_retries": 3,
  "timeout_s": 30
}
```

---

## Methodology

1. **Fixed task set**: 8 representative tasks (bug fixes, features, refactoring,
   testing, documentation, investigation).
2. **Three configurations**: baseline (no optimizations), optimized baseline
   (routing + context + persistence), LayaSDLC (all + Laya decisions).
3. **Repeated trials**: `--repeat N` runs each task N times per configuration.
4. **Order balancing**: Tasks are shuffled per repeat to reduce ordering bias.
5. **Usage collection**: Every model call records input_tokens, output_tokens,
   model, provider, and latency from the provider's response metadata.

---

## Metrics Collected

| Metric | Source | Measured/Estimated |
|--------|--------|-------------------|
| Input tokens | Provider `usage.prompt_tokens` | **Measured** |
| Output tokens | Provider `usage.completion_tokens` | **Measured** |
| Total tokens | Sum of above | **Measured** |
| Model name | Provider response | **Measured** |
| Latency | Wall-clock around API call | **Measured** |
| Cost | Tokens × provider pricing | **Calculated** |
| Task completion | Acceptance test result | **Measured** |
| Test pass rate | Verification command exit code | **Measured** |

---

## Output

Results are saved as JSON:

```json
{
  "metadata": {
    "timestamp": "2026-01-16T12:00:00Z",
    "configurations": ["baseline", "optimized_baseline", "layasdlc"],
    "tasks": 8,
    "repeats": 3,
    "total_runs": 72
  },
  "runs": [
    {
      "configuration": "layasdlc",
      "task_id": "B-1",
      "input_tokens": 1250,
      "output_tokens": 340,
      "total_tokens": 1590,
      "model": "gpt-4o",
      "latency_ms": 2340,
      "cost_usd": 0.023,
      "completed": true,
      "test_passed": true,
      "measured": true
    }
  ],
  "summary": {
    "baseline": {"mean_tokens": 2100, "cost_usd": 0.031},
    "layasdlc": {"mean_tokens": 1590, "cost_usd": 0.023},
    "savings_percent": 24.3,
    "net_tokens_saved": 510
  }
}
```

---

## Interpreting Results

- **`measured: true`** — every number came from provider usage metadata.
- **`measured: false`** — token counts are estimates; label them as such.
- **Savings** are computed only across successful, quality-equivalent runs.
- **Failed runs** are included in aggregate counts, never silently dropped.

---

## Reproducibility

```bash
# Full run
python -m layasdlc.benchmark_real run \
  --config layasdlc \
  --repeat 3 \
  --output results-$(date +%Y%m%d-%H%M%S).json

# Report
python -m layasdlc.benchmark_real report --results results.json
```

---

## Limitations

- Requires API keys for both the decision provider and the coding provider.
- Token counts depend on the provider's tokenizer; different providers may count
  differently.
- Cost calculations use published pricing and may not reflect actual billing.
- Latency includes network overhead; results vary by region and load.
- A single run is not statistically significant; use `--repeat` for variability.
