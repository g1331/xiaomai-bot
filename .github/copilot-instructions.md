# xiaomai-bot GitHub Copilot Instructions

xiaomai-bot is a QQ bot based on the Graia Ariadne framework with a modular plugin architecture. It supports AI chat, gaming utilities (Battlefield 1), image processing, entertainment features, and administrative functions.

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Working Effectively

### Bootstrap, Build, and Test the Repository

**CRITICAL**: Install `uv` (modern Python package manager) before any other operations:
- **Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh` -- may fail due to network restrictions
- **Fallback**: `python3 -m pip install uv` -- always works in restricted environments
- **Windows**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **Verify**: `uv --version`

**Setup and Dependencies** (takes ~30 seconds, NEVER CANCEL):
```bash
cd /path/to/xiaomai-bot
uv sync  # Install all dependencies - takes 24 seconds. Set timeout to 120+ seconds.
```

**Configuration Setup**:
```bash
cp config/config_demo.yaml config/config.yaml
# Edit config.yaml to replace placeholder values:
# - Master: 123456789 (valid QQ number)
# - test_group: 987654321 (valid group number) 
# - bot_accounts: [123456] (list of valid QQ numbers)
# - default_account: 123456 (valid QQ number)
```

**Start the Bot** (requires external Mirai server):
```bash
uv run main.py  # Will fail without Mirai server - this is expected
```

### Linting and Code Quality

**Run Ruff Linter** (takes <1 second, NEVER CANCEL):
```bash
uv run ruff check --output-format=github .  # 0.08 seconds
```

**Run Ruff Formatter** (takes <1 second, NEVER CANCEL):
```bash
uv run ruff format --check .  # 0.10 seconds
uv run ruff format .  # To actually format files
```

**Run Pre-commit Hooks** (takes ~7 seconds first time, NEVER CANCEL):
```bash
# Install pre-commit in virtual environment if not available
uv run pip install pre-commit
uv run pre-commit run --all-files  # 6.6 seconds first time, <1 second after
```

### Testing

**Run All Tests** (takes ~2 seconds, NEVER CANCEL):
```bash
uv run pytest tests/ -v  # 1.7 seconds, 30 tests pass
```

**Test Categories**:
- Socket keepalive tests (Blaze protocol)
- Minecraft async database fixes  
- Header handling fixes
- Parameter parsing tests

## Validation

**CRITICAL VALIDATION SCENARIOS**: After making changes, always test these core functionalities:

### 1. Bot Startup Validation
```bash
# Test that bot initializes correctly (will fail at Mirai connection - this is expected)
timeout 10 uv run main.py 2>&1 | head -20
# Should show ASCII art, configuration checks, and module loading
```

### 2. Plugin System Validation  
- Check that plugins in `modules/required/`, `modules/self_contained/`, and `modules/third_party/` load correctly
- Verify plugin metadata files (`metadata.json`) are valid JSON
- Test that core control systems (permissions, frequency limits, function switches) work

### 3. Configuration Validation
- Ensure `config.yaml` has valid structure and data types
- Test environment variable override functionality
- Verify database connection string format

### 4. Code Quality Validation
- Always run `uv run ruff check .` and `uv run ruff format --check .` before committing
- Run `uv run pre-commit run --all-files` to ensure hooks pass
- All tests must pass: `uv run pytest tests/ -v`

## Deployment Options

### Local Development
```bash
# Quick start scripts available:
./run.sh      # Linux/macOS - handles uv installation and setup
./run.bat     # Windows - handles uv installation and setup  
```

### Docker Deployment
```bash
# Note: Dockerfile uses Poetry, not uv (legacy configuration)
docker build -t xiaomai-bot .
docker run -d --name xiaomai-bot --net=host \
  -v $(pwd)/config/config.yaml:/xiaomai-bot/config/config.yaml \
  -v $(pwd)/data.db:/xiaomai-bot/data.db \
  xiaomai-bot
```

### Docker Compose
```bash
docker-compose up -d
```

## External Dependencies

**Required External Service**: Mirai (QQ bot framework server)
- Install MCL 2.1.0 and Mirai API HTTP (MAH) 
- Configure endpoint in `config.yaml`: `mirai_host: http://localhost:8080`
- Bot will fail startup without Mirai - this is expected behavior during development

**Database**: SQLite with async SQLAlchemy ORM
- Default: `sqlite+aiosqlite:///data.db`
- Database file created automatically on first run
- Migrations handled via Alembic: `alembic revision --autogenerate`

## Project Structure

### Core Directories
- `core/` - Framework code (bot.py, config.py, control.py, orm/)
- `modules/required/` - Essential plugins (permissions, help, auto-upgrade)
- `modules/self_contained/` - Built-in plugins (AI chat, BF1, image tools)
- `modules/third_party/` - External plugins
- `utils/` - Utility libraries
- `config/` - Configuration files
- `tests/` - Test suites

### Key Files
- `main.py` - Application entry point
- `pyproject.toml` - Dependencies and project metadata (uses uv, not Poetry)
- `config_demo.yaml` - Template configuration
- `.pre-commit-config.yaml` - Code quality hooks
- `scripts/bump.py` - Version management utility

## Common Development Tasks

### Adding New Dependencies
```bash
uv add <package>        # Add runtime dependency
uv add --dev <package>  # Add development dependency
uv remove <package>     # Remove dependency
```

### Plugin Development
1. Create plugin directory in appropriate `modules/` subdirectory
2. Add `metadata.json` with plugin information
3. Implement `__init__.py` with Saya event listeners
4. Use `@channel.use(ListenerSchema(...))` for message handling
5. Test plugin loading: check bot startup logs for successful module installation

### Version Management
```bash
python scripts/bump.py info                    # Show current version
python scripts/bump.py patch --commit --tag    # Bump patch version
python scripts/bump.py minor --changelog       # Bump minor with changelog
```

### Database Operations
- Models: `core/orm/tables.py`
- Access: `await orm.fetch_one()`, `await orm.insert()`
- Migrations: `alembic revision --autogenerate`

## Build Timings and Timeouts

**NEVER CANCEL these operations** - always wait for completion:

| Operation | Expected Time | Timeout Setting |
|-----------|---------------|-----------------|
| `uv sync` | 24 seconds | 120+ seconds |
| `uv run pytest tests/` | 2 seconds | 30+ seconds |
| `uv run ruff check .` | 0.08 seconds | 30+ seconds |
| `uv run ruff format .` | 0.10 seconds | 30+ seconds |
| `uv run pre-commit run --all-files` | 7 seconds (first), <1 second (subsequent) | 60+ seconds |
| Bot startup (until Mirai connection fails) | 3 seconds | 30+ seconds |

## Framework-Specific Notes

### Graia Ariadne Framework
- Event-driven architecture with Broadcast Control
- Message chains for rich content (text, images, at-mentions)
- Saya module system for plugin management
- Launart for lifecycle management

### Plugin Architecture
- Three-tier plugin system: required, self_contained, third_party
- Each plugin has metadata.json describing capabilities
- Control system handles permissions, frequency limits, function switches
- Database integration via async ORM

### Core APIs
- Configuration: `config = create(GlobalConfig)`
- Database: `await orm.fetch_one()`, `await orm.insert()`
- Messaging: `await app.send_message(target, MessageChain(...))`
- Permissions: `Permission.require()`, `Function.require()`

## Troubleshooting

### Common Issues
1. **uv not found**: Install via pip fallback: `python3 -m pip install uv`
2. **Config validation errors**: Check that placeholder values in config.yaml are replaced with valid data
3. **Mirai connection fails**: Expected during development - Mirai server must be running separately
4. **Module import errors**: Ensure `uv sync` completed successfully
5. **Permission denied on scripts**: `chmod +x run.sh` on Linux/macOS

### CI/CD Integration
- Pre-commit hooks enforce code quality
- GitHub Actions run tests on Python 3.10, 3.11
- Docker builds use Python 3.10 with Poetry (legacy)
- All changes must pass: ruff check, ruff format, pytest

Always validate changes by running the complete test suite and ensuring the bot can start and load all plugins successfully.