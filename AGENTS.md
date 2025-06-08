# AGENTS.md - AI 代理开发指南

欢迎AI代理协助开发本项目！为确保代码质量、风格统一和协作顺畅，请在开始工作前仔细阅读并遵守以下指南。

## 概述
本文档旨在为参与本项目的AI编码代理提供指导，内容包括代码风格、测试流程、环境配置、工具使用以及合并请求（PR）的规范。

## 1. 代码风格

### 1.1 Python 版本
- 本项目支持 **Python 版本 >=3.10, <3.13** (即 3.10, 3.11, 3.12)。请确保您的代码兼容这些版本。

### 1.2 代码格式化
- **Ruff Formatter**: 本项目使用 Ruff 进行代码格式化，配置如下：
    - 行长度：最大88个字符。
    - 引号：统一使用双引号 (`""`)。
    - 缩进：使用空格进行缩进。
- **提交前检查**: 项目配置了 pre-commit 钩子，会自动使用 Ruff Formatter 进行格式化。请在本地安装并启用 pre-commit，确保提交的代码符合格式要求。

### 1.3 代码规范 (Linting)
- **Ruff Linter**: 本项目使用 Ruff 进行代码规范检查，启用的规则集包括 `E` (PEP 8 错误), `F` (Pyflakes), `W` (一般警告), `UP` (Python 版本升级建议)。
- **提交前检查**: pre-commit 钩子同样会运行 Ruff Linter。请确保所有Linter报告的问题都已修复。

### 1.4 命名约定
- 遵循 PEP 8 命名约定。
- 变量、函数和模块名应清晰、描述性强，尽量避免使用无意义的缩写。

### 1.5 注释与文档字符串
- 为公共模块、类、函数和方法编写清晰的文档字符串 (docstrings)。
- 对复杂或不直观的代码段添加必要的行内注释。

## 2. 测试

### 2.1 当前测试状态
- 项目当前的自动化CI流程主要依赖 pre-commit 钩子执行代码格式化和规范检查。
- **目前在CI流程和Dockerfile中未发现明确的单元测试或集成测试执行步骤** (例如 `pytest` 或 `unittest`)。

### 2.2 AI 代理的测试责任
- **编写单元测试**: 对于新增的模块或重要功能，请为其编写单元测试。建议使用 `pytest` 框架。
    - 测试文件应放置在 `tests/` 目录下，并遵循 `test_*.py` 的命名约定。
- **本地运行测试**: 在提交代码前，请在本地运行您编写的测试，确保它们通过。
    - 例如，如果使用 `pytest`：`uv run pytest tests/`
- **集成测试**: 对于涉及多个组件交互的功能，请考虑编写集成测试。
- **未来方向**: 建议项目未来在CI流程中加入自动化测试步骤。

## 3. 工具和环境

### 3.1 依赖管理
- 本项目使用 `uv` 进行依赖管理。
- **安装依赖**: 在项目根目录下运行 `uv sync`。此命令会根据 `uv.lock` 文件安装所有项目依赖。如果 `uv.lock` 不存在或需要更新（例如 `pyproject.toml` 修改后），`uv sync` 也会基于 `pyproject.toml` 生成或更新 `uv.lock` 文件。
- **添加新依赖**: 运行 `uv add <package_name>` 命令。此命令会自动将依赖项添加到 `pyproject.toml` 文件并更新 `uv.lock` 文件及当前开发环境。
- **移除依赖**: 运行 `uv remove <package_name>` 命令。此命令会自动从 `pyproject.toml` 文件中移除依赖项并更新 `uv.lock` 文件及当前开发环境。

### 3.2 Python 环境
- **创建虚拟环境**: `uv venv` (通常会自动在 `.venv` 目录创建)
- **激活虚拟环境**:
    - Linux/macOS: `source .venv/bin/activate`
    - Windows: `.venv\Scripts\activate`
- **运行项目**: `uv run main.py`

### 3.3 配置文件
- 项目的主要配置文件是 `config.yaml`。
- 首次配置时，请将 `config_demo.yaml` 复制为 `config.yaml`，并根据实际需求填写配置信息。

### 3.4 Docker
- 项目提供了 `Dockerfile` 用于构建镜像。
- **构建镜像**: `docker build -t xiaomai-bot .`
- Docker部署时，配置通常通过环境变量传递，或挂载 `config.yaml`。

### 3.5 pre-commit
- **在仓库中安装钩子**: `pre-commit install` (通常在初次克隆项目后执行一次)
- **手动运行所有检查**: `pre-commit run --all-files` (CI中会执行此操作，提交前在本地运行以确保通过)

## 4. 合并请求 (Pull Request) 指南

### 4.1 分支命名规范
- **基本要求**:
  - 分支名必须使用英文。
  - 禁止包含中文或任何非ASCII的特殊字符。
  - 单词之间建议使用连字符 (`-`) 或下划线 (`_`) 分隔。
- **命名结构**:
  - 分支名应简洁明了，能够清晰概括该分支的主要目的或特性。
  - 推荐使用 `类型/简短描述` 的格式，例如：
    - `feat/user-authentication` (新功能：用户认证)
    - `fix/payment-gateway-error` (修复：支付网关错误)
    - `docs/update-readme` (文档：更新README)
    - `refactor/database-schema` (重构：数据库结构)
    - `chore/update-dependencies` (事务：更新依赖)
- **常见类型 (`type`)**:
  - `feat`: 新功能 (feature)
  - `fix`: Bug修复
  - `docs`: 文档相关的修改
  - `style`: 代码风格调整（不影响代码逻辑）
  - `refactor`: 代码重构（既不是新增功能，也不是修复bug）
  - `test`: 添加或修改测试
  - `chore`: 构建过程或辅助工具的变动

### 4.2 Commit Message 规范
- 本项目遵循 **Conventional Commits** 规范。这对于版本管理和生成更新日志 (CHANGELOG) 非常重要。
- **格式**: `<type>(<scope>): <subject>`
    - `type`: 提交类型，例如 `feat` (新功能), `fix` (修复bug), `docs` (文档), `style` (代码格式), `refactor` (重构), `test` (测试), `chore` (构建过程或辅助工具变动)。
    - `scope` (可选): 本次提交影响的范围，例如某个模块名。
    - `subject`: 简短描述本次提交的目的，动词开头，首字母小写。
- **示例**:
    - `feat(api): add new endpoint for user data`
    - `fix: correct calculation error in payment module`
    - `docs: update installation guide`
- 详细的 `type` 分类请参考 `pyproject.toml` 文件中 `[tool.git-cliff.commit_parsers]`部分的定义。

### 4.3 PR 标题
- PR 标题应清晰概括PR的内容，建议也遵循 Conventional Commits 的 `<type>(<scope>): <subject>` 格式。

### 4.4 PR 描述
- 清晰描述PR的目的、所做的更改。
- 如果解决了某个Issue，请在描述中链接该Issue (例如 `Closes #123`)。
- 说明如何测试您的更改。

### 4.5 CI 检查
- 提交PR后，会自动触发 GitHub Actions CI流程。
- CI会执行 pre-commit 检查 (Ruff格式化和Linting) 以及 Docker 镜像构建。
- **确保所有CI检查都通过** 后，PR才能被合并。

## 5. 其他注意事项
- 在进行大的重构或添加复杂功能前，建议先通过Issue进行讨论。
