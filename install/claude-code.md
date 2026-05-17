# Install for Claude Code

Claude Code reads skills from `~/.claude/skills/` (user-level) or `<project>/.claude/skills/` (project-level). Each skill is a directory containing a `SKILL.md` with YAML frontmatter; Claude Code reads the `name` and `description` fields natively.

## User-level (recommended)

Applies to every project you work on with Claude Code.

```bash
# Symlink (recommended — updates automatically when you `git pull` this repo)
ln -sfn $(pwd)/skills ~/.claude/skills

# Or copy if you want to customize per-machine
cp -r skills/* ~/.claude/skills/
```

Use the helper:

```bash
./install.sh claude-code
```

## Project-level

Applies to just one project. Useful if multiple repos on the same machine have different conventions.

```bash
cd <your-project>
mkdir -p .claude
ln -sfn $(realpath /path/to/pystack-skills/skills) .claude/skills
```

Or:

```bash
cd /path/to/pystack-skills
./install.sh claude-code project   # run from inside the target project? See note below.
```

Note: `./install.sh claude-code project` symlinks `skills/` into `./.claude/skills`. Run it from inside the project you want to install to, with the script path adjusted.

## How skills activate

Each skill's `description` field tells Claude when to load it. You don't manually trigger anything — Claude reads the descriptions and selects relevant skills for the task at hand.

To see which skills are available in a session, check the `available skills` system reminder or run `/skills`.

## Disabling a skill

Rename the directory to something Claude Code ignores:

```bash
mv ~/.claude/skills/python-pure-domain-layer ~/.claude/skills/.python-pure-domain-layer.disabled
```

Or delete it.

## Per-project overrides

If a project has its own `.claude/skills/` AND you have user-level skills, both load. Project-level takes precedence for same-named skills.

## Updating

If you symlinked, just `git pull` in this repo — your installed skills update automatically.

If you copied, re-run the copy after `git pull`:

```bash
cd /path/to/pystack-skills
git pull
cp -rf skills/* ~/.claude/skills/
```
