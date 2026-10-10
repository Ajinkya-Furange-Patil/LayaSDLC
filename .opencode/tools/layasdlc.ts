/**
 * LayaSDLC custom tools for OpenCode (Stage 5).
 *
 * Three tools are exported from this file, named after the file:
 *   layasdlc_route    — submit a task, get the next permitted action
 *   layasdlc_inspect  — show current state, history, evidence and facts
 *   layasdlc_approve  — settle a pending approval request
 *
 * All routing, safety and permission decisions happen in the Python backend.
 * The backend is invoked through a file-based bridge (JSON in, JSON out) so
 * user-supplied task text never reaches a shell command line.
 */

import { tool } from "@opencode-ai/plugin"
import { z } from "zod"
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "fs"
import { tmpdir } from "os"
import path from "path"

// ======================================================================================
// Bridge invocation
// ======================================================================================

/**
 * Locate the layasdlc package source relative to the worktree.
 *
 * Tries the known monorepo layout first, then a plain `src/` layout, then the
 * worktree root. Returns an empty string when the package cannot be found, in
 * which case the bridge will report the import error from Python.
 */
function findSrcDir(worktree: string): string {
  const candidates = [
    path.join(worktree, "services", "decision", "src"),
    path.join(worktree, "src"),
    worktree,
  ]
  for (const candidate of candidates) {
    if (existsSync(path.join(candidate, "layasdlc", "__init__.py"))) {
      return candidate
    }
  }
  return ""
}

/**
 * Invoke the Python bridge with a JSON payload and return its raw output.
 *
 * The payload is written to a temporary file and the result read back from
 * another, so no user input is ever interpolated into a shell command.
 */
async function runBridge(worktree: string, payload: unknown): Promise<string> {
  const srcDir = findSrcDir(worktree)
  const env: Record<string, string> = { ...(process.env as Record<string, string>) }
  if (srcDir) {
    env.PYTHONPATH =
      srcDir + (env.PYTHONPATH ? path.delimiter + env.PYTHONPATH : "")
  }

  const dir = mkdtempSync(path.join(tmpdir(), "layasdlc-"))
  const inputPath = path.join(dir, "input.json")
  const outputPath = path.join(dir, "output.json")
  writeFileSync(inputPath, JSON.stringify(payload), "utf-8")

  const proc = Bun.spawn(
    [
      "python", "-m", "layasdlc.opencode_bridge",
      "--input", inputPath, "--output", outputPath,
    ],
    { cwd: worktree, env, stdout: "pipe", stderr: "pipe" },
  )
  await proc.exited

  try {
    return readFileSync(outputPath, "utf-8").trim()
  } catch {
    return `LayaSDLC bridge failed (exit ${proc.exitCode})`
  }
}

// ======================================================================================
// Result formatting
// ======================================================================================

/**
 * Format a bridge result for the LLM. Route results become a short readable
 * summary; everything else passes through as pretty JSON.
 */
function formatResult(raw: string): string {
  try {
    const result = JSON.parse(raw)
    if (result.error) return `Error: ${result.error}`

    if (result.next_action) {
      const lines = [
        `Task: ${result.task_id}`,
        `Phase: ${result.phase}`,
        `Next action: ${result.next_action}`,
        `Reason: ${result.reason}`,
      ]
      if (result.rules?.length) lines.push(`Rules: ${result.rules.join(", ")}`)
      if (result.confidence != null) {
        lines.push(`Confidence: ${result.confidence}`)
      }
      if (result.error) lines.push(`Warning: ${result.error}`)
      if (result.unmet_conditions?.length) {
        lines.push(`Unmet: ${result.unmet_conditions.join(", ")}`)
      }
      return lines.join("\n")
    }

    if (result.task) {
      const header = [
        `Task: ${result.task.task_id}`,
        `Phase: ${result.task.phase}`,
        `Safety: ${result.task.safety_class}`,
        `Verification: ${result.task.verification}`,
        result.task.unmet_conditions?.length
          ? `Unmet: ${result.task.unmet_conditions.join(", ")}`
          : null,
      ].filter(Boolean).join("\n")
      return `${header}\n\n${JSON.stringify(result, null, 2)}`
    }

    return JSON.stringify(result, null, 2)
  } catch {
    return raw
  }
}

// ======================================================================================
// Tools
// ======================================================================================

const routeArgs = {
  task_id: z
    .string()
    .optional()
    .describe("Task identifier. Omit to create a new task."),
  subject: z
    .string()
    .optional()
    .describe("Short task title (required when creating a new task)."),
  body: z.string().optional().describe("Detailed description."),
  path: z.string().optional().describe("Relevant file path."),
  kind: z
    .enum([
      "bug_fix",
      "feature",
      "refactor",
      "testing",
      "documentation",
      "investigation",
    ])
    .optional()
    .describe("Task classification hint."),
}

export const route = tool({
  description:
    "Submit a task to the LayaSDLC workflow router and get the next permitted " +
    "action. Creates a persistent task record. Use this before making any " +
    "repository changes.",
  args: routeArgs,
  async execute(args, context) {
    const worktree = context.worktree || context.directory
    const raw = await runBridge(worktree, { action: "route", ...args })
    return formatResult(raw)
  },
})

export const inspect = tool({
  description:
    "Inspect a task's current state, history, evidence and context facts. " +
    "Use this to review progress before deciding next steps.",
  args: {
    task_id: z.string().describe("Task to inspect."),
  },
  async execute(args, context) {
    const worktree = context.worktree || context.directory
    const raw = await runBridge(worktree, { action: "inspect", ...args })
    return formatResult(raw)
  },
})

export const approve = tool({
  description:
    "Approve or deny a pending approval request for a high-risk task. " +
    "Use this when the router returns a request_approval action.",
  args: {
    task_id: z.string().describe("Task awaiting approval."),
    grant: z.boolean().describe("true to approve, false to deny."),
    reason: z.string().optional().describe("Reason for the decision."),
  },
  async execute(args, context) {
    const worktree = context.worktree || context.directory
    const raw = await runBridge(worktree, {
      action: args.grant ? "approve" : "deny",
      task_id: args.task_id,
      reason: args.reason,
    })
    return formatResult(raw)
  },
})
