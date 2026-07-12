# Per-Campaign Configuration Directory Isolation Plan

## Goal
Move all CampaignGenerator configuration files into a configurable `config` subdirectory within each campaign directory.

## Core Changes

### 1. Make Config Directory Location Configurable
- **server/main.py**: Add `--config-dir` argument (default: "config"), pass to CampaignConfigService
- **server/config_service.py**: 
  - Add `config_dir` parameter (default: "config")
  - Compute `config_path_base = campaign_dir / config_dir`
  - Update all path properties to use `config_path_base`
  - Add directory validation/creation with clear error messages
  - Update docstring to document new 3-level structure

### 2. Update Planning Service Location
- **server/planning_config_service.py**: 
  - Modify constructor to accept campaign and config directories
  - Change `planning_path` to: `campaign_dir / config_dir / "planning.yaml"`
  - Update all path references throughout class

### 3. System-Wide Updates
- Verify and update all hardcoded references to configuration filenames in:
  - Other service files (`server/*.py`)
  - Router files (`server/routers/*.py`)
  - Test files
  - Documentation files (`docs/config/*`)
  - Script files
  - Template files

### 4. Manual Migration Approach
Since you're the only user and prefer manual migration:
- Provide migration script description for manual execution
- Script will move: `config.yaml`, `ui_state.yaml`, `.campaigngenerator.local.yaml`, `planning.yaml` from campaign root to `config/` subdirectory
- Include safety checks, confirmation prompts, and dry-run option

### 5. Behavior & Error Handling
- **Default**: `--campaign-dir ./test` → uses `./test/config/`
- **Explicit**: `--config-dir custom` → uses `./test/custom/`
- **Backward compatible**: `--config-dir .` → uses campaign root (original behavior)
- **Errors**: Clear messages if config directory invalid, not creatable, or not writable

### 6. Start Script Usage Examples & Changes
**Changes to `./start` script:**
- Add parsing for `--config-dir` argument in the argument parsing loop (similar to `--campaign-dir`, `--session-dir`, `--port`)
- Pass `--config-dir` value through to the `startup` script in the argument reconstruction section
- Update documentation/comments to mention the new argument

**Usage Examples:**
```bash
# Start with default config directory (<campaign>/config/)
~/CampaignGenerator/start --campaign-dir ./mycampaign

# Start with custom config directory  
~/CampaignGenerator/start --campaign-dir ./mycampaign --config-dir myconfigs

# Start preserving original behavior (backward compatibility)
~/CampaignGenerator/start --campaign-dir ./mycampaign --config-dir .

# Start with config directory at campaign root (explicit .)
~/CampaignGenerator/start --campaign-dir ./mycampaign --config-dir .

# Combine with other arguments
~/CampaignGenerator/start --campaign-dir ./mycampaign --config-dir config --session-dir summaries/20260404 --port 5001

# View help for new argument (via startup script)
~/CampaignGenerator/startup --help
```

### 7. Documentation Updates
All documentation to be updated:
- Command-line help text (--config-dir description in both startup and start scripts)
- Configuration documentation in `docs/config/` (schema.md, master.md, planning-isolation.md, etc.)
- README and getting-started guides
- Any launch scripts or startup documentation (including comments in `./start` and `./startup`)

This provides sensible defaults for new users while maintaining backward compatibility and offering configurable locations for advanced use cases. The start script examples show how to leverage the new `--config-dir` argument in various scenarios, including integration with existing workflows.