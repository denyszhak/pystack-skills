#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$REPO_DIR/skills"

usage() {
  cat <<EOF
Install PyStack into your AI coding tool.

Usage:
  install.sh claude-code [user|project]    Symlink skills into ~/.claude/skills (user, default)
                                            or ./.claude/skills (project).
  install.sh codex [output-file]            Generate AGENTS.md at ./AGENTS.md (default) or
                                            the path you pass.
  install.sh opencode                       Copy skills into ./.opencode/rules/
  install.sh cursor                         Copy skills into ./.cursor/rules/ as .mdc files

Re-run after 'git pull' in this repo to update.
EOF
}

claude_code() {
  local scope="${1:-user}"
  case "$scope" in
    user)
      local target="$HOME/.claude/skills"
      mkdir -p "$(dirname "$target")"
      if [ -e "$target" ] && [ ! -L "$target" ]; then
        echo "error: $target exists and is not a symlink. Move it aside and retry." >&2
        exit 1
      fi
      ln -sfn "$SKILLS_DIR" "$target"
      echo "linked $SKILLS_DIR -> $target"
      ;;
    project)
      local target=".claude/skills"
      mkdir -p .claude
      ln -sfn "$SKILLS_DIR" "$target"
      echo "linked $SKILLS_DIR -> $(pwd)/$target"
      ;;
    *)
      echo "error: unknown scope '$scope' (expected: user | project)" >&2
      exit 1
      ;;
  esac
}

codex() {
  local out="${1:-AGENTS.md}"
  {
    echo "# PyStack conventions"
    echo
    echo "These conventions apply to all Python code in this repo."
    echo
    for f in "$SKILLS_DIR"/*/SKILL.md; do
      local name
      name="$(basename "$(dirname "$f")")"
      echo "## $name"
      awk '/^---$/{c++; next} c>=2' "$f"
      echo
    done
  } > "$out"
  echo "wrote $out"
}

opencode() {
  mkdir -p .opencode/rules
  for d in "$SKILLS_DIR"/*/; do
    local name
    name="$(basename "$d")"
    cp "$d/SKILL.md" ".opencode/rules/$name.md"
  done
  echo "copied skills to $(pwd)/.opencode/rules/"
}

cursor() {
  mkdir -p .cursor/rules
  for d in "$SKILLS_DIR"/*/; do
    local name
    name="$(basename "$d")"
    cp "$d/SKILL.md" ".cursor/rules/${name}.mdc"
  done
  echo "copied skills to $(pwd)/.cursor/rules/"
  echo "note: Cursor supports 'globs' and 'alwaysApply' frontmatter — see install/cursor.md"
}

case "${1:-}" in
  claude-code) shift; claude_code "$@";;
  codex)       shift; codex "$@";;
  opencode)    shift; opencode "$@";;
  cursor)      shift; cursor "$@";;
  -h|--help|"") usage;;
  *) echo "error: unknown tool '$1'" >&2; usage; exit 1;;
esac
