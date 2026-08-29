# Tenko 第一阶段：Entari + Satori/OneBot 11 最小闭环

这一阶段在旧 Graia Ariadne 机器人旁边新增独立的 `tenko` 包，完成以下最小链路：

```text
NapCat 反向 WebSocket
        │
        ▼
Satori OneBot 11 adapter ──► Satori Server ──► Entari client
        ▲                                      │
        └──────── OneBot action ◄── 固定回复事件处理器
```

收到 OneBot 11 的群聊或私聊消息后，Tenko 会记录账号、会话类型、用户、文本和图片 URL。固定回复默认关闭；开启后，会通过 Satori protocol 发送 `Tenko 已收到消息。`（或配置的文案）。

## 边界与文件

- `tenko/connection.py`：连接层，组装官方 Satori Server、OneBot 11 反向适配器和 Entari 使用的内部 WebSocket。
- `tenko/events.py`：事件层，记录消息、过滤机器人自己的消息，并按开关发送固定文案。
- `tenko/context.py`：消息上下文层，统一 `account_id`、事件类型、群/私聊、文本和图片 URL。
- `tenko/config.py`：只使用 Python 标准库 `tomllib` 读取 TOML 配置。
- `tenko/runtime.py`、`tenko/__main__.py`：服务编排和入口。
- `tests/tenko/`：事件类型解析、上下文提取、回复开关和 OneBot action JSON 测试。

本阶段不加载或迁移旧的 `core/`、`modules/`、`utils/`，也不修改这些目录。没有实现业务插件、权限迁移、数据库迁移或消息等待器。

## 创建独立环境

旧 `.venv` 是 Graia 基线环境，不能与当前 Entari 依赖混装；`uv.lock` 也刻意保持不变。使用独立环境和已提交的完整依赖清单：

```bash
uv venv --no-project --python 3.11 .venv-entari
uv pip sync --python .venv-entari/bin/python requirements-entari.txt
```

核心直接依赖已在 `pyproject.toml` 的独立 `[dependency-groups]` 下的 `entari` 组中固定版本；`requirements-entari.txt` 进一步锁定了运行时、测试和 Ruff 所需的完整解析结果。当前清单按 Linux/Python 3.11 生成。

核心包版本如下：

| 包 | 版本 |
| --- | --- |
| `arclet-entari` | `0.18.6` |
| `satori-python-adapter-onebot11` | `0.5.0` |
| `satori-python-client` | `1.3.7` |
| `satori-python-core` | `1.3.9.post1` |
| `satori-python-server` | `1.3.7` |

## 配置 NapCat

先复制示例配置，并修改 token：

```bash
cp config/tenko.toml.example config/tenko.toml
```

默认 NapCat 反向 WebSocket 地址是：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

在 NapCat 的 OneBot 11 反向 WebSocket 配置中填写上述地址。若 Tenko 与 NapCat 不在同一台机器，把 `127.0.0.1` 换成 Tenko 可访问的监听地址；若配置了 `access_token`，NapCat 必须使用相同 token。OneBot 反向连接还需要 NapCat 发送 `X-Self-ID`，官方适配器会据此创建账号。

`[onebot]` 中的 `satori_*` 是 Tenko 内部使用的 Satori client/server 配置，不应填写为 NapCat 的反向 WebSocket 地址。`listen_host = "0.0.0.0"` 时，Tenko 会自动用 `127.0.0.1` 连接本机内部 Satori 服务；跨机器场景请显式设置 `satori_host`。

## 启动与验证

### Dry-run

Dry-run 只读取配置、打印 NapCat endpoint 和回复开关，不创建网络连接，执行后退出：

```bash
.venv-entari/bin/python -m tenko --dry-run
.venv-entari/bin/python -m tenko --config /path/to/tenko.toml --dry-run
```

### 运行闭环

```bash
.venv-entari/bin/python -m tenko --config config/tenko.toml
```

正常启动后会看到 Tenko endpoint 和固定回复开关日志。NapCat 连接成功、账号上线、断开以及等待重新连接都会出现在日志中；Satori client 也会在连接中断后自动重连。先保持 `send_replies = false` 可以只观察收包，不向真实群聊发送消息。确认收包正常后，设置：

```toml
[runtime]
send_replies = true
reply_text = "Tenko 已收到消息。"
```

此时每条来自其他用户的群/私聊消息都会发出一条固定回复；机器人自己发送的消息会被过滤，避免形成回环。按 `Ctrl-C` 停止进程。本阶段不提供后台守护、部署或自动启动配置。

### 测试与静态检查

使用独立解释器运行 Tenko 测试集，避免旧项目的 Graia 测试导入旧配置：

```bash
.venv-entari/bin/ruff check tenko tests/tenko
.venv-entari/bin/python -m pytest tests/tenko
```

测试不要求真实 NapCat：OneBot 11 原始事件类型使用 mock 数据，发送测试使用 mock WebSocket 和 action response，验证实际官方适配器发出的 action JSON。

## 第二阶段：宿主重写

第二阶段在不触碰旧 `core/`、`modules/`、`utils/` 和 `main.py` 的前提下，
为后续业务插件迁移建立三个 Tenko 宿主子系统：多账号注册表、权限协议包装和
插件装载运行时。它们位于 `tenko/host/`，只使用第一阶段的 Satori
`MessageContext` 和 Entari `Account`，不保存 Ariadne 对象，也不复用 Graia
的事件注入或 Saya channel 结构。

### 新旧职责对应

| Tenko 第二阶段 | 旧实现 | 迁移边界 |
| --- | --- | --- |
| `tenko/host/accounts.py` 的 `AccountRegistry` | `core/models/response_model/AccountController`，以及 `core/bot.py` 的账号生命周期部分 | 保存 `self_id -> satori.client.Account`、可用状态和群路由；群成员/群列表由宿主显式绑定，不调用 Ariadne API |
| `tenko/host/perm.py` 的 `Permission`、`PermissionRegistry`、`PermissionChecker` | `core/control.py` 的权限数值策略和 `MemberPerm`/`GroupPerm` 读操作 | 保留 `-1/0/16/32/64/128/256` 成员权限与 `0/1/2/3` 群等级；通过 `MessageContext` 返回 awaitable 布尔检查，不产生 `Depend` 或 `ExecutionStop` |
| `tenko/host/plugins.py` 的 `PluginRuntime` | `core/models/saya_model.ModulesController` 和 Graia Saya | 扫描 Tenko 插件目录，导入模块并调用 `register(app, ctx)`；只读兼容旧 `modules_data.json` 的开关字段，不写回旧文件 |

### A：多账号注册表

`AccountRegistry` 的注册、状态和路由操作均以 Satori `Account` 为对象：

```python
registry.register(account, available=True, groups=["10001"])
registry.set_available(account, False)
target = registry.select_for_context(context, source_id=stable_message_id)
```

群消息会从已绑定且可用的账号中选择；`random` 策略在传入 `source_id` 时遵循旧宿主
的 `round(source_id) % account_count` 规则，`deterministic` 策略则使用指定账号。
deterministic 账号离线时返回 `None`，不会静默换成另一账号。私聊沿用消息所属的
`context.account_id`，账号注销时会同时移除它参与的群路由。

### B：权限协议包装

`Permission` 和 `GroupPermission` 保留旧数值含义；`PermissionRegistry` 可承载
Tenko 启动配置或测试中的 master、BotAdmin、成员和群等级覆盖。常规检查通过
`PermissionChecker` 或模块级入口完成：

```python
checker = PermissionChecker(registry=permission_registry)
allowed = await checker.require_perm(context, Permission.GroupAdmin)
group_allowed = await checker.require_group_perm(context, GroupPermission.ActiveGroup)
```

当没有提供运行时注册表时，检查器在第一次确实需要数据库读取时才延迟导入旧
`core.orm.orm`；读取使用 `MemberPerm`、`GroupPerm` 的查询，不执行写入。群消息
上下文会携带 Satori `Member` 的 `member`、`admin` 或 `owner` 角色；全局黑名单
优先于群内角色。权限不足由 `require_*` 返回 `False`，由插件决定如何处理，不再
依赖 Graia 的事件注入异常。

### C：插件装载运行时

`PluginRuntime` 默认扫描 `tenko/plugins/` 的直接子项，支持单个 `.py` 文件和带
`__init__.py` 的插件包。插件只需要提供简单入口：

```python
def register(app, ctx):
    app.register_on_message(ctx)


def unregister(app, ctx):
    pass
```

运行时提供 `discover()`、`load()`、`unload()`、`reload()` 和 `load_all()`；被开关
过滤的插件不会执行导入或 `register`。插件元数据可用 `metadata.json` 中的
`default_switch` 指定默认状态。

传入旧 `modules_data.json` 路径后，运行时读取其 `modules` 下的 `available`、
群 ID 对象中的 `switch`，并兼容旧模块名及 `groups` 嵌套形式。`set_enabled()`
只建立当前进程内的覆盖；旧文件始终保持只读，因此第二阶段不会改变旧 Saya
宿主的运行数据。

### 第二阶段校验

继续使用独立 Entari 环境运行：

```bash
.venv-entari/bin/ruff check tenko tests/tenko
.venv-entari/bin/python -m pytest tests/tenko
```

`tests/tenko/test_accounts.py` 覆盖注册/注销、可用性和多账号路由；
`tests/tenko/test_perm.py` 覆盖权限矩阵、数据库 mock、黑名单和群等级；
`tests/tenko/test_plugins.py` 覆盖发现、加载/卸载、开关过滤、旧状态只读和重载。
测试使用临时目录和 mock 账号/数据库，不会启动 NapCat、修改旧状态文件或部署服务。

## 依赖来源

- [Entari](https://github.com/ArcletProject/Entari)
- [Satori Python SDK](https://github.com/RF-Tar-Railt/satori-python)
- [OneBot 11 反向 WebSocket 约定](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)
