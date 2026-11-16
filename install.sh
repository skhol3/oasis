#!/usr/bin/env bash
# Install the committed oasis bundle as the agent skill directory.
#
# Copies the files of HEAD (never uncommitted edits) into the target, removes
# repository-only files, records the installed commit and keeps the previous
# install as a backup outside any skill discovery directory.
set -euo pipefail

usage() {
  echo 'usage: install.sh [--target /absolute/path]' >&2
  echo 'default target: $HOME/.agents/skills/odoo19' >&2
}

die() {
  echo "install.sh: $*" >&2
  exit 1
}

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
target="$HOME/.agents/skills/odoo19"
state=${OASIS_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/oasis}
repo_only=(AGENTS.md .gitignore install.sh)

while (($#)); do
  case $1 in
    --target)
      (($# >= 2)) || { usage; exit 2; }
      target=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

[[ $target == /* ]] || die 'target must be an absolute path'
target=${target%/}
parent=$(dirname "$target")
[[ -d $parent ]] || die "target parent does not exist: $parent"
parent=$(cd "$parent" && pwd -P)
target="$parent/$(basename "$target")"
case "$target/" in
  "$repo"/*) die "target overlaps the repository: $target" ;;
esac
case "$repo/" in
  "$target"/*) die "target overlaps the repository: $target" ;;
esac

git -C "$repo" rev-parse --verify -q HEAD >/dev/null || die 'repository has no commit to install'
commit=$(git -C "$repo" rev-parse HEAD)
if [[ -n $(git -C "$repo" status --porcelain) ]]; then
  echo 'install.sh: warning: uncommitted changes are not installed' >&2
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$state/staging" "$state/backups"
staging=$(mktemp -d "$state/staging/$stamp-XXXXXX")
trap 'rm -rf "$staging"' EXIT

git -C "$repo" archive --format=tar "$commit" | tar -xf - -C "$staging"
for name in "${repo_only[@]}"; do
  rm -f "$staging/$name"
done
printf '{"commit": "%s", "installed_at": "%s", "source": "%s"}\n' \
  "$commit" "$stamp" "$repo" > "$staging/.oasis-install.json"

backup=
if [[ -e $target || -L $target ]]; then
  backup="$state/backups/$(basename "$target")-$stamp"
  mv "$target" "$backup"
fi
if ! mv "$staging" "$target"; then
  [[ -n $backup ]] && mv "$backup" "$target"
  die "could not install into $target; previous install restored"
fi
trap - EXIT

echo "oasis ${commit:0:12} installed in $target"
[[ -z $backup ]] || echo "previous install kept in $backup"
