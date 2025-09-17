# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a QQ bot built on the Graia Ariadne framework, named "xiaomai-bot" (小麦机器人). It's a comprehensive chatbot with AI integration, gaming features (especially Battlefield 1), image processing, entertainment functions, and management capabilities.

## Development Commands

### Core Commands
- **Run the bot**: `uv run main.py`
- **Install dependencies**: `uv sync` (using uv package manager)
- **Linting**: `ruff check` (configured in pyproject.toml)
- **Formatting**: `ruff format` (configured in pyproject.toml)  
- **Tests**: `pytest` (test files in tests/ directory)

### Convenience Scripts
- **Windows**: `run.bat` - Quick start script for Windows
- **Linux**: `run.sh` - Quick start script for Linux

### Version Management
- **Bump version**: Uses `bump-my-version` tool (configured in pyproject.toml)
- **Changelog generation**: Uses `git-cliff` (configured in pyproject.toml)

## Architecture Overview

### Core Components
- **main.py**: Application entry point with message listeners and bot initialization
- **core/**: Contains the bot's core functionality
  - **bot.py**: Main bot class (Umaru) with module loading and initialization
  - **config.py**: Global configuration access interface  
  - **control.py**: Permission, frequency, and feature control components
  - **orm/**: Database ORM layer with SQLAlchemy + Alembic migrations
  - **models/**: Control component models (frequency, response, saya)

### Module System
The bot uses a plugin-based architecture organized into:
- **modules/required/**: Essential plugins (auto_upgrade, saya_manager, perm_manager, helper, status, etc.)
- **modules/self_contained/**: Built-in feature plugins (AI chat, BF1 features, image processing, entertainment)
- **modules/third_party/**: External plugins

Each module has a `metadata.json` file defining its configuration, permissions, and usage.

### Database Architecture
- Uses SQLAlchemy ORM with async support (AsyncORM)
- SQLite database by default (`data.db`)
- Alembic for database migrations
- Tables defined in `core/orm/tables.py`

### Key Features
- **AI Chat**: Multi-provider support (OpenAI, DeepSeek) with plugin system for tools
- **Battlefield 1 Integration**: Complete server management and player statistics
- **Image Processing**: Search, generation, meme creation using Playwright
- **Permission System**: Granular user and group permissions
- **Multi-Account Support**: Supports multiple bot accounts with response management

## Configuration

### Primary Config
- **config.yaml**: Main configuration file (copy from config_demo.yaml)
- Environment variables supported for Docker deployment
- Critical settings: bot_accounts, mirai_host, verify_key, Master (admin user)

### Prerequisites
- Python 3.10-3.12
- Mirai Console with Mirai API HTTP plugin
- UV package manager (recommended)

## Important Patterns

### Module Development
- Each module should have proper metadata.json configuration
- Use the control system for permissions and rate limiting
- Follow the existing patterns for message handling and command parsing

### Database Operations
- Use the AsyncORM from `core.orm` for database operations  
- All database models should inherit from Base in `core.orm`
- Use Alembic migrations for schema changes

### Error Handling
- Comprehensive logging with loguru
- Error logs stored in `log/` directory organized by date
- Exception catcher module handles unhandled exceptions

## Testing

- Test files located in `tests/` directory
- Uses pytest with async support
- Includes specialized tests for components like md2img, Minecraft integration

## Deployment

Supports multiple deployment methods:
- Direct Python execution
- Docker containers  
- Docker Compose
- All methods support environment variable configuration

## Dependencies

Major dependencies include:
- graia-ariadne: Core bot framework
- SQLAlchemy + Alembic: Database ORM and migrations  
- FastAPI: Web interface
- Playwright: Browser automation for image generation
- httpx: HTTP client
- Various AI providers (openai, etc.)

The project uses UV for dependency management with lock file support.