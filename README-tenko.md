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
| `tenko/host/plugins.py` 的 `PluginRuntime` | `core/models/saya_model.ModulesController` 和 Graia Saya | 发现 Tenko 插件目录项并转换为 Entari 导入名；加载、卸载、重载、元数据和开关全部交给 Entari 原生机制，只读兼容旧 `modules_data.json` 的状态，不写回旧文件 |

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

`PluginRuntime` 默认发现 `tenko/plugins/` 的直接子项，支持单个 `.py` 文件和带
`__init__.py` 的插件包，然后把它们转换为 Entari 的导入路径。插件模块不再实现
Tenko 自己的 `register(app, ctx)` 或 `unregister` 协议，而是直接使用 Entari 的
插件上下文、元数据和事件监听：

```python
from arclet.entari import MessageCreatedEvent, plugin


plugin.metadata(
    "Tenko 示例插件",
    version="0.1.0",
    description="使用 Entari 原生插件上下文注册消息处理器",
)


@plugin.listen(MessageCreatedEvent)
async def handle_message(event: MessageCreatedEvent):
    # 使用 Entari 的事件、依赖注入和插件生命周期能力
    ...
```

`plugin.metadata(...)` 是当前 Entari 版本的原生元数据声明，插件元数据不由
Tenko 读取或转换。运行时的 `load()`、`load_all()` 和 `reload()` 是异步方法：它们
调用 Entari 的 `load_plugin()`，重载按 Entari 的原生方式先 `unload_plugin()` 再
加载；`unload()` 直接调用 Entari 的 `unload_plugin()`。全局开关通过
`await runtime.enable(name)`、`await runtime.disable(name)` 或
`await runtime.set_enabled(name, enabled)` 委托给 Entari，不在 Tenko 中维护第二份
插件生命周期状态。

传入旧 `modules_data.json` 路径后，适配层只读取其 `modules` 下的 `available` 和
全局 `switch`，并将明确的旧状态映射到 Entari 的 `enable_plugin()` /
`disable_plugin()`；旧模块名 `modules.required`、`modules.self_contained` 和
`modules.third_party` 作为兼容查找名保留。群 ID 对象中的 `switch` 仍可通过
`is_enabled()` 查询，但不会把单个群的旧开关错误地转换成整个 Entari 插件的全局
禁用。旧文件始终保持只读。

### 第二阶段校验

继续使用独立 Entari 环境运行：

```bash
.venv-entari/bin/ruff check tenko tests/tenko
.venv-entari/bin/python -m pytest tests/tenko
```

`tests/tenko/test_accounts.py` 覆盖注册/注销、可用性和多账号路由；
`tests/tenko/test_perm.py` 覆盖权限矩阵、数据库 mock、黑名单和群等级；
`tests/tenko/test_plugins.py` 覆盖目录形状发现、Entari 原生生命周期委托、旧状态到
原生全局开关的映射、兼容查找名、群级旧开关查询和旧状态只读。测试 mock Entari
插件机制，使用临时目录，不会启动 NapCat、修改旧状态文件或部署服务。

## 第四阶段：必需插件迁移

第四阶段建立在 Tenko 协议闭环和第二阶段宿主子系统之上，把旧
`modules/required/` 中与基础运行有关的插件迁移到 `tenko/plugins/`。每个插件都
使用 Entari 原生的 `plugin.metadata`、`plugin.listen` 或 `command.on`；命令参数由
Alconna 的 `Args`、`Option` 和 `Query` 注入，消息使用 Satori 元素构造，不再引入
Graia 的 Listener、Twilight、Depend、Waiter 或 Ariadne `MessageChain`。

运行时在启动 Entari 前调用 `Entari.ensure_manager()`，随后由
`PluginRuntime.load_all()` 发现并加载 `tenko/plugins/`。因此插件的命令、事件监听和
生命周期都会进入同一套 Entari 原生分发链。当前 Entari 版本为 0.18.6，其
`PluginMetadata` 构造器没有 `default_switch` 字段；各插件在原生元数据声明完成后
保留 `metadata.default_switch = True` 兼容标记，供 `tenko/host/plugins.py` 的旧状态
适配和检查工具使用。

### 已迁移插件与旧实现对应关系

| 新插件 | 对应旧实现 | 本阶段迁移内容与边界 |
| --- | --- | --- |
| `tenko/plugins/perm_manager` | `modules/required/perm_manager` | 复用 `MemberPerm`、`GroupPerm`、`GroupSetting` 的权限管理、查询和成员权限同步；使用 `PermissionChecker` 做统一权限检查。成员加入、退群和管理员角色变化分别映射为 `GuildMemberAddedEvent`、`GuildMemberRemovedEvent`、`GuildMemberUpdatedEvent`。OneBot/Satori 当前无法确认的成员管理能力保留 `InternalEvent` 日志，并标记“待 NapCat capability 确认”。 |
| `tenko/plugins/helper` | `modules/required/helper` | 使用 Entari/Alconna 当前注册命令表生成帮助和编号详情，不复制旧的文本解析或图片菜单生成逻辑。 |
| `tenko/plugins/group_manager` | `modules/required/group_manager` | 仅提供 `群设置` 的群设置只读查询，读取旧 `GroupSetting`、`GroupPerm` 表；禁言、解禁、撤回、加精、全体禁言及邀请等平台动作留给第⑦步 capability-aware service。 |
| `tenko/plugins/status` | `modules/required/status` | 以 `-bot`/`状态` 命令提供文本状态查询，报告当前会话和已注册 Entari 插件数量；不再依赖旧的进程监控、图片渲染或 Ariadne 对象。 |
| `tenko/plugins/exception_catcher` | `modules/required/exception_catcher` | 订阅 Entari 全局 `ExceptionEvent`，按错误哈希冷却并向 Entari 配置的 superusers 发送 Satori 文本报告；不复制旧的 Graia 异常注入和图片报告路径。 |

权限插件的数据库写入仍只发生在明确的权限管理命令中；状态查询、帮助查询和群设置
查询路径不会创建或更新旧表。未迁移的群管理平台动作不会注册为“看似可用”的命令，
避免在没有 capability 确认时产生误操作。五个插件各自有触发路径和权限/过滤路径的
单元测试，实际测试会通过 `.venv-entari` 的 `load_plugin()` 验证元数据、命令登记和
原生卸载。

第四阶段校验命令仍为：

```bash
.venv-entari/bin/ruff check tenko tests/tenko
.venv-entari/bin/python -m pytest tests/tenko
```

## 依赖来源

- [Entari](https://github.com/ArcletProject/Entari)
- [Satori Python SDK](https://github.com/RF-Tar-Railt/satori-python)
- [OneBot 11 反向 WebSocket 约定](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)
