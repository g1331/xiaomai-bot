# CLAUDE.md

Tenko 是一个基于 Entari、Satori 和 OneBot 11 的 QQ 群管理 bot。

开始修改前请先阅读 [AGENTS.md](AGENTS.md)，其中包含项目结构、开发命令、插件
约定、测试要求和提交规范。

## 常用命令

```text
./.venv-entari/bin/ruff check tenko tests/tenko
./.venv-entari/bin/python -m pytest -q
./.venv-entari/bin/python -m tenko --dry-run
```

## 实现约定

- 插件使用 Entari 原生生命周期和命令注册机制，所有对外命令使用 `/` 前缀。
- 账号、权限、功能开关、限流、升级和平台动作优先复用 `tenko/host/` 中的服务。
- 配置使用 TOML，数据库访问使用 `tenko/db/` 的现有抽象；不要把 token 或其他
  敏感值写入仓库。
- 修改保持局部，并在提交前执行 Ruff 和完整 pytest。
