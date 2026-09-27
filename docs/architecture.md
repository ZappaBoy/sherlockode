# Architecture

## Package layout

```text
src/sherlockode/
├── cli.py                 Typer CLI (ask, repos, groups, sync, config, investigations)
├── app.py                 Composition root: wires settings, providers, workspace, git, sandbox
├── config/                Pydantic settings: TOML + .env + environment, config section models
├── domain/                Provider-independent models: repositories, commits, work items, evidence
├── git/                   Async git CLI client, hardened against repository-provided hooks/helpers
├── providers/             Provider base + capability mixins, GitHub, GitLab, generic Git, registry, MCP
├── catalog/               Repository catalog: explicit + discovered repos, include/exclude, groups, scope
├── workspace/             On-disk layout and checkout management
├── analysis/              Deterministic, read-only analyzers (languages, python_versions, dependencies)
├── sandbox/               Execution sandbox: Docker (default) and local (development only)
├── agent/                 PydanticAI agents, instructions, dependencies and toolsets
└── investigation/         Lifecycle service, recorder (trace + evidence ledger), models, rendering
```

## Investigation lifecycle

```text
question ─► scope resolution ─► planner agent ─► investigator agent ─► validated answer ─► report
               (catalog)        (InvestigationPlan)   (tools, evidence)    (output validator)   (persisted)
```

1. **Scope.** `--scope` or `agent.default_scope` is expanded by the catalog into repositories. This is a
   hard boundary: tools refuse repositories outside it.
2. **Plan.** A planner agent with catalog tools only produces an `InvestigationPlan`: objective, scope,
   hypotheses, steps and the data sources each step needs. It can be disabled (`agent.planning`,
   `--no-plan`) for cheap questions.
3. **Investigate.** The investigator receives the question and the plan and iterates freely over the
   toolsets. Every tool call goes through `RecordingToolset`, which records a step and converts
   operational errors (git failures, HTTP errors, missing files) into `ToolFailed` so the model adapts
   instead of the run crashing.
4. **Validate.** The output validator rejects findings that cite unknown evidence ids, and observed or
   computed findings without evidence; the model is asked to fix them.
5. **Persist.** `workspace/investigations/<date>-<seq>/` holds `manifest.json` (question, scope, model,
   version, usage, redacted configuration, status), `plan.json`, `steps.jsonl`, `evidence.json`,
   `sandbox/<run>/` (scripts and outputs), `report.json` and `report.md`.

Usage limits (`limits.max_agent_requests`, `limits.max_tool_calls`) are shared by planner and
investigator.

## Evidence model

`Evidence` = kind + statement + source + optional excerpt, with an id (`E0001`) and the id of the step
that produced it (`S0001`).

- **kind**: `observed` (read directly), `computed` (derived deterministically), `inferred` (agent
  judgement).
- **source**: `file` (repository, path, line, commit), `git` (command), `provider_api` (provider,
  endpoint), `command` (sandbox run), `analyzer`, `agent`.

Tools return `Observation[T]` (single repository) or `list[RepositoryResult[T]]` (fan-out, with
per-repository errors isolated), each carrying an evidence id. Analyzers additionally record one
evidence item per finding with file and line. `record_evidence` lets the agent cite a specific line or
record an inference derived from other evidence ids.

## Providers

`Provider` is the base; optional capabilities are ABC mixins, so a provider declares exactly what it
supports (interface segregation) and `Provider.capabilities` is derived by `isinstance`:

| Capability        | Mixin                      | GitHub | GitLab | Git |
|-------------------|----------------------------|:------:|:------:|:---:|
| discovery         | `RepositoryDiscovery`      | ✓ | ✓ |   |
| metadata          | `RepositoryMetadataSource` | ✓ | ✓ |   |
| contributors      | `ContributorSource`        | ✓ | ✓ |   |
| change requests   | `ChangeRequestSource`      | ✓ | ✓ |   |
| issues            | `IssueSource`              | ✓ | ✓ |   |
| namespaces        | `NamespaceSource`          | ✓ | ✓ |   |
| raw read-only API | `RawApiAccess`             | ✓ | ✓ |   |

Everything Git itself can answer (history, branches, tags, contents, contributors by commits) is
served by `GitClient` for every provider.

Adding a provider (e.g. Gitea): implement a `HostedProvider` subclass with the relevant mixins, then
`registry.register("gitea", GiteaProvider)` and pass the registry to `Application.open`. Configuration
uses `kind = "gitea"`. The agent and toolsets are unchanged.

Repositories are routed to providers by explicit `provider`, else by URL host (`hosts`, or the host of
`base_url`, or the public host), else to the generic `git` provider. Clone credentials are supplied by
the provider and passed to git via `GIT_CONFIG_*` environment variables, never on the command line or in
remote URLs.

### Native tools vs MCP

`providers.<name>.integration` decides how provider APIs reach the agent:

- `native` — the platform's typed `provider_*` tools. Predictable schemas, evidence recorded per call,
  works offline from MCP availability, and the same tools across providers.
- `mcp` — the provider's official MCP server (`MCPToolset`, prefixed `<name>_mcp_`), over stdio or
  streamable HTTP; the provider token is injected as an env var or bearer header. Broadest API coverage,
  maintained upstream. `allowed_tools` restricts it, which is strongly recommended to keep it read-only.
- `both` — both are exposed; native tools remain the default path.

Repository discovery for the catalog always uses the native client, since it happens outside the agent.
MCP tool calls are recorded as steps like any other tool.

## Configuration

`Settings` (pydantic-settings) with sources in precedence order: init arguments, environment variables
(`REPO_AGENT_` prefix, `__` nested delimiter), `.env`, TOML, defaults. Provider tokens also accept
`REPO_AGENT_<PROVIDER>_TOKEN`. Secrets are `SecretStr` and are redacted in `sherlockode config` and in
investigation manifests. Unknown keys in config sections are rejected (`extra="forbid"`) to catch typos.

## Security boundaries

- **Git.** `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `protocol.ext.allow=never`,
  `credential.helper=""`, no submodule recursion, `GIT_TERMINAL_PROMPT=0`, host `GIT_*` variables
  scrubbed. Git operations only read repository data; no repository code runs in the application.
- **Analyzers** read files (size-capped, symlinks skipped) and never execute them.
- **File access** from tools is confined to the checkout; `read_file` rejects paths resolving outside it.
- **Provider raw API** accepts only relative paths, so tokens cannot be sent to other hosts.
- **Sandbox (docker backend).** One container per execution, removed afterwards: `--network none`,
  `--read-only` root filesystem, repository mounted read-only, only the run directory writable,
  `--cap-drop ALL`, `no-new-privileges`, non-root user, CPU/memory/PID limits, an in-container
  `timeout -s KILL` plus an outer timeout, explicit environment passthrough only. `sandbox.runtime`
  selects gVisor (`runsc`) or similar for kernel-level isolation.
- **Docker-out-of-Docker.** When the application runs in a container it starts sandboxes through the
  host daemon; `sandbox.host_workspace` maps workspace paths to host paths for bind mounts. Access to the
  Docker socket is root-equivalent on the host: prefer rootless Docker, a remote Docker host
  (`DOCKER_HOST`), or a dedicated sandbox VM in production.
- **Sandbox (local backend).** Development fallback: `prlimit` CPU and memory limits and a scrubbed
  environment, but no filesystem or network isolation. It logs a warning and the agent is told it is
  unisolated.
- **Disabling execution.** `sandbox.enabled = false` removes `run_in_sandbox` from the agent entirely.

## Extension points

| Extend            | How |
|-------------------|-----|
| Git provider      | `HostedProvider`/`Provider` subclass + capability mixins, register in `ProviderRegistry` |
| Provider via MCP  | `integration = "mcp"` + `[providers.<name>.mcp]`, no code |
| Analyzer          | `Analyzer` subclass, add to `AnalyzerRegistry` |
| Agent tools       | a `FunctionToolset[InvestigationDeps]`, added in `build_toolsets` |
| Sandbox backend   | `Sandbox` subclass implementing `_run`, selected in `build_sandbox` |
| Model             | any PydanticAI model string in `agent.model` / `agent.planner_model` |
