# xiaomai-bot Development Instructions

**ALWAYS follow these instructions first and only fall back to additional search and context gathering if the information here is incomplete or found to be in error.**

xiaomai-bot is a Python-based QQ bot built with the Graia Ariadne framework. It uses a modular plugin architecture with core functionality in `core/`, plugins in `modules/`, and utilities in `utils/`.

## Essential Development Setup

### Install Dependencies
**CRITICAL**: Install uv package manager first if not available:
```bash
# If uv command not found, install via pip:
python3 -m pip install uv
```

**Setup and install all dependencies** (takes 25-30 seconds):
```bash
uv sync
```
**NEVER CANCEL** - This command takes 25-30 seconds to complete. Always wait for completion.

### Code Quality and Validation
**Always run before committing changes:**
```bash
# Linting (takes <1 second):
uv run ruff check .
uv run ruff format --check .

# Pre-commit hooks (takes 5-10 seconds after first setup):
# First time setup may take longer to install hooks
pre-commit run --all-files
```

**Test suite** (takes 2-3 seconds):
```bash
uv run pytest tests/ -v
```
**NEVER CANCEL** - Test suite completes in 2-3 seconds. Always wait for full completion.

### Running the Application
**⚠️ IMPORTANT: Most development tasks do NOT require running the full application.**

**When to run the full application:**
- Developing new plugins that require framework integration testing
- Making core framework changes that need end-to-end validation
- Testing full bot behavior with external dependencies (Mirai HTTP, QQ)

**For plugin functionality testing, prefer unit tests:**
```bash
# Test specific plugin functionality:
uv run pytest tests/test_plugin_name.py -v

# Test all plugins:
uv run pytest tests/ -v
```

**Application startup requires external setup and will FAIL without proper configuration:**
```bash
# Only run if developing plugins or core framework changes:
uv run main.py
```

**Quick start scripts (for full deployment only):**
```bash
# Linux/Mac:
./run.sh

# Windows:
run.bat
```

**Configuration setup (only needed for full application runs):**
```bash
# Copy demo config and manually edit:
cp config/config_demo.yaml config/config.yaml
# Edit config.yaml with valid QQ account IDs and Mirai HTTP settings

# Interactive configuration (requires terminal):
uv run main.py --set-config
```

## Validation Requirements

### Manual Testing After Changes
**ALWAYS test after making changes:**

1. **Development workflow validation (required for all changes):**
   ```bash
   uv sync                              # Verify dependencies install
   uv run ruff check .                  # Verify code passes linting
   uv run ruff format --check .         # Verify code is formatted
   uv run pytest tests/ -v              # Verify tests pass
   ```

2. **Plugin-specific testing (for plugin changes):**
   ```bash
   # Test specific plugin functionality:
   uv run pytest tests/test_plugin_name.py -v
   
   # Test affected modules only:
   uv run pytest tests/ -k "plugin_name" -v
   ```

3. **Application startup validation (only for plugin development or framework changes):**
   ```bash
   # Should fail gracefully with config errors (expected):
   # Only run if developing plugins or core framework changes
   uv run main.py
   ```

4. **Configuration validation (only if modifying config-related code):**
   ```bash
   # Verify config file structure:
   python3 -c "import yaml; print(yaml.safe_load(open('config/config_demo.yaml')))"
   ```

### External Dependencies Required for Full Operation
**The application requires these external components to run fully:**
- Mirai HTTP API server running on configured host/port
- Valid QQ bot account credentials
- SQLite database (created automatically)
- Network access for external APIs (AI providers, image services, etc.)

## Build and Deployment

### Docker Deployment
**Docker build** (takes 5-15 minutes when network is available):
```bash
docker build -t xiaomai-bot .
```
**NEVER CANCEL** - Docker builds can take 5-15 minutes. Set timeout to 30+ minutes.

**Docker Compose:**
```bash
# Setup first:
cp config/config_demo.yaml config/config.yaml
# Edit config.yaml with real values

# Deploy:
docker-compose up -d
```

### Environment Variables
**For Docker/production deployment, use these environment variables:**
- `bot_accounts`: Bot QQ account IDs (comma-separated)
- `default_account`: Primary bot account ID
- `Master`: Admin QQ account ID
- `mirai_host`: Mirai HTTP server URL
- `verify_key`: Mirai HTTP verification key
- `test_group`: Debug group ID
- `db_link`: Database connection string

## Project Structure Navigation

### Core Components
- `core/`: Framework core (bot.py, config.py, control.py, orm/)
- `modules/`: Plugin system
  - `required/`: Essential plugins (permissions, help, management)
  - `self_contained/`: Built-in features (AI chat, BF1 stats, images)
  - `third_party/`: External plugins
- `utils/`: Utility libraries and helpers
- `config/`: Configuration files
- `tests/`: Test suite

### Key Development Files
- `main.py`: Application entry point
- `pyproject.toml`: Dependencies and project config
- `uv.lock`: Dependency lock file
- `.pre-commit-config.yaml`: Code quality hooks
- `run.sh`/`run.bat`: Quick start scripts

### Important Development Commands
```bash
# Version info:
uv --version                    # Check uv version
python3 --version              # Check Python version (requires >=3.10, <3.13)

# Project commands:
uv sync                         # Install/update dependencies
uv add <package>               # Add new dependency
uv remove <package>            # Remove dependency

# Code quality:
uv run ruff check .            # Lint code
uv run ruff format .           # Format code
pre-commit install             # Setup git hooks
pre-commit run --all-files     # Run all hooks

# Testing:
uv run pytest                  # Run all tests
uv run pytest tests/test_*.py  # Run specific test file
uv run pytest -v              # Verbose test output
```

## Common Development Tasks

### Adding New Functionality
1. **Create plugin in appropriate `modules/` subdirectory**
2. **Include `metadata.json` with plugin information**
3. **Use `@channel.use(ListenerSchema())` for event handling**
4. **Test with unit tests first: `uv run pytest tests/test_new_plugin.py -v`**
5. **Run full test suite: `uv run pytest tests/ -v`**
6. **Only run full application if plugin requires framework integration testing**
7. **Run `pre-commit run --all-files` before committing**

### Debugging Issues
1. **Check logs in `log/` directory (created at runtime)**
2. **Verify Mirai HTTP server is running and accessible**
3. **Validate configuration with demo config comparison**
4. **Use `debug_mode: true` in config for master-only responses**

### Database Operations
1. **Uses SQLAlchemy async ORM with SQLite**
2. **Models defined in `core/orm/tables.py`**
3. **Migrations via Alembic (see `utils/alembic.py`)**
4. **Database file created automatically at configured path**

## Time Expectations and Timeouts

**Command Timing Reference:**
- `uv sync`: 25-30 seconds (first run), 2-5 seconds (subsequent)
- `uv run pytest`: 2-3 seconds
- `uv run ruff check .`: <1 second
- `pre-commit run --all-files`: 5-10 seconds (after initial setup)
- Docker build: 5-15 minutes (with network access)
- Application startup: <5 seconds (will fail without valid config)

**Always use these minimum timeouts:**
- Dependency installation: 60+ seconds
- Test execution: 30+ seconds  
- Docker builds: 30+ minutes
- **CRITICAL**: NEVER CANCEL long-running operations - they will complete

## Troubleshooting

### Common Issues
1. **"uv: command not found"** → Install with `python3 -m pip install uv`
2. **Permission denied on run.sh** → Run `chmod +x run.sh`
3. **Config validation errors** → Use `config_demo.yaml` as template with real values
4. **Import errors** → Run `uv sync` to ensure dependencies are installed
5. **Docker build failures** → Usually network/DNS issues, retry with better connectivity

### Expected Failures
- **Application startup without config**: Normal, requires valid QQ credentials
- **Docker build in restricted environments**: Network access required for packages
- **Interactive config tools in CI**: Requires terminal, use environment variables instead

## CI/CD Integration

**GitHub Actions workflow** (`.github/workflows/pre-commit.yml`):
- Runs on Python 3.10, 3.11
- Executes pre-commit hooks automatically
- Fails if code style or linting issues exist

**Pre-commit hooks** automatically run:
- Ruff linting with auto-fix
- Ruff code formatting
- Must pass before merge

## Quick Reference Commands

```bash
# Essential development cycle (for most changes):
uv sync                              # Setup dependencies
uv run ruff check . && uv run ruff format --check .  # Code quality  
uv run pytest tests/ -v             # Run tests
pre-commit run --all-files          # Final validation

# Plugin development cycle (when creating/modifying plugins):
uv run pytest tests/test_plugin_name.py -v  # Test specific plugin
uv run main.py                       # Test framework integration (only if needed)

# Repository exploration:
ls -la                               # See project structure
cat pyproject.toml                   # Check dependencies/config
cat README.md                        # Full documentation
cat config/config_demo.yaml          # Configuration template
```

**Remember: Always validate every step and never cancel long-running operations.**