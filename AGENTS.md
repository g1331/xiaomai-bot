# AGENTS.md - Tenko 开发指南

本文档为参与 Tenko 项目开发的协作者提供约定和必要上下文。

## 项目定位

Tenko 是面向 QQ 群的管理 bot，使用 Entari 作为运行时，以 Satori 协议抽象承接
消息、事件和平台动作，并通过 OneBot 11 接入 QQ。业务能力以插件形式组织，覆盖
权限、群管理、账号响应策略、功能开关、状态查询和宿主升级。

协议接入应以 OneBot 11 和 Satori 为边界，插件逻辑不要绑定到某一个具体协议端。
持久化数据使用 SQLite；数据库访问集中在 repository 和数据库服务中，避免在插件
里直接管理连接生命周期。

## 目录结构

```text
tenko/
├── __main__.py              # 命令行入口和 dry-run
├── config.py                # TOML 配置模型
├── connection.py            # OneBot 11 / Satori 连接服务
├── runtime.py               # Entari 运行时装配
├── context.py               # 消息上下文和身份转换
├── db/                      # 模型、迁移、数据库启动和 repositories
├── host/                    # 账号、权限、功能、限流和升级服务
├── plugins/                 # Tenko 原生插件
└── templates/               # 离线渲染模板和资源
tests/tenko/                  # 单元测试和集成式调用点测试
config/tenko.toml.example    # 配置模板
requirements-entari.txt      # pip 兼容出口（锁定版本快照，主路径是 uv.lock）
```

## 开发环境与命令

- 支持 Python `>=3.10,<3.13`。
- 依赖管理使用 uv（pyproject.toml 声明依赖，uv.lock 锁定版本）。
  在项目根目录执行 `uv sync` 创建/更新环境，随后用 `uv run <命令>` 执行
  （例如 `uv run pytest -q`、`uv run python -m tenko --dry-run`）。
  requirements-entari.txt 是当前 uv.lock 的 pip 兼容快照，仅在无 uv 的环境
  作为替代安装路径使用；依赖变更时先改 pyproject.toml 再 `uv lock`，
  同步刷新 requirements-entari.txt（`uv export --format requirements-txt
  --no-hashes > requirements-entari.txt`），不要单独手改其一。
  服务器上的既有环境名为 `.venv-entari`，两种方式并存时以 uv 为准。

- 提交前至少执行：

  ```text
  ./.venv-entari/bin/ruff check tenko tests/tenko
  ./.venv-entari/bin/python -m pytest -q
  ```

- 只检查配置和连接信息、不启动网络服务：

  ```text
  ./.venv-entari/bin/python -m tenko --dry-run
  ```

- 全量钩子检查使用 `pre-commit run --all-files`。测试默认只收集
  `tests/tenko`，新增测试应放在该目录并保持测试可重复、无真实外部连接。

## 插件开发要点

1. 插件放在 `tenko/plugins/` 下，使用 Entari 原生插件生命周期和命令注册机制，
   并通过 `plugin.metadata` 声明名称、版本、作者和能力。
2. 对外命令统一使用 `/` 前缀。命令解析、帮助内容和权限检查应复用现有的
   command manager、`tenko.context` 以及 `tenko.host` 服务。
3. 平台动作通过宿主动作服务执行，先确认账号能力、目标可用性和权限，再处理
   失败结果；不要在插件中复制协议层调用或吞掉未知异常。
4. 配置从 `tenko.config` 读取，数据库操作通过 `tenko.db.repositories` 等现有
   抽象完成。新增状态需要明确持久化路径、迁移策略和测试覆盖。
5. 插件加载和卸载都必须释放自己创建的资源。渲染、网络和定时任务应遵循宿主
   生命周期，不在模块导入阶段启动副作用。

## 代码与提交规范

- Ruff 使用 88 列、双引号，并启用 E、F、W、UP 规则集；遵循现有命名、异常处理和
  类型标注风格。
- 先理解调用链和已有测试，再做局部修改；不要为了顺手清理而扩大变更范围。
- 提交消息使用 Conventional Commits，例如
  `fix(commands): correct command boundary handling`。
- 功能、修复、文档和清理尽量分成可独立验证的小提交。每个提交前运行 Ruff 和
  pytest，并在交接时说明已验证内容与剩余风险。

## 配置与安全

使用 `config/tenko.toml.example` 创建本地配置。真实 token、QQ 号、Git 凭据和
其他敏感信息不得写入版本库；测试和 dry-run 应使用占位值或隔离的临时路径。
