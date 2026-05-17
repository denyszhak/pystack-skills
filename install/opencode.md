# Install for OpenCode

OpenCode (sst/opencode) reads rules from a project-level config directory. The format and exact path may evolve — verify against current OpenCode docs.

As of writing (early 2026), rules live in `.opencode/rules/*.md`. OpenCode supports `name` + `description` frontmatter similar to Claude Code, so no transformation is needed beyond copying the `SKILL.md` files.

## Install

From inside your project:

```bash
/path/to/pystack-skills/install.sh opencode
```

Or manually:

```bash
cd <your-project>
mkdir -p .opencode/rules
for d in /path/to/pystack-skills/skills/*/; do
  name=$(basename "$d")
  cp "$d/SKILL.md" ".opencode/rules/$name.md"
done
```

## Per-project only

Unlike Claude Code, OpenCode's rules are project-scoped. There's no user-level rules directory. If you want the same rules across all your projects, run install in each.

## Disabling a skill

Remove the file:

```bash
rm .opencode/rules/python-pure-domain-layer.md
```

## Updating

After `git pull` in this repo, re-copy:

```bash
/path/to/pystack-skills/install.sh opencode
```

This overwrites existing files but won't remove ones whose names changed. If a skill is renamed upstream, manually delete the old file.
