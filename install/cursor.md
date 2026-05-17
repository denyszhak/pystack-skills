# Install for Cursor

Cursor reads rules from `.cursor/rules/*.mdc`. Each rule's frontmatter supports `description`, `globs` (file patterns), and `alwaysApply` (boolean).

The canonical `SKILL.md` files have `name` + `description`. Cursor ignores `name` and uses the file name as the rule identifier; `description` is read as-is. `globs` and `alwaysApply` are Cursor-only and can be added after install.

## Install

From inside your project:

```bash
/path/to/pystack-skills/install.sh cursor
```

Or manually:

```bash
cd <your-project>
mkdir -p .cursor/rules
for d in /path/to/pystack-skills/skills/*/; do
  name=$(basename "$d")
  cp "$d/SKILL.md" ".cursor/rules/${name}.mdc"
done
```

## Adding Cursor-specific fields

For app-context skills, add `globs` so Cursor only loads them when relevant files are open:

```yaml
---
description: ...
globs:
  - "app/services/**/*.py"
  - "app/repos/**/*.py"
alwaysApply: false
---
```

For broad-trigger skills (Tier 1), restrict to Python files:

```yaml
---
description: ...
globs:
  - "**/*.py"
alwaysApply: false
---
```

For an "always-on" rule (use sparingly — context cost):

```yaml
---
description: ...
alwaysApply: true
---
```

## Recommended `globs` per skill

| Skill | Suggested globs |
|---|---|
| `python-typing-idioms` | `**/*.py` |
| `python-value-objects` | `**/*.py` |
| `python-stdlib-idioms` | `**/*.py` |
| `python-antipatterns-cheatsheet` | `**/*.py` |
| `python-fastapi-sa-app-setup` | `app/setup.py`, `app/config.py`, `app/db/**`, `app/api/**`, `app/deps/**`, `app/common/**` |
| `python-aggregate-and-repo` | `app/models/**`, `app/repos/**` |
| `python-service-and-schema-cohesion` | `app/services/**`, `app/schemas/**` |
| `python-external-client` | `app/clients/**`, `tests/doubles/**` |
| `python-structlog-logging` | `app/common/logging.py`, `app/api/middleware/**` |
| `python-test-pyramid` | `tests/**` |
| `python-pure-domain-layer` | `app/domain/**` (file must exist) |
| `python-message-bus-outbox` | `app/events/**`, `app/outbox/**` (file must exist) |

## Disabling a skill

Remove or rename:

```bash
rm .cursor/rules/python-pure-domain-layer.mdc
```

## Updating

After `git pull` in this repo, re-run:

```bash
/path/to/pystack-skills/install.sh cursor
```

The install script overwrites files. Any `globs` / `alwaysApply` you hand-added will be lost on update — keep your customizations in a separate file or accept that you'll re-apply them.
