Implement Stage 8: reproducible evaluation of LayaSDLC.

## Objective

Determine whether Laya-based decision-making and context optimization improve the efficiency of agentic software development without reducing verified task success.

## Compare three configurations

A. Baseline: standard coding-agent workflow.

B. Optimized baseline: deterministic routing, compact context and persistent state.

C. LayaSDLC: the same optimizations plus Laya-based bounded decisions.

Keep the coding model, task set, repository snapshots and verification criteria comparable.

## Metrics

Record:
- Total input tokens.
- Total output tokens.
- Decision-model tokens or inference cost, when applicable.
- Coding-model tokens and cost.
- Total measured inference cost.
- Wall-clock latency.
- Verified task completion rate.
- Test pass rate and regressions.
- Routing accuracy.
- Number of model calls and retries.
- Fallback and escalation rates.

Separate measured values from estimates. Include failed tasks and incomplete runs rather than silently excluding them.

## Evaluation methodology

1. Build a fixed set of representative software tasks.
2. Record a baseline for each task.
3. Run each configuration under comparable conditions.
4. Repeat selected tasks to estimate variability.
5. Report aggregate results and per-task differences.
6. Document limitations, failures and possible confounding factors.
7. Calculate token reduction and verified success-rate differences.
8. Do not claim a causal improvement when the experiment does not support it.

## Deliverables

Create a reproducible benchmark script, machine-readable results, a comparison report and a small summary dashboard or CLI report.

The project is complete only when the results can be reproduced from documented instructions.