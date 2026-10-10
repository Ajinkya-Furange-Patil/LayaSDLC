Implement Stage 1 of LayaSDLC: repository reconnaissance and project foundation.

## Objective

Determine the actual development environment, verify the available Laya and OpenCode interfaces, and create a minimal, testable architecture without implementing agent orchestration yet.

## Step 1: Inspect

Report:
- Operating system and relevant runtime versions.
- Whether OpenCode is installed and how it is configured.
- Whether the Laya repository, package, model weights or inference runtime are available.
- The official Laya installation and inference methods supported by the current version.
- Whether Laya runs locally in this environment and what resources it requires.
- Existing files, Git status and any current project structure.

Do not print secrets or environment variable values.

## Step 2: Define the minimum architecture

Use TypeScript for the OpenCode integration boundary and Python for the decision-service boundary if both are practical in the verified environment.

Keep the following responsibilities separate:
- Decision engine interface.
- Decision-service adapter.
- Workflow controller.
- Task state and evidence models.
- Logging and metrics.

Do not install every planned dependency yet. Choose only what is necessary for the initial working foundation.

## Step 3: Create the foundation

Create a small repository structure with:
- README and setup instructions.
- Architecture decisions document.
- Environment configuration example without secrets.
- Typed task and decision contracts.
- Basic health check for the decision service.
- Unit-test configuration.
- .gitignore and dependency manifests.

Do not implement real Laya inference, autonomous coding, database persistence, a frontend or multi-agent orchestration in this stage.

## Acceptance criteria

- The repository's original files remain intact.
- Setup instructions match the actual environment.
- The contracts can be imported or compiled.
- Basic tests pass.
- The decision engine can be replaced without rewriting the controller.
- The README identifies verified capabilities separately from planned features.

Finish with a concise report and wait for Stage 2.