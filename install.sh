#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$REPO_DIR/skills"
TIERS="python service opt-in"

usage() {
  cat <<'EOF'
Install PyStack skills by linking each one into an agent's skills directory.

Usage:
  install.sh <target> [options] [tier|skill ...]
  install.sh --list

Targets:
  claude    Claude Code                         ~/.claude/skills  (--project: ./.claude/skills)
  agents    Codex, Cursor, OpenCode, GitHub     ~/.agents/skills  (--project: ./.agents/skills)
            Copilot / VS Code, Gemini CLI, and
            other Agent Skills clients

Selection (default: every skill):
  python | service | opt-in    every skill in that tier
  python-<name>                one skill by name

Options:
  --project     install into the current directory instead of your home directory
  --copy        copy instead of symlink (symlinks pick up `git pull`; copies don't)
  --force       replace an existing non-symlink directory with the same skill name
  --uninstall   remove the selected skills from the target instead
  --list        list skills and their tiers
  -h, --help    show this help

Examples:
  install.sh claude                           # every skill, for you, in Claude Code
  install.sh agents --project service         # service tier into ./.agents/skills
  install.sh claude python python-test-pyramid
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

all_skills() {
  for dir in "$SKILLS_DIR"/*/; do
    [ -f "$dir/SKILL.md" ] && basename "$dir"
  done
}

tier_of() {
  awk '/^---$/ { fences++; next } fences == 1 && /^  tier:/ { print $2; exit }' "$SKILLS_DIR/$1/SKILL.md"
}

list_skills() {
  for name in $(all_skills); do
    printf '%-8s %s\n' "$(tier_of "$name")" "$name"
  done
}

TOOL=""
PROJECT=0
COPY=0
FORCE=0
UNINSTALL=0
WANTED=""

[ $# -gt 0 ] || { usage >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    claude|claude-code) TOOL="claude" ;;
    agents|codex|cursor|opencode|copilot) TOOL="agents" ;;
    --project) PROJECT=1 ;;
    --copy) COPY=1 ;;
    --force) FORCE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --list) list_skills; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) WANTED="$WANTED $1" ;;
  esac
  shift
done

[ -n "$TOOL" ] || die "missing target: claude or agents (see --help)"

SELECTED=" "
select_skill() {
  case "$SELECTED" in
    *" $1 "*) ;;
    *) SELECTED="$SELECTED$1 " ;;
  esac
}

if [ -z "$WANTED" ]; then
  for name in $(all_skills); do select_skill "$name"; done
fi
for item in $WANTED; do
  case " $TIERS " in
    *" $item "*)
      for name in $(all_skills); do
        [ "$(tier_of "$name")" = "$item" ] && select_skill "$name"
      done
      continue
      ;;
  esac
  if [ -f "$SKILLS_DIR/$item/SKILL.md" ]; then
    select_skill "$item"
  elif [ "$item" = "project" ] || [ "$item" = "user" ]; then
    die "unknown skill or tier: $item (did you mean --project?)"
  else
    die "unknown skill or tier: $item (tiers: $TIERS; see --list)"
  fi
done

if [ "$PROJECT" = 1 ]; then BASE="$PWD"; else BASE="$HOME"; fi
case "$TOOL" in
  claude) DEST="$BASE/.claude/skills" ;;
  agents) DEST="$BASE/.agents/skills" ;;
esac

if [ -L "$DEST" ]; then
  die "$DEST is itself a symlink (to $(readlink "$DEST")), probably from an older PyStack installer that linked the whole directory.
       Remove the link (this deletes no skills) and re-run: rm \"$DEST\""
fi

SKIPPED=0
skip() {
  echo "skip    $1: $2" >&2
  SKIPPED=$((SKIPPED + 1))
}

install_skill() {
  local name="$1" dest="$DEST/$1"
  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    [ "$FORCE" = 1 ] || { skip "$name" "$dest exists and is not a symlink (--force replaces it)"; return 0; }
    rm -rf "$dest"
  fi
  if [ "$COPY" = 1 ]; then
    cp -R "$SKILLS_DIR/$name" "$dest"
  else
    ln -s "$SKILLS_DIR/$name" "$dest"
  fi
  echo "added   $name"
}

uninstall_skill() {
  local name="$1" dest="$DEST/$1"
  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    [ "$FORCE" = 1 ] || { skip "$name" "$dest is a copy, not a symlink (--force deletes it)"; return 0; }
    rm -rf "$dest"
  else
    return 0
  fi
  echo "removed $name"
}

if [ "$UNINSTALL" = 1 ]; then
  for name in $SELECTED; do uninstall_skill "$name"; done
else
  mkdir -p "$DEST"
  for name in $SELECTED; do install_skill "$name"; done
fi

echo "target: $DEST"
[ "$SKIPPED" = 0 ] || exit 1
