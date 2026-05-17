# PyStack

Opinionated agent skills for typed Python backend services.

PyStack is a repo-owned skill set for AI coding agents (Claude Code, Codex, OpenCode, Cursor) working on modern Python backend services.

The chosen stack is the mainstream modern Python service stack this repo targets. It is not every Python backend, but it is a common default for new typed HTTP services:

- **FastAPI** for HTTP APIs and dependency injection
- **Pydantic v2** for API schemas, commands, settings, and external payloads
- **SQLAlchemy 2.0 async** for persistence
- **PostgreSQL** for the database
- **pytest** for tests, with real Postgres and protocol-level external doubles
- **httpx**, **structlog**, **uv**, **ruff**, and **ty** for clients, logging, packaging, linting, and type checking

These are not "the only true way." If your style differs, install the subset that matches yours and skip the rest.

## What's in the box

12 skills across three activation tiers. The `description` field in each skill's frontmatter tells the agent when to load it.

### Tier 1 — Broad triggers (fire across most Python work)

1. `python-typing-idioms` — `Protocol`, `Self`, `NewType`, PEP 695, alternative constructors via `@classmethod`
2. `python-value-objects` — frozen dataclasses with `slots` / `kw_only` for domain primitives
3. `python-stdlib-idioms` — iteration (generators, `itertools`) + tree composition (`Protocol` + dataclass)
4. `python-antipatterns-cheatsheet` — Singleton / Factory redirects

### Tier 2 — App-context triggered (FastAPI + SA project signals)

5. `python-fastapi-sa-app-setup` — layout, `AppConfig`, lifespan, middleware, exception handlers
6. `python-aggregate-and-repo` — SA model with behavior + repository
7. `python-service-and-schema-cohesion` — service classes, Pydantic schemas with `from_X` / `to_X` methods
8. `python-external-client` — `BaseHTTPClient` with tenacity, `httpx.MockTransport` tests
9. `python-structlog-logging` — structlog setup with `contextvar` correlation_id
10. `python-test-pyramid` — real Postgres, session-scoped DB+app, `ASGITransport`

### Tier 3 — Opt-in (explicit signal)

11. `python-pure-domain-layer` — Cosmic Python separate `domain/` aggregate pattern
12. `python-message-bus-outbox` — in-process events, outbox, idempotency

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the philosophy and locked decisions.

## Install

Each tool has its own conventions. Pick yours:

| Tool | Doc |
|---|---|
| Claude Code | [install/claude-code.md](install/claude-code.md) |
| Codex | [install/codex.md](install/codex.md) |
| OpenCode | [install/opencode.md](install/opencode.md) |
| Cursor | [install/cursor.md](install/cursor.md) |

### Quick start

```bash
git clone https://github.com/<you>/pystack-skills
cd pystack-skills

./install.sh claude-code             # user-level: ~/.claude/skills
./install.sh claude-code project     # project-level: ./.claude/skills
./install.sh codex                   # generates ./AGENTS.md
./install.sh opencode                # copies to ./.opencode/rules/
./install.sh cursor                  # copies to ./.cursor/rules/
```

## Skill format

Each skill is a directory under `skills/` with a `SKILL.md` at its root:

```
skills/python-typing-idioms/
  SKILL.md            # YAML frontmatter + markdown body
  examples/           # runnable Python examples (optional)
  reference/          # supplementary docs (optional)
```

The frontmatter is universal — every tool either consumes it or ignores it:

```yaml
---
name: python-typing-idioms
description: |
  Use when ... Triggers ... Encodes ...
  Do NOT use for: ...
---
```

Tool-specific fields (Cursor `globs`, etc.) can be added at install time. See each tool's install doc.

## What this is, in one paragraph

**Style guides are written for humans.** AI coding agents need skills that trigger contextually, fire when they're relevant, and stay quiet when they're not. This repo is one team's distilled answer for what good Python backend code looks like when an AI writes it — 12 skills covering a typed FastAPI + SQLAlchemy service end to end: app setup, repositories, services, external clients, structured logging, testing, plus the classic GoF anti-patterns Python doesn't need. Hexagonal-shaped but pragmatic: strict separation of inbound and outbound adapters, SQLAlchemy models carry behavior by default, pure domain is opt-in for invariant-dense systems, and top-level service methods own transaction boundaries with `AsyncSession.begin()`. **Provider-neutral by design** — install once, works with Claude Code, Codex, OpenCode, and Cursor. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the locked decisions and reasoning.

## Why this exists

Modern Python backend work sits between two worlds. On one side are academic architecture terms: DDD, hexagonal architecture, ports and adapters, repositories, unit of work, tactical patterns. On the other side is day-to-day service code: FastAPI dependencies, Pydantic schemas, SQLAlchemy sessions, retries, message queues, tests, and deployment constraints. This repo maps the useful parts of those ideas onto the way most Python services are actually built.

It is based on 8+ years of practical backend experience and heavily influenced by [Cosmic Python](https://www.cosmicpython.com/), [Python Patterns](https://python-patterns.guide/), Evans-style DDD, Fowler's writing on [testing](https://martinfowler.com/testing/) and [mocks vs stubs](https://martinfowler.com/articles/mocksArentStubs.html), and the official docs for [Python](https://docs.python.org/3/), [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), and [SQLAlchemy](https://docs.sqlalchemy.org/). The result is not academic DDD. It is tactical DDD shaped for one bounded context: a single Python backend service.

AI agents often produce plausible Python that slowly breaks a good codebase: repos start committing transactions, routes grow business logic, services become god classes, Pydantic leaks into persistence, tests mock ORM internals, and "follow DDD" leaves too much room for interpretation. These skills turn team taste into repo-owned, versioned, reviewable guidance so humans and agents know what shape to expect.

The goal is not to make agents care about plumbing forever. The goal is to specify the relationships between the pieces clearly enough that the agent can do good work without every request restating the architecture.

## DDD mapping

This repo focuses on **tactical DDD**. Strategic DDD concepts like context maps, upstream/downstream relationships, and subdomain classification matter when designing a multi-service system or team boundary. Inside one Python service, the useful surface is usually smaller: aggregates, value objects, repositories, application services, invariants, events, transactions, and adapters.

| Traditional concept | Repo representation | Notes |
|---|---|---|
| Entity | SQLAlchemy model with identity and lifecycle in `app/models/` | Default style: the SA model is the domain object for that aggregate. |
| Value Object | Frozen dataclass or `NewType` | Use for `Money`, `EmailAddress`, IDs, and other values with equality/invariants. Pydantic stays at I/O boundaries. |
| Aggregate | One SA model root plus owned child entities | Aggregate methods enforce invariants and state transitions. |
| Aggregate Root | One model file and one repo file per root | Children like `OrderLine` live with `Order`; external code mutates through the root. |
| Repository | `app/repos/<aggregate>.py` | Repos load/save aggregates through `AsyncSession`; they do not own transactions. |
| Unit of Work | `AsyncSession` by default | A custom UoW is optional only when it owns extra behavior such as outbox/event collection. |
| Application Service | `app/services/<use_case_area>.py` | Orchestrates repos, clients, transactions, outbox writes, and returns Pydantic schemas. |
| Domain Service / Policy | Small sync function or frozen dataclass, extracted only when justified | Use when a pure business decision spans multiple aggregates/value objects and would make the application service a god class. |
| Factory | `@classmethod new/from_X` or schema `to_X` method | Separate factory classes are discouraged unless construction has real state or dependencies. |
| Domain Event | Frozen dataclass in `app/events/` | Opt-in with `python-message-bus-outbox`; past-tense facts like `OrderPlaced`. |
| Message Bus | `app/common/message_bus.py` plus handlers | Opt-in for local decoupling or event-driven services. Direct calls are fine when there is one consumer and no reliability need. |
| Outbox | `app/outbox/` table and dispatcher | Opt-in for at-least-once cross-process delivery after DB commit. |
| Anti-Corruption Layer | External clients + schemas | External payloads are translated at client/schema boundaries; raw third-party shapes should not leak inward. |
| Port | Usually a concrete repo/client; `Protocol` only when it earns its keep | No interface for every repo/client by default. Add a port when there are multiple implementations or a real substitution boundary. |
| Adapter | `app/api/`, `app/consumers/`, `app/repos/`, `app/clients/`, `app/outbox/` | Uses conventional FastAPI names instead of academic `inbound/` / `outbound/` directories. |

## License

MIT. See [LICENSE](LICENSE).
