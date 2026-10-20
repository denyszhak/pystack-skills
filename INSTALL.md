# Installing PyStack

PyStack skills are plain [Agent Skills](https://agentskills.io/specification): one directory per skill with a `SKILL.md`. Every major coding agent now loads that format natively, so installing means putting the skill directories where your agent looks. No conversion to rules files or `AGENTS.md`.

## Where agents look

| Agent | Project | User |
|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.agents/skills/` | `~/.agents/skills/` (`~/.codex/skills/` is deprecated) |
| Cursor | `.agents/skills/`, `.cursor/skills/`, also `.claude/skills/` | `~/.agents/skills/`, `~/.cursor/skills/`, also `~/.claude/skills/` |
| OpenCode | `.opencode/skills/`, `.agents/skills/`, also `.claude/skills/` | `~/.config/opencode/skills/`, `~/.agents/skills/`, also `~/.claude/skills/` |
| GitHub Copilot / VS Code | `.github/skills/`, `.agents/skills/`, also `.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` |

`.agents/skills/` is the shared cross-agent location. Claude Code is the exception: it reads only `.claude/skills/`.

## Option 1 — `npx skills` (any agent)

The [`skills`](https://github.com/vercel-labs/skills) CLI finds the skills in this repo, asks which agents you use, and links them into the right directories. It needs Node.js.

```bash
npx skills add denyszhak/pystack-skills
```

Useful flags: `--skill <name>` (repeatable) to pick skills, `-a <agent>` (e.g. `claude-code`, `codex`, `cursor`, `opencode`, `github-copilot`) to pick agents, `-g` to install for your user instead of the project, `-l` to list without installing.

```bash
npx skills add denyszhak/pystack-skills -a claude-code -a codex \
  --skill python-aggregate-and-repo --skill python-service-and-schema-cohesion
```

## Option 2 — Claude Code plugin

This repo is a Claude Code plugin marketplace. Each tier is its own plugin, so you install the tiers you want:

```text
/plugin marketplace add denyszhak/pystack-skills
/plugin install pystack-service@pystack-skills
/plugin install pystack-python@pystack-skills
/plugin install pystack-opt-in@pystack-skills
```

Or from a shell: `claude plugin marketplace add denyszhak/pystack-skills`, then `claude plugin install pystack-service@pystack-skills`.

Plugin skills are namespaced by plugin, e.g. `/pystack-service:python-test-pyramid`. Update with `claude plugin update pystack-service@pystack-skills`. Don't also install the same skills into `~/.claude/skills/` — Claude Code would load each one twice.

## Option 3 — `install.sh` (no Node, symlinks from a clone)

```bash
git clone https://github.com/denyszhak/pystack-skills
cd pystack-skills

./install.sh claude                      # every skill → ~/.claude/skills
./install.sh agents                      # every skill → ~/.agents/skills (Codex, Cursor, OpenCode, Copilot, ...)
./install.sh claude --project service    # service tier → ./.claude/skills of the current directory
./install.sh agents python-typing-idioms python-value-objects
./install.sh --list                      # skills and their tiers
```

Each skill is symlinked on its own, so `git pull` in the clone updates installed skills, and your other skills in the same directory are left alone. `--copy` copies instead (re-run with `--force` to update a copy). `--uninstall` removes the selected skills.

## Picking a subset

| Tier | Plugin | Skills | Install when |
|---|---|---|---|
| `python` | `pystack-python` | typing-idioms, value-objects, stdlib-idioms, antipatterns-cheatsheet | Any typed Python 3.12+ project |
| `service` | `pystack-service` | fastapi-sa-app-setup, aggregate-and-repo, service-and-schema-cohesion, external-client, structlog-logging, test-pyramid | FastAPI + SQLAlchemy + Postgres services |
| `opt-in` | `pystack-opt-in` | pure-domain-layer, message-bus-outbox | You have `app/domain/`, or the service is event-driven |

A typical service installs `python` + `service`. Tier names work as selectors for `install.sh`.

## Avoiding duplicates

Cursor, OpenCode, and Copilot read `.claude/skills/` *and* `.agents/skills/`. If you install into both, those agents may list every skill twice.

- **Claude Code only:** install to `claude` (or use the plugin).
- **Claude Code + Cursor / OpenCode / Copilot:** install to `claude` only — the others read `.claude/skills/` too.
- **Claude Code + Codex:** install to both `claude` and `agents`; Codex doesn't read `.claude/skills/`.
- **No Claude Code:** install to `agents` only.

## Upgrading from the old installer

Earlier versions of `install.sh` converted skills into other formats. Clean those up:

| Old command | What it left behind | Clean up |
|---|---|---|
| `install.sh claude-code` | `~/.claude/skills` as one symlink to this repo's `skills/` | `rm ~/.claude/skills` (removes only the link), then `./install.sh claude` |
| `install.sh claude-code project` | `.claude/skills` as one symlink | `rm .claude/skills`, then `./install.sh claude --project` |
| `install.sh codex` | A generated `AGENTS.md` with every skill concatenated | Delete the generated sections (or the file), then `./install.sh agents` |
| `install.sh cursor` | `.cursor/rules/python-*.mdc` | `rm .cursor/rules/python-*.mdc`, then `./install.sh agents --project` |
| `install.sh opencode` | `.opencode/rules/python-*.md` | `rm .opencode/rules/python-*.md`, then `./install.sh agents --project` |

The new `install.sh` refuses to write into a skills directory that is itself a symlink, so a leftover whole-directory link is caught rather than written through.

## Optional: scope skills to paths in Claude Code

Claude Code supports a `paths:` glob list in `SKILL.md` frontmatter that loads a skill only when you're working with matching files. PyStack doesn't ship it — `paths` is Claude Code-only (claude.ai and the Skills API reject frontmatter keys outside the spec), and a scaffolding task often runs before the matching files exist. If you want it in a fork, add it to the service-tier skills, e.g. `paths: ["app/models/**", "app/repos/**"]` for `python-aggregate-and-repo`.
