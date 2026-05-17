# PyStack

Opinionated agent skills for typed Python backend services.

PyStack is a repo-owned skill set for AI coding agents such as Claude Code, Codex, OpenCode, and Cursor. It encodes one practical backend shape for a common modern Python service stack so agents, reviewers, and teams know what kind of code to expect.

If your style differs, install the subset that matches yours and skip the rest.

## Why This Exists

Style guides are written for humans. AI coding agents need smaller, triggerable rules that load only when relevant: how repos behave, where transactions live, when Pydantic is allowed, how external clients retry, and what tests should prove.

Generic prompts like "follow DDD" or "use clean architecture" help a little, but they leave too much room for agents to drift. In real codebases that drift shows up as repos committing their own transactions, routes growing business logic, services becoming god classes, Pydantic leaking into persistence, SQLAlchemy tests using mocks, and retries duplicating side effects.

PyStack turns team taste into repo-owned, reviewable guidance. The goal is not to make every prompt longer. The goal is to define the relationships between the pieces once so agents can do better work without every request restating the architecture.

The useful part is that this guidance is yours. Fork it, delete what you disagree with, rewrite the trade-offs, add your own examples, and keep the resulting agent behavior visible in the same place as the code it shapes.

## Architecture Stance

PyStack is pragmatic tactical DDD for one Python backend service.

- SQLAlchemy models carry aggregate behavior by default.
- Pydantic stays at boundaries: API schemas, commands, responses, config, and external payloads.
- Repositories load and save aggregates; they do not own transactions.
- Top-level application services own write transactions with `async with session.begin()`.
- Pure domain classes are opt-in for invariant-dense systems where mapper cost pays back.
- Domain services and policies are extraction tools, not a mandatory layer.
- External systems are wrapped in clients with explicit retry/error behavior.
- Tests use real Postgres for persistence and purpose-built doubles for external systems.
- Protocols/interfaces are added when they earn their keep, not for every repo/client by default.

The influences are [Cosmic Python](https://www.cosmicpython.com/), [Python Patterns](https://python-patterns.guide/), Evans-style DDD, Fowler's writing on [testing](https://martinfowler.com/testing/) and [mocks vs stubs](https://martinfowler.com/articles/mocksArentStubs.html), plus the official docs for [Python](https://docs.python.org/3/), [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), and [SQLAlchemy](https://docs.sqlalchemy.org/).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the locked decisions and trade-offs.

## DDD Mapping

Strategic DDD concepts like context maps and upstream/downstream relationships matter when designing multiple services or team boundaries. Inside one service, the useful surface is usually tactical: aggregates, value objects, repositories, application services, invariants, events, transactions, and adapters.

| Traditional concept | PyStack representation | Notes |
|---|---|---|
| Entity | SQLAlchemy model with identity and lifecycle in `app/models/` | The default domain object is the SA model. |
| Value Object | Frozen dataclass or `NewType` | Use for `Money`, `EmailAddress`, IDs, and other invariant-bearing values. |
| Aggregate | One SA model root plus owned child entities | Methods enforce invariants and state transitions. |
| Aggregate Root | One model file and one repo file per root | Children like `OrderLine` live with `Order`; external code mutates through the root. |
| Repository | `app/repos/<aggregate>.py` | Repos use `AsyncSession`; they do not `commit()` or `begin()`. |
| Unit of Work | `AsyncSession` | A custom UoW is optional only when it owns extra behavior such as outbox/event collection. |
| Application Service | `app/services/<use_case_area>.py` | Orchestrates repos, clients, transactions, outbox writes, and returns Pydantic schemas. |
| Domain Service / Policy | Small sync function or frozen dataclass | Extract only when a pure business decision spans multiple objects or would create a god service. |
| Factory | `@classmethod new/from_X` or schema `to_X` method | Separate factory classes are discouraged unless construction has real state or dependencies. |
| Domain Event | Frozen dataclass in `app/events/` | Opt-in with `python-message-bus-outbox`; events are past-tense facts like `OrderPlaced`. |
| Message Bus | `app/common/message_bus.py` plus handlers | Opt-in for local decoupling or event-driven services. |
| Outbox | `app/outbox/` table and dispatcher | Opt-in for at-least-once cross-process delivery after DB commit. |
| Anti-Corruption Layer | External clients + schemas | Third-party payloads are translated at client/schema boundaries. |
| Port | Concrete repo/client by default; `Protocol` only when useful | Add a port when there are multiple implementations or a real substitution boundary. |
| Adapter | `app/api/`, `app/consumers/`, `app/repos/`, `app/clients/`, `app/outbox/` | Uses conventional FastAPI names instead of academic `inbound/` / `outbound/` directories. |

## Skills

PyStack contains 12 skills across three activation tiers. The `description` field in each skill's frontmatter tells the agent when to load it.

| Tier | Skill | Purpose |
|---|---|---|
| Broad | `python-typing-idioms` | `Protocol`, `Self`, `NewType`, PEP 695, typed constructors |
| Broad | `python-value-objects` | Frozen dataclass value objects and ID types |
| Broad | `python-stdlib-idioms` | Generators, `itertools`, async iteration, tree composition |
| Broad | `python-antipatterns-cheatsheet` | Singleton and Factory redirects for Python |
| App | `python-fastapi-sa-app-setup` | App layout, config, lifespan, deps, middleware, exception handlers |
| App | `python-aggregate-and-repo` | SQLAlchemy model with behavior, aggregate boundaries, repositories |
| App | `python-service-and-schema-cohesion` | Application services, commands, schemas, transaction ownership |
| App | `python-external-client` | HTTP clients, retry policy, error mapping, fake transports |
| App | `python-structlog-logging` | Structlog setup and request correlation |
| App | `python-test-pyramid` | Real Postgres tests, API tests, external doubles |
| Opt-in | `python-pure-domain-layer` | Separate pure domain classes when invariants justify mapper cost |
| Opt-in | `python-message-bus-outbox` | Domain events, in-process bus, outbox, idempotent handlers |

## Install

Each tool has its own conventions. Pick yours:

| Tool | Doc |
|---|---|
| Claude Code | [install/claude-code.md](install/claude-code.md) |
| Codex | [install/codex.md](install/codex.md) |
| OpenCode | [install/opencode.md](install/opencode.md) |
| Cursor | [install/cursor.md](install/cursor.md) |

Quick start:

```bash
git clone https://github.com/denyszhak/pystack-skills
cd pystack-skills

./install.sh claude-code             # user-level: ~/.claude/skills
./install.sh claude-code project     # project-level: ./.claude/skills
./install.sh codex                   # generates ./AGENTS.md
./install.sh opencode                # copies to ./.opencode/rules/
./install.sh cursor                  # copies to ./.cursor/rules/
```

## Skill Format

Each skill is a directory under `skills/` with a `SKILL.md` at its root:

```text
skills/python-typing-idioms/
  SKILL.md            # YAML frontmatter + markdown body
  examples/           # runnable Python examples (optional)
  reference/          # supplementary docs (optional)
```

The frontmatter is universal. Every tool either consumes it or ignores it:

```yaml
---
name: python-typing-idioms
description: |
  Use when ... Triggers ... Encodes ...
  Do NOT use for: ...
---
```

Tool-specific fields can be added at install time. See each tool's install doc.

## Target Stack

PyStack is not a framework, starter template, or claim about all Python. It is versioned guidance for this service stack:

| Layer | Choice |
|---|---|
| HTTP API | FastAPI |
| Schemas and settings | Pydantic v2 |
| Persistence | SQLAlchemy 2.0 async |
| Database | PostgreSQL |
| Tests | pytest, real Postgres, protocol-level external doubles |
| Clients and logging | httpx, structlog |
| Tooling | uv, ruff, ty |

## License

MIT. See [LICENSE](LICENSE).
