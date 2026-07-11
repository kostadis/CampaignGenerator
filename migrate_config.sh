#!/bin/bash
# Migration script to move configuration files to config subdirectory
# Usage: ./migrate_config.sh [campaign_directory]
# Default: current working directory

set -e

# Use first argument as campaign directory, or current directory if not provided
CAMPAIGN_DIR="${1:-.}"
CONFIG_DIR="$CAMPAIGN_DIR/config"

# Convert to absolute path for safety
CAMPAIGN_DIR=$(cd "$CAMPAIGN_DIR" && pwd)
CONFIG_DIR="$CAMPAIGN_DIR/config"

echo "Campaign directory: $CAMPAIGN_DIR"
echo "Target config directory: $CONFIG_DIR"

# Verify campaign directory exists
if [ ! -d "$CAMPAIGN_DIR" ]; then
  echo "Error: Campaign directory '$CAMPAIGN_DIR' does not exist"
  exit 1
fi

# Check if any config files exist in the root
FILES_TO_MOVE=("config.yaml" "ui_state.yaml" ".campaigngenerator.local.yaml" "planning.yaml")
FOUND_FILES=()

for file in "${FILES_TO_MOVE[@]}"; do
  if [ -f "$CAMPAIGN_DIR/$file" ]; then
    FOUND_FILES+=("$file")
  fi
done

if [ ${#FOUND_FILES[@]} -eq 0 ]; then
  echo "No configuration files found to migrate in $CAMPAIGN_DIR"
  echo "Files checked: ${FILES_TO_MOVE[*]}"
  exit 0
fi

echo "Found files to migrate: ${FOUND_FILES[*]}"

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"
echo "Ensuring config directory exists: $CONFIG_DIR"

# Move each file
for file in "${FOUND_FILES[@]}"; do
  source="$CAMPAIGN_DIR/$file"
  target="$CONFIG_DIR/$file"
  
  if [ -f "$target" ]; then
    echo "Warning: $file already exists in config/ - skipping to avoid overwriting"
    echo "  Source: $source"
    echo "  Target: $target"
  else
    mv "$source" "$target"
    echo "Moved: $file"
    echo "  From: $source"
    echo "  To:   $target"
  fi
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