#!/bin/bash
# Migration script to move configuration files into the config/ subdirectory.
#
# Usage: ./migrate_config.sh [campaign_directory]
# Default: current working directory
#
# Behavior:
#   - Recursively searches the campaign directory for known config files
#     (see CONFIG_NAMES below).
#   - Moves each one into <campaign_directory>/config/.
#   - If a file with the same name already exists in config/, the INCOMING file
#     is moved under a versioned name (e.g. config.yaml.v1, config.yaml.v2, ...)
#     instead of being skipped or overwriting the existing file, so no config
#     file is ever deleted or lost.
#   - The target config/ directory itself, plus .git and node_modules, are
#     excluded from the search (git internals are never config; config/ already
#     holds migrated files).

set -e

# Use first argument as campaign directory, or current directory if not provided
CAMPAIGN_DIR="${1:-.}"

# Verify campaign directory exists before we try to resolve it
if [ ! -d "$CAMPAIGN_DIR" ]; then
  echo "Error: Campaign directory '$CAMPAIGN_DIR' does not exist"
  exit 1
fi

# Convert to absolute path for safety
CAMPAIGN_DIR=$(cd "$CAMPAIGN_DIR" && pwd)
CONFIG_DIR="$CAMPAIGN_DIR/config"

echo "Campaign directory: $CAMPAIGN_DIR"
echo "Target config directory: $CONFIG_DIR"
echo ""

# Config filenames we know how to migrate.
#
# <campaign>/config/ is THE location for every one of these — there are no
# fallback probes any more (docs/config/grounding-isolation.md Track 0). A file
# left outside config/ is simply not found by the app.
#
# party.yaml joins the list per issue #144. The search below is recursive, so
# the obelisk campaign's docs/party.yaml is picked up without needing docs/ as
# an explicit search root. Safe to move only because Phase 2 made its contents
# resolve against the campaign root rather than against its own directory
# (issues #145/#146) — before that, moving it broke every path inside it.
#
# refs.yaml / refs.local.yaml / ingest_manifest.yaml were campaign-root files
# that resolve_refs.py, launch_5etools_mcp.py and apply_ingest_manifest.py read
# from <campaign>/<name>. Those readers move to <campaign>/config/<name> in the
# same change, so run this script only on a tree whose CampaignGenerator is at
# or past that commit.
#
# Deliberately NOT here: docs/entity_registry.yaml (campaign DATA, not config —
# config/ holds how a pipeline runs, docs/ holds what it operates on), and the
# tool-owned root files .mcp.json / .gitignore / .mempalaceignore.
CONFIG_NAMES=(
  "config.yaml"
  "ui_state.yaml"
  ".campaigngenerator.local.yaml"
  "planning.yaml"
  "party.yaml"
  "refs.yaml"
  "refs.local.yaml"
  "ingest_manifest.yaml"
)

# Build the -name predicate group for find: \( -name a -o -name b ... \)
find_name_args=()
for name in "${CONFIG_NAMES[@]}"; do
  if [ ${#find_name_args[@]} -eq 0 ]; then
    find_name_args+=(-name "$name")
  else
    find_name_args+=(-o -name "$name")
  fi
done

# Recursively find config files, pruning the target config dir, .git and node_modules.
# -print0 + read -d '' is used so paths with spaces are handled safely.
FOUND_FILES=()
while IFS= read -r -d '' f; do
  FOUND_FILES+=("$f")
done < <(find "$CAMPAIGN_DIR" \
    \( -path "$CONFIG_DIR" -o -name .git -o -name node_modules \) -prune -o \
    -type f \( "${find_name_args[@]}" \) -print0)

if [ ${#FOUND_FILES[@]} -eq 0 ]; then
  echo "No configuration files found to migrate under $CAMPAIGN_DIR"
  echo "Filenames searched: ${CONFIG_NAMES[*]}"
  exit 0
fi

echo "Found ${#FOUND_FILES[@]} configuration file(s) to migrate:"
for f in "${FOUND_FILES[@]}"; do
  echo "  ${f#"$CAMPAIGN_DIR"/}"
done
echo ""

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"
echo "Ensuring config directory exists: $CONFIG_DIR"
echo ""

# Move each file. On a name collision, version the incoming file so nothing is
# ever overwritten or deleted.
for source in "${FOUND_FILES[@]}"; do
  name=$(basename "$source")
  target="$CONFIG_DIR/$name"

  if [ -e "$target" ]; then
    version=1
    while [ -e "$CONFIG_DIR/${name}.v${version}" ]; do
      version=$((version + 1))
    done
    target="$CONFIG_DIR/${name}.v${version}"
    echo "Note: '$name' already exists in config/ - keeping existing, versioning the incoming copy"
  fi

  mv "$source" "$target"
  echo "Moved: ${source#"$CAMPAIGN_DIR"/}"
  echo "  ->   ${target#"$CAMPAIGN_DIR"/}"
done

echo ""
echo "Migration complete!"
echo "Configuration files are now in: $CONFIG_DIR"
echo ""
echo "To use the new structure with CampaignGenerator:"
echo "  ./start --campaign-dir $CAMPAIGN_DIR"
echo ""
echo "To verify the migration worked:"
echo "  ls -la $CONFIG_DIR/"
echo ""
echo "Note: If you want to preserve the original behavior (files in campaign root),"
echo "      use: ./start --campaign-dir $CAMPAIGN_DIR --config-dir ."
