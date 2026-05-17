# Install for Codex (OpenAI CLI)

Codex doesn't have a per-skill activation system. It reads project-level instructions from `AGENTS.md` at the repo root. The install step concatenates all skill bodies (stripping YAML frontmatter) into a single `AGENTS.md`.

## Generate `AGENTS.md`

From inside your project:

```bash
/path/to/pystack-skills/install.sh codex
```

This writes `./AGENTS.md`. You can pass a different output path:

```bash
/path/to/pystack-skills/install.sh codex docs/CONVENTIONS.md
```

## Manual version (if you don't want to use the script)

```bash
{
  echo "# Python opinionated conventions"
  echo
  echo "These conventions apply to all Python code in this repo."
  echo
  for f in /path/to/skills/*/SKILL.md; do
    name=$(basename "$(dirname "$f")")
    echo "## $name"
    awk '/^---$/{c++; next} c>=2' "$f"
    echo
  done
} > AGENTS.md
```

## Trade-off

Codex puts the *entire* `AGENTS.md` into context for every prompt. With all 15 skills concatenated, that's a lot of context cost compared to Claude Code's per-skill activation.

**Recommendation: install only the skills relevant to your project.** For a typical FastAPI + SA app, that's:

- All Tier 1 (broad) skills — they apply to all Python
- All Tier 2 (app-context) skills — your app needs them
- Skip Tier 3 (opt-in) unless you're using those patterns

To install a subset, edit your generated `AGENTS.md` to remove sections you don't need, or generate from a subset:

```bash
{
  echo "# Python opinionated conventions"
  for skill in python-typing-idioms python-value-objects python-aggregate-and-repo python-service-and-schema-cohesion; do
    echo "## $skill"
    awk '/^---$/{c++; next} c>=2' "/path/to/skills/$skill/SKILL.md"
    echo
  done
} > AGENTS.md
```

## Updating

After `git pull` in this repo, regenerate `AGENTS.md`:

```bash
/path/to/pystack-skills/install.sh codex
```
