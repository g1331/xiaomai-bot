# Tenko：Entari + Satori/OneBot 11 宿主闭环

Tenko 在旧 Graia Ariadne 机器人旁边提供独立的 `tenko` 包，当前闭环包括
Satori/OneBot 11 接入、Entari 原生插件、统一权限/动作服务、多账号群路由、群级功能
开关和命令限流：

```text
NapCat 反向 WebSocket
        │
        ▼
Satori OneBot 11 adapter ──► Satori Server ──► Entari client
        ▲                                      │
        └──────── OneBot action ◄── Tenko host services ◄── Entari plugins
```

收到 OneBot 11 的群聊或私聊消息后，Tenko 会记录账号、会话类型、用户、文本和图片
URL，并在宿主事件层维护有限长度的消息统计与取证环形缓冲。群消息在多账号同时在线
时按群策略只交给一个账号处理；命令进入 Entari 前统一经过群级功能开关和频率限制。
固定回复默认关闭；开启后，会通过 Satori protocol 发送 `Tenko 已收到消息。`（或配置
的文案）。

## 边界与文件

- `tenko/connection.py`：连接层，组装官方 Satori Server、OneBot 11 反向适配器和 Entari 使用的内部 WebSocket。
- `tenko/events.py`：事件层，在插件分发前执行调试白名单和禁言过滤，记录消息、收发统计、取证缓冲，并按开关发送固定文案。
- `tenko/context.py`：消息上下文层，统一 `account_id`、事件类型、群/私聊、文本和图片 URL。
- `tenko/host/accounts.py`：账号生命周期、群绑定、响应策略、禁言状态和管理账号候选。
- `tenko/host/actions.py`：Satori/OneBot 动作接缝、能力学习、失败分类和群发现。
- `tenko/db/`：官方 `entari-plugin-database` 的启动桥接、旧表同构模型和普通 repository。
- `tenko/host/features.py`、`tenko/host/ratelimit.py`：群级插件开关、维护状态和命令限流。
- `tenko/config.py`：只使用 Python 标准库 `tomllib` 读取 TOML 配置。
- `tenko/runtime.py`、`tenko/__main__.py`：服务编排和入口。
- `tests/tenko/`：事件类型解析、上下文提取、回复开关和 OneBot action JSON 测试。

Tenko 不加载或修改旧的 `core/`、`modules/`、`utils/` 和 `main.py`。当前 JSON 状态
文件仍是开关、限流黑名单和响应策略的临时持久化边界；成员权限、群权限和群设置已
通过官方数据库服务与 Tenko repository 接入 SQLite。

## 创建独立环境

旧 `.venv` 是 Graia 基线环境，不能与当前 Entari 依赖混装；`uv.lock` 也刻意保持不变。使用独立环境和已提交的运行依赖清单：

```bash
uv venv --no-project --python 3.11 .venv-entari
uv pip sync --python .venv-entari/bin/python requirements-entari.txt
```

核心直接依赖已在 `pyproject.toml` 的独立 `[dependency-groups]` 下的 `entari` 组中固定版本；`requirements-entari.txt` 提供运行时、测试和 Ruff 所需的解析结果。渲染链的 `playwright` 有意不锁旧版本，安装时取当前稳定版；当前清单按 Linux/Python 3.11 生成。

启用图片渲染前，需要安装 Playwright 浏览器运行时。推荐使用与 Tenko 相同的解释器执行：

```bash
./.venv-entari/bin/python -m playwright install chromium
```

Linux 部署机如果缺少 Chromium 系统依赖，可以在具备相应系统权限时使用：

```bash
./.venv-entari/bin/python -m playwright install --with-deps chromium
```

Playwright 会把浏览器放在自己的缓存目录；升级 `playwright` 后应重新执行浏览器安装命令。没有浏览器环境时保持 `[render].enabled = false`，Tenko 继续使用文本回退路径。

核心包版本如下：

| 包 | 版本 |
| --- | --- |
| `arclet-entari` | `0.18.6` |
| `satori-python-adapter-onebot11` | `0.5.0` |
| `satori-python-client` | `1.3.7` |
| `satori-python-core` | `1.3.9.post1` |
| `satori-python-server` | `1.3.7` |
| `psutil` | `>=5.9.8`（status 可选运行时依赖） |
| `jinja2` | `>=3.1.4`（RenderService 模板渲染） |
| `markdown-it-py` | `>=3.0.0`（RenderService Markdown 转换） |
| `playwright` | 当前稳定版（RenderService Chromium 截图） |

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

### Entari superusers（唯一权威来源）

Entari 0.18.6 的原生配置字段是“平台名称 → 该平台用户 ID 列表”的
`basic.superusers` 映射。Tenko 在自己的 `[entari]` 配置节中提供唯一权威来源：

```toml
[entari]
superusers = { onebot = ["YOUR_QQ_ID"] }
```

`onebot` 必须与账号的 Satori `platform` 值一致；ID 可以写成字符串或整数，Tenko
加载时会统一转换为字符串。运行时会在 Entari 初始化后、加载插件前将这项配置写入
`EntariConfig.instance.basic.superusers`，异常捕获插件因此可以向这些用户发送报告，
不需要另外维护 Entari 的 `entari.yml`。`PermissionChecker` 使用与 Entari 原生
`filter.superusers` 相同的 platform→ID 判定，并将命中者视为 `Permission.Master`。

### 数据库配置与旧库迁移（G1）

Tenko 使用 `entari-plugin-database==0.3.4` 提供的异步 SQLAlchemy 服务，v1 默认配置
为 SQLite + `aiosqlite`：

```toml
# 旧版测试群不可通过权限管理命令修改；留空表示不启用保护。
test_group = ""

[database]
url = "sqlite+aiosqlite:///./.tenko/tenko.db"
echo = false
create_table_at = "preparing"
```

`test_group` 是顶层配置项，不属于 `[database]` table。数据库文件和官方迁移状态
（`.entari/data/database/migrations_lock.json`）都属于运行数据，已加入忽略列表。
运行时会先加载官方 database 插件、注册 `tenko/db/models.py`，再加载 Tenko 插件；
官方服务在生命周期中初始化表并运行 Alembic 自动迁移。Tenko 的模型与旧
`core/orm/tables.py` 保持以下表名、列名和主键不变：`MemberPerm`、`GroupPerm`、
`GroupSetting`、`chat_record`、`keyword_reply`。其中 `MemberPerm` 仍使用
`(group_id, qq)` 复合主键，成员权限值域仍是 `-1/0/16/32/64/128/256`，群等级仍是
`0/1/2/3`。

旧 Graia 库与当前模型同构，因此优先停掉旧进程后直接复用旧 SQLite 文件：

```bash
# 只指定旧文件：不复制，直接对该文件建表检查并写入官方迁移 baseline
.venv-entari/bin/python -m scripts.migrate_tenko_db \
  --source /path/to/old-graia.db

# 如需复制到 Tenko 数据目录：目标存在时必须明确 --force
.venv-entari/bin/python -m scripts.migrate_tenko_db \
  --source /path/to/old-graia.db \
  --target .tenko/tenko.db
```

也可以不运行脚本，直接把 `[database].url` 指向旧文件，例如绝对路径
`sqlite+aiosqlite:////path/to/old-graia.db`，随后正常启动 Tenko。脚本不会删除旧文件，
默认也不会覆盖已有目标文件；请在复制前停止旧机器人并按需备份 SQLite 的伴随文件。
当前仓库不包含旧版真实数据库文件，因此本批次使用旧表结构 fixture 验证了五张表、
全部成员权限等级和复合主键的保留；真实部署仍需由运维按上面的路径执行一次迁移。

Satori/OneBot 的群号和用户号在 repository 边界必须是纯数字，并转换为旧列使用的
整数；非数字 ID 会得到明确的 `DatabaseIdentifierError`。数据库连接、官方插件或
session 工厂不可用时，repository 抛出 `DatabaseUnavailableError`：宿主权限读取回退
到旧默认权限和运行时群角色，群设置查询回退到 `ActiveGroup`、`random`、`default`
等旧默认值，并按群去重 warning；权限管理写操作返回“数据库暂不可用”提示，不会把
未写入伪装成成功。

`[debug].masters` 和 `[upgrade].superuser_ids` 在未显式配置时继承这份名单；显式配置
（包括显式空列表）优先覆盖继承。旧 `[runtime].superusers` 仅作为迁移读取入口，解析后
与 `[entari]` 共享同一份有效值，不再是独立名单。升级命令的继承关系也不改变其自身
命令权限用途。

### 开发调试模式（仅响应 master）

在真实环境测试时，可以开启开发调试模式，让 Tenko 只处理指定开发者产生的事件：

```toml
[debug]
enabled = true
# masters = ["123456789"]  # 省略时继承 [entari].superusers
```

`masters` 是开发者 QQ 号列表，建议始终写成字符串；显式填写后不再使用超管继承。
事件入口会把事件中的用户
ID 和白名单统一转换为字符串后比较，因此协议层返回整数 ID 时也不会因为类型
不同而漏过过滤。`enabled = false` 是默认值；省略整个 `[debug]` 配置节时，行为
与未启用调试模式相同。

过滤发生在 `tenko/events.py` 的 `MessageEventHandler.should_skip()`，并由
`MessageEventHandler.guard()` 包在 Entari 原生事件分发入口之前。因而群聊、私聊、
命令、普通消息以及由消息触发的插件/AI 处理都会一起受到限制；没有事件来源用户
的事件也不会在调试模式下放行。

启用调试模式但将 `masters` 留空时，Tenko 会把所有事件视为不在白名单并跳过，
同时记录 warning 日志。该配置会导致全静默，只适合在明确需要时使用；正常测试
应填写至少一个开发者 QQ 号。

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
| `tenko/host/accounts.py` 的 `AccountRegistry` | `core/models/response_model/AccountController`，以及 `core/bot.py` 的账号生命周期部分 | 保存 `self_id -> satori.client.Account`、可用状态和群路由；注册表本身不调用 API，账号上线后的群列表由 `ActionService` 发现后写入 |
| `tenko/host/perm.py` 的 `Permission`、`PermissionRegistry`、`PermissionChecker` | `core/control.py` 的权限数值策略和 `MemberPerm`/`GroupPerm` 读操作 | 保留 `-1/0/16/32/64/128/256` 成员权限与 `0/1/2/3` 群等级；通过 `MessageContext` 返回 awaitable 布尔检查，不产生 `Depend` 或 `ExecutionStop` |
| `tenko/host/plugins.py` 的 `PluginRuntime` | `core/models/saya_model.ModulesController` 和 Graia Saya | 发现 Tenko 插件目录项并转换为 Entari 导入名；加载、卸载、重载、元数据和开关全部交给 Entari 原生机制，只读兼容旧 `modules_data.json` 的状态，不写回旧文件 |

### A：多账号注册表

`AccountRegistry` 的注册、状态和路由操作均以 Satori `Account` 为对象：

```python
registry.register(account, available=True, groups=["10001"])
registry.set_available(account, False)
target = registry.select_for_context(context, source_id=stable_message_id)
```

群消息会从已绑定且可用的账号中选择；事件入口的 `random` 策略每条消息随机选择一
个账号，并缓存这条消息的选择，使多个账号收到同一消息时只有一个进入 Entari。
`deterministic` 策略使用指定账号；指定账号离线或在该群被禁言时返回 `None`，不会
静默换用另一账号。私聊沿用消息所属的 `context.account_id`，账号注销时会同时移除
它参与的群路由。单账号群仍走原账号，不增加额外路由行为。

### B：权限协议包装

`Permission` 和 `GroupPermission` 保留旧数值含义；`PermissionRegistry` 可承载
Tenko 启动配置或测试中的 master、BotAdmin、成员和群等级覆盖。常规检查通过
`PermissionChecker` 或模块级入口完成：

```python
checker = PermissionChecker(registry=permission_registry)
allowed = await checker.require_perm(context, Permission.GroupAdmin)
group_allowed = await checker.require_group_perm(context, GroupPermission.ActiveGroup)
```

当没有提供运行时注册表时，检查器在第一次确实需要数据库读取时才延迟导入
`tenko.db.repositories`；读取通过 `MemberPermRepository`、`GroupPermRepository` 完成，
不执行写入。数据库可用时已有记录优先，没有群记录时使用旧实现的
`ActiveGroup = 1` 默认值。如果数据库连接读取失败，权限层会把它视为正常的不可用
分支：群权限仍回退到 `ActiveGroup = 1`，成员权限回退到运行时注册表或 Satori 群角色，
命令继续执行；同一检查器对同一群只记录一次包含群 ID 和原因的 warning。权限不足由
`require_*` 返回 `False`，由插件决定如何处理，不依赖 Graia 的事件注入异常。

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
| `tenko/plugins/group_manager` | `modules/required/group_manager` | 提供 `群设置` 只读查询、邀请审批，以及通过 `tenko/host/actions.py` 发出的禁言、解禁、撤回、全体禁言、全体解禁、加精和踢出；退群仍只在宿主动作层保留扩展入口。 |
| `tenko/plugins/status` | `modules/required/status` | 以 `-bot`/`状态` 命令提供状态查询，默认在渲染启用且成功时发送 `status.html` 图片，否则返回文本；报告系统资源、进程运行信息、收发消息统计、在线账号和账号×群禁言状态，不依赖旧的 Ariadne 对象。 |
| `tenko/plugins/exception_catcher` | `modules/required/exception_catcher` | 订阅 Entari 全局 `ExceptionEvent`，按错误哈希冷却并向 Entari 配置的 superusers 发送包含上下文和最近消息的 Markdown 图片报告；渲染或投递失败时分别回退文本或落盘，不复制旧的 Graia 异常注入。 |

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

## 第④.5步：命令前缀与禁言感知路由

### 全局命令前缀

Tenko 的命令前缀配置位于 `[runtime] command_prefix`，默认值为 `/`：

```toml
[runtime]
command_prefix = "/"
```

实现选择的是 Alconna 原生的默认命名空间前缀，而不是在各个插件中重新解析
消息。具体接入集中在 `tenko/commands.py:configure_command_prefix()`：它设置
`arclet.alconna.config.default_namespace.prefixes`，所有插件构造的 `Alconna`
命令都会复制这一配置；跨迁移保留的旧顶层别名（例如 `/-公告`、
`/关闭全体禁言`、`/-开启`、`/-关闭`、`/-upgrade`）以及 helper/status 的旧别名
都使用 Alconna 原生 `shortcut(..., prefix=True)` 注册。

选择依据是当前独立环境中的实际源码（Alconna 1.8.44、Entari 0.18.6）：

- `arclet/alconna/core.py:120-147` 说明 `Alconna` 从命令参数或默认
  `Namespace.prefixes` 获取前缀；`core.py:154-156` 会把示例中的 `$` 展开为
  实际前缀。
- `arclet/alconna/config.py:23-30,116-144` 定义了命名空间的 `prefixes` 和
  全局默认命名空间。
- `arclet/alconna/manager.py:466-490` 的帮助收集使用命令的
  `header_display`，因此帮助列表会和解析使用同一前缀。
- Entari 的 `arclet/entari/command/provider.py:40-63,68-99` 会在命令解析前
  消费 `EntariConfig.instance.basic.prefix`；`command/plugin.py:55-67` 默认
  启用这一步，`config/model.py:85-93` 定义了该配置。若同时设置两层，`/` 会
  被消费两次，Alconna 将看不到它；nickname 也会绕过 `/` 规则。因此 Tenko 在
  同一个集中接缝中清空 Entari 的消息级前缀和 nickname 预处理，只保留 Alconna
  的严格命令头匹配。

这样裸词不会触发，`/帮助x` 和 `/ 帮助` 也不会被当成同一命令；参数本身由
Alconna 继续负责类型和范围解析，helper 对越界编号返回“编号不在范围内~”。

### 禁言感知的账号×群路由

禁言状态直接扩展现有 `AccountRegistry`，核心 API 为：

```python
registry.set_muted(
    account_id,
    group_id,
    muted: bool,
    *,
    until: datetime | None = None,
) -> None
```

`until=None` 表示持续禁言；带时区或不带时区的 `datetime` 都按其自身时间类型
比较。状态在 `is_muted()`、`mute_until()`、`accounts_for_group()` 和选路时惰性
检查，到期后自动从状态表移除并重新参与选路。`accounts_for_group()` 始终排除
当前群仍被禁言的账号；deterministic 策略的指定账号被禁言时返回 `None`，不会
静默换用其他账号。显式 `set_muted(..., False)` 会立即恢复该群选路。

如果群发送 action 成功，`ActionService.send_group_message()` 和固定回复处理器都会
惰性清除对应的过期/误判 `muted` 标记。被标记的账号仍允许精确的 `/解禁自己` 进入
群管理插件；该命令按群管理员权限执行 `duration=0` 的标准解禁动作，成功后清除
账号×群状态。除此之外仍保留 `until` 到期时的惰性恢复；状态查询命令会展示永久或
具体到期时间。

OneBot 11 的 action 失败回执由 `AccountRegistry.observe_send_failure()` 作为
明确接缝消费。Satori OneBot 11 适配器的实际调用链在
`satori/adapters/onebot11/reverse.py:111-128`：非 `ok` 回执会抛出
`ActionFailed`，其中保留 `status` 和 `retcode`；Tenko 仅在群发送 action 的
该接缝被调用且回执明确失败时设置禁言，不把普通网络异常误判为禁言。NapCat
具体 retcode/自身 `message_sent` 字段的组合仍待实测确认。

当前版本扫描了 `arclet/entari/event/base.py` 和
`satori/adapters/onebot11/events/notice.py` 的原生事件定义，没有发现可直接
表示“本账号在某群被禁言”的 Entari/Satori 事件，因此暂按“显式 `set_muted` +
群发送 action 失败回执感知”降级接入，没有静默忽略该平台差异。OneBot 适配器
对 `message_sent.group.normal` 的识别可见
`satori/adapters/onebot11/events/message.py:71-99`，但这不等同于禁言状态事件。

运行时在 `tenko/runtime.py` 通过 Satori `event_callbacks` 的原生回调列表包住
Entari 的 `handle_event`，再由 `tenko/events.py` 的 `MessageEventHandler` 做
调试白名单和账号×群判定。这样不在调试白名单的事件、或被禁言账号收到该群消息
或事件时，会在 Entari 发布到插件之前跳过，并记录 debug 日志；解除调试模式或
禁言到期后恢复正常。Satori `App` 的回调列表
和并发发布位置为 `satori/client/__init__.py:62-70,304-315`，Entari 原生事件
入口为 `arclet/entari/core.py:471-480`。

### 查询插件

`tenko/plugins/response_manager/` 注册以下当前群查询与管理命令：

- `/BOT列表 [群号]`：查看群绑定的全部账号、响应策略、在线状态和群内禁言状态；
- `/BOT群列表 [BOT账号]`：查看一个账号的全部已知群绑定及各群状态；不带账号
  时汇总所有账号；
- `/在线BOT [群号]`：查看全局或指定群的在线/可用比例，同时保留不可用账号
  的状态信息。
- `/设定响应 [random|deterministic]`：群管理员查看或设置当前群响应策略；群内
  不接受跨群参数；
- `/指定BOT <账号ID|清除>`：群管理员在当前群设置 deterministic 响应账号，或
  清除显式账号并恢复当前群绑定顺序的默认账号。

插件不导入旧 `modules/required/response_manager`；策略和 deterministic 账号由
`account_registry` 写入宿主启动时使用的 `.tenko/accounts.json`，响应策略同时尝试
同步 `GroupSetting`。数据库暂不可用时，账号状态文件仍保留本次策略修改。

## 批次 C：平台动作层与公告迁移

### capability-aware action service

`tenko/host/actions.py` 的 `ActionService` 是管理动作的唯一宿主入口。插件只传递
群、成员、消息和业务时长，不拼接 OneBot JSON，也不直接调用 OneBot action。标准
动作使用当前独立环境（`.venv-entari`）中 `satori.client.protocol.ApiProtocol`
的原生方法，已安装的 OneBot 11 adapter 再负责协议转换：

| Tenko 服务方法 | Satori 原生方法 | OneBot 11 action / 说明 |
| --- | --- | --- |
| `mute_member(..., duration)` | `guild_member_mute` | `set_group_ban`；服务时长为秒，`0` 表示解禁 |
| `mute_group(..., enabled)` | `channel_mute` | `set_group_whole_ban`；全体禁言是独立 action，不复用单人禁言 action |
| `delete_message` | `message_delete` | `delete_msg`；消息 ID 按 OneBot 标准转为整数 |
| `kick_member` | `guild_member_kick` | `set_group_kick`；`permanent` 映射标准 `reject_add_request` |
| `send_group_message` | `send_message` | 由 adapter 的消息创建路径发出群消息，并接入发送失败观察点 |
| `set_essence`、`leave_group` | `protocol.internal` | NapCat/OneBot 扩展入口；具体失败回执仍“待第⑧步 NapCat 实测确认” |

OneBot 11 没有标准 capability 查询 action。`get_version_info` 只能识别实现方，
不能证明某个扩展 action 或当前账号权限可用；Satori 0.18.6/已安装 adapter 也没有
提供逐 action 的类型化 capability 列表。因此 Tenko 使用账号×能力的三态懒探测：
初始为未知，首次成功记为可用；真正的平台级不支持/失败才记为不可用，后续调用会
显式抛出 `ActionCapabilityUnavailable` 并记录日志。群内权限不足和连接/超时等暂态
失败只记录本次动作，不会把该账号在其他群的能力永久锁定。配置覆盖优先于学习结果，
示例为：

```toml
[onebot.capability_overrides."10001"]
member_mute = true
group_mute = true
group_essence = false
```

失败记录保留账号、逻辑能力、实际 action、`status`、`retcode`、`data`、`message`、
`wording` 和 `echo`，供日志和测试读取；群发送失败还会调用
`AccountRegistry.observe_send_failure()`，使账号×群禁言状态机继续生效。NapCat 官方
API 页面列出标准动作和扩展动作，OneBot 11 WebSocket 回执规范定义了
`status/retcode/data/echo` 字段；NapCat 实际失败 retcode 与 `message/wording` 组合
在本批次只作为结构化字段保留，具体组合“待第⑧步 NapCat 实测确认”。

协议依据：

- OneBot 11 [公共 API 定义](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)；
- OneBot 11 [反向 WebSocket 通信与回执](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)；
- NapCat [OneBot API 列表](https://napneko.github.io/onebot/api)；
- Entari [官方教程](https://arclet.top/tutorial/entari/)。

Entari 教程没有覆盖本批次所需的全部动作映射，动作方法名、参数单位、内部路由和
异常传递以安装环境 `.venv-entari` 的 `arclet.entari`、`satori` 和
`satori.adapters.onebot11` 实际源码确认；这一回退边界在宿主代码 docstring 中明确
标注为“按源码确认”。

### 群管理命令

`tenko/plugins/group_manager/` 的管理命令全部使用全局 `/` 前缀，并经过
`ActionService.authorize()`（内部调用 `PermissionChecker`）。它保留旧
`core.control.Permission` 的 `GroupAdmin=32`、`GroupOwner=64`、`BotAdmin=128` 和
`Master=256` 数值语义：

- `/禁言 [@成员|成员ID] [分钟] [-t <分钟>]`：默认 2 分钟，范围 `1..43200`；进入
  action service 后转换成标准秒数；
- `/解禁 [@成员|成员ID]`：也支持回复目标消息；
- `/全体禁言`、`/全体解禁`（旧别名 `/关闭全体禁言`）；
- `/撤回`：必须回复消息，使用 Satori `Quote.id`；
- `/加精 [消息ID]`：优先使用显式消息 ID，否则使用回复消息的 Satori `Quote.id`；
  `/设精` 是同一处理路径的旧命令别名；
- `/踢出 [@成员|成员ID]`：也支持回复目标消息。

目标为机器人自身或已知管理权限成员时，插件会在发出动作前拦截；平台返回的权限
错误仍会作为逐条动作失败返回，不会伪装成成功。管理动作遇到当前账号在目标群无
权限时，`ActionService` 会从同群在线账号中查找已知的 Administrator/Owner，按群
权限尝试其他账号；动作 capability 状态始终按账号维度记录，不跨群污染。

### announcement 迁移

`tenko/plugins/announcement/` 注册 `/公告 <功能名> <内容...> [-t <间隔分钟>]`
（旧别名 `/-公告`）。
它先读取宿主 `FeatureService` 的群×插件开关，再只读兼容旧状态中的
`modules -> groups -> switch`，按 `AccountRegistry` 的群路由每群选择一个可用账号，
然后通过 `ActionService.send_group_message()` 发送。每个群都会得到一个
`PushResult`，状态包括成功、功能未开启、账号不可用、账号在群内禁言、能力不可用和
动作失败；这些结果会汇总返回，避免静默丢弃目标。发送前的 `is_muted(account, group)`
检查与发送失败后的状态观察都使用现有账号×群禁言状态机。
推送开始时在发起群只报告本次评估的目标总数，完成时报告成功、失败和跳过数量；
群内不会列出群号或平台错误。Master 发起时，全部群号和逐群状态仍通过私聊诊断
消息发送。

旧仓库事实与任务描述存在一处边界差异：当前 `core/orm/tables.py` 没有群-功能开关
表，旧实现实际由 `ModulesController` 维护 `modules_data.json`。因此本批次继续沿用
该 JSON 契约的只读适配；权限和群设置的五张旧表则由 `tenko/db/` 的同构模型与
repository 负责，不导入旧 ORM，也不调用会写回旧状态的控制器方法。

### 批次 C 校验

新增测试覆盖 action service 的标准/扩展动作和 OneBot 失败回执、能力锁定与显式覆盖；
group_manager 的全局前缀、目标解析、时长边界、权限拦截和回复撤回；announcement
的开关/账号/禁言预检、逐目标推送、间隔、失败结果和权限拦截。插件目录中不包含裸
OneBot action 名称，所有平台动作都经过宿主服务。

```bash
./.venv-entari/bin/ruff check .
./.venv-entari/bin/python -m pytest tests/tenko -q
```

## 批次 D：宿主层正确性修复与 P1 缺口

本批次继续只修改 `tenko/`、`tests/tenko/`、`config/tenko.toml.example` 和本文件，
不改旧 `core/`、`modules/`、`utils/`。新增状态文件默认位于 `.tenko/`，目录由服务
在第一次需要写入时创建。

### 多账号唯一选路

账号上线后，`TenkoRuntime` 通过 `ActionService.get_group_list()` 发现该账号的群，
再写入 `AccountRegistry`。收到群消息时，`MessageEventHandler.guard()` 在 Entari
原生命令/事件分发前按群策略选路：

- `random`：从该群已绑定且在线、未处于有效 `muted` 状态的账号中随机选一个；同一
  消息的选择按消息 ID 缓存，多个账号同时收到该消息时只有选中账号继续分发；
- `deterministic`：只允许指定账号处理；指定账号离线或在该群被禁言时不回退到其他
  账号，相关事件跳过并记录 debug 日志；
- 单账号群和私聊保持原有路径。退群/被踢事件会主动解除账号×群绑定；消息触发的
  首次绑定仍保留，因此上线群发现失败或事件遗漏时不会阻断后续消息兜底。

### 群级功能开关与命令限流

`FeatureService` 负责群×插件的显式开关和插件全局维护状态，写入
`[features].state_path`（默认 `.tenko/features.json`）。未显式设置的群使用
`default_enabled`。`tenko/plugins/feature_manager/` 提供 `/开启 <插件编号或名称>`、
`/关闭 <插件编号或名称>`（旧别名 `/-开启`、`/-关闭`），要求当前用户达到 `GroupAdmin`；必须的宿主插件不可
关闭。命令归属由 `PluginRuntime` 从 Entari 当前命令注册表解析，事件入口统一在
插件回调之前拦截关闭的功能并提示开启方式，因此不需要每个插件重复装饰器。
公告插件同时读取该新开关和旧 `modules_data.json` 的只读兼容状态。

`RateLimitService` 负责用户×群的滚动窗口、冷却和临时黑名单，写入
`[ratelimit].state_path`（默认 `.tenko/ratelimit.json`）。默认窗口为 15 秒、每次
命令权重为 1、阈值为 24；达到阈值后默认冷却 5 秒并加入 300 秒临时黑名单，均可
在配置中调整。群管理员达到 `override_permission`（默认 32）时跳过限流。开关检查
优先于限流，二者都在 Entari 命令执行前完成。

### 超管收敛与权限桥接

`[entari].superusers` 是唯一权威名单，格式与 Entari 的
`basic.superusers` 相同。`[debug].masters` 和 `[upgrade].superuser_ids` 缺省时继承
它；显式配置（包括 `[]`）覆盖继承。旧 `[runtime].superusers` 只为旧配置提供迁移
读取，解析后成为同一份有效名单。

运行时将名单写入 `EntariConfig.instance.basic.superusers`。`PermissionChecker` 按
平台和用户 ID 复用 Entari 原生 `filter.superusers` 的判定，命中者直接获得
`Permission.Master`，优先于数据库和普通群角色查询。

### 动作失败分类与禁言恢复

`ActionService` 只把真正的平台级不支持/失败学习为账号×能力不可用；群内权限不足、
连接错误和超时只记录当前动作，不会锁死该账号在其他群的能力。群管理动作的当前
执行账号权限不足时，会从同群在线账号中寻找已知的 Administrator/Owner 并重试；
候选账号状态和 capability 都按账号维度维护。

群发送失败产生的 `muted` 状态仍按账号×群维护并支持到期惰性清理。后续群消息成功
发送时会清除对应状态；需要立即恢复时，群管理员可发送 `/解禁自己`，该命令使用
标准 `duration=0` 动作并在成功后清除当前账号×群标记。`/BOT列表`、`/BOT群列表`
会展示在线/离线和禁言到期信息。

### 响应策略持久化与启动群发现

`AccountRegistry` 把每个群的 `response_type` 和 `deterministic_account` 写入
`[accounts].state_path`（默认 `.tenko/accounts.json`），`TenkoRuntime` 在账号上线
前配置并恢复这份状态；之后的群绑定会保留已恢复策略。响应查询命令读取同一个
注册表，因此显示的是恢复后的值。

账号进入 `ONLINE` 生命周期后，运行时调用 `ActionService.get_group_list()`，该服务
通过 Satori `guild_list()` 进入 OneBot adapter，再由 adapter 调用标准
`get_group_list` action，将返回的群 ID 全量绑定到该账号。拉取失败只记录 warning，
不会阻止账号上线；消息入口的绑定逻辑继续作为兜底。OneBot 11 的 action 名和无参
群列表返回约束见[公共 API 定义](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)。

### 批次 D 校验

新增测试覆盖随机/指定选路及在线、离线、禁言组合；群开关的持久化、命令拦截和命令
格式；限流阈值、冷却、恢复和黑名单重启恢复；超管继承/覆盖与原生 Master 桥接；
动作权限失败、平台失败、跨群隔离和管理账号回退；禁言自动/手动恢复；响应策略
重启恢复及上线群列表 mock 发现。

```bash
./.venv-entari/bin/ruff check .
./.venv-entari/bin/python -m pytest tests/tenko -q
./.venv-entari/bin/python -m tenko --dry-run
```

## 批次 E：功能补全

本批次继续只修改 `tenko/`、`tests/tenko/`、`config/tenko.toml.example` 和本文件，
不改旧 `core/`、`modules/`、`utils/`。事件名、请求字段和审批 API 均以当前
`.venv-entari` 中的 Entari 0.18.6、Satori OneBot 11 adapter 源码为准。

### status 文本状态

`/状态`（也保留 `/-bot -t`）现在输出以下轻量信息：

- `psutil` 采集的 CPU、内存、磁盘和网络 IO；
- Bot 进程启动时间、运行时长和 RSS；
- 宿主事件层的收发总数、最近 60 秒收发速率和活跃群数；
- `AccountRegistry` 中的在线账号，以及每个账号×群的禁言状态。

项目声明已经包含 `psutil>=5.9.8`；独立环境安装时可执行：

```bash
uv pip install --python .venv-entari/bin/python psutil
```

如果运行环境没有 `psutil`，状态命令仍返回会话、消息、账号和进程信息，只跳过
“系统”资源段。渲染服务关闭、浏览器不可用、模板失败或超时都会回退为同一份文本状态；
`-t`/`--text` 可显式跳过图片渲染。

### 退群和被踢感知

当前 OneBot 11 adapter 的实际映射是：

- `notice.group_decrease.leave`、`notice.group_decrease.kick` →
  `EventType.GUILD_MEMBER_REMOVED`；
- `notice.group_decrease.kick_me` → `EventType.GUILD_REMOVED`。

Tenko 在宿主层监听这两个 Satori 事件。当事件中的成员 ID 命中已注册账号的
`self_id` 时，只解除该账号在当前群的绑定，保留它的其他群；普通成员退群不会改变
账号路由。解绑复用 `AccountRegistry.unbind_group()`，因此 deterministic 指定账号
被移除时仍由注册表回退到剩余成员的首个账号，空群则清理群路由状态。若是被踢事件，
宿主会在具备 `guild_get` 且账号可用时通过 `ActionService` 做一次群信息确认；确认失败
只记 debug 日志，不阻塞解绑。

如果 OneBot adapter 在构造退群事件时所需的补充查询失败，adapter 会保留原始
`_type`/`_data` 并发布 `EventType.INTERNAL`；宿主也会按上述已核实的三个 raw event
类型读取 `group_id`/`user_id`，因此不会把“已被踢后无法查询成员信息”误当成无事件。

消息入口的首次绑定兜底仍保留，所以语义是“退群/被踢事件感知 + 消息触发兜底”，而
不是只依赖下一条消息才发现状态变化。

### 群邀请审批

当前适配器把 `request.group.invite` 转换为 Satori `GuildRequestEvent`，并保留请求
`flag` 为 `event.message.id`；审批使用安装版本提供的 `protocol.guild_approve()`，
由 adapter 转换为 OneBot `set_group_add_request` 的 `sub_type=invite`。因此 Tenko
不会虚构 `get_friend_requests` 轮询或不存在的事件名。

行为与旧群管理插件对齐：邀请人拥有 `BotAdmin`（包括 `Master`）时自动同意并使用
“已同意您的邀请~”备注；其他邀请进入进程内待审队列，默认等待 1 小时后以
“拒绝了你的入群邀请!” 自动拒绝。待审通知发送给 `[entari].superusers`，通知不可达
时队列仍保留。

审批命令使用全局 `/` 前缀：

- `/同意邀请 <请求ID>`（别名 `/同意`）：目标群内的 `GroupAdmin`，或群外/私聊的
  `Master`；
- `/拒绝邀请 <请求ID> [理由]`（别名 `/拒绝`）：同上；省略理由时使用旧版拒绝备注；
- `/待审邀请`：仅 `Master` 查看当前进程待审列表。

OneBot adapter 当前还把 `request.group.add` 映射成 `GUILD_MEMBER_ADDED` 通知，而不是
`GuildMemberRequestEvent`；本批次只对实际可观测的 bot 邀请请求注册审批监听，不把该
通知误当成另一个待审请求。

### 异常取证

`exception_catcher` 的报告现在包含发生时间、完整异常类型和 traceback、当前会话的
账号/平台/群/用户/消息摘要，以及宿主 `events.py` 环形缓冲中的最近消息。缓冲默认
保留 10 条，可在配置中调整：

```toml
[exception]
message_buffer_size = 10
evidence_dir = ".tenko/exceptions"
```

环形缓冲使用固定 `maxlen`，超限时先进先出淘汰，不把消息无限留在内存中。报告先
发送给 `EntariConfig.instance.basic.superusers`；没有可投递 superuser，或任一投递
失败时，会在 `evidence_dir` 创建带时间和错误哈希的 `.log` 文件，并同时记录本地
日志，避免异常证据只存在于一次失败的发送动作中。

### 图片渲染服务（G2-P1）

`tenko/render.py` 中的 `RenderService` 由 `tenko/plugins/render` 这个 Entari
library plugin 提供。该插件在自己的加载上下文中调用官方 `add_service()` 注册服务；
`TenkoRuntime` 只把 `[render]` 配置传给插件，不再手动构造或加入 Launart 组件。浏览器
在准备阶段启动、宿主停止时关闭，单次渲染使用独立 BrowserContext，完成后立即关闭。
默认超时为 10 秒、viewport 宽度为 800、JPEG quality 为 85、并发上限为 2。服务启动
失败不会阻断 Tenko 启动。

`status` 命令和 `exception_catcher` listener 直接在处理函数参数中声明
`RenderService`，由 Entari 的服务 Provider 注入；调用 `render_or_none()` 时显式传入
这个实例和目标方法。这样服务的注册、依赖跟踪和卸载都属于 Entari 原生插件生命周期，
不会再通过模块级单例获取服务。直接调用 `send_error_report()` 的测试或工具代码若没有
经过 listener 注入，可以显式传入 `render_service=None`，此边界只表示不进行图片增强，
不会建立第二套服务获取机制。

配置项位于 `config/tenko.toml.example`：

```toml
[render]
enabled = false
timeout = 10.0
width = 800
quality = 85
```

模板固定从 `tenko/templates/<name>.html` 查找。本批次的占位模板是
`tenko/templates/status.html` 和 `tenko/templates/markdown.html`，后续视觉批次可以直接
替换这两个文件，不需要修改服务 API。status 使用 `build_status_data()` 产生以下约定的
context：顶层 `title`、`content`、`lines`、`plugin_count`、`chat_type`、`detailed`、
`current_group_mute`、`project_address`、`version_details`、`online_bots`、
`active_groups`；`metrics` 包含 `received_count`、`sent_count`、`received_rate`、
`sent_rate`；`process` 包含 `start_time`、`uptime_seconds`、`uptime`、`rss`、
`rss_display`；`resources` 为 `None` 或包含 CPU、内存、磁盘和网络原始数值的 mapping。
异常模板的 `content` 是 markdown-it 生成的 HTML，模板需使用安全渲染；原始报告在
`source` 字段中保留。

### 批次 E 校验

```bash
./.venv-entari/bin/ruff check tenko tests/tenko
./.venv-entari/bin/python -m pytest tests/tenko -q
./.venv-entari/bin/python -m tenko --dry-run
```

## 批次 F：动作能力误判恢复与安全错误提示

本批次只修改 `tenko/`、`tests/tenko/` 和本文件，继续不改旧 `core/`、`modules/`、
`utils/`。重点是区分“账号确实不支持某个 action”和“账号在当前群暂时没有足够权限”：
后者不能把账号级 capability 锁死。

### NapCat 权限失败与 capability 学习

NapCat 当前 `SetGroupBan` action 的源码注释明确记录：没有群管理员权限时，底层结果
可以是 `120101005`，错误名为 `ERR_NOT_GROUP_ADMIN`，见
[`SetGroupBan.ts`](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/group/SetGroupBan.ts)。
OneBot 11 的 WebSocket action 失败回执使用 `status`、`retcode`、`data` 和 `echo` 等
字段；适配器也可能把平台的 `errMsg` 放进 `message` 或 `wording`，所以 Tenko 同时
兼容 `"1200: {'status': 'failed', ...}"` 这种 `ActionFailed` 文本和 mapping 参数，
依据见 [OneBot 11 WebSocket 通信约定](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)。

`ERR_NOT_*` 以及 `*_ADMIN`/`*_OWNER` 是识别规则，而不是声称 NapCat 发布了一份稳定
的完整符号枚举；当前也兼容 `ERR_NOT_GROUP_ADMIN`、`ERR_NOT_GROUP_OWNER` 和
`ERR_NOT_FRIEND` 这几个已知/兼容名称。权限类 action 失败只记录失败和日志，不学习
`capability=False`；如果历史版本已经错误学习为 `False`，收到新的权限类失败时会清除
该学习值，下一次动作可以重新探测。动作成功仍会通过 `_remember_success` 恢复为可用。

超管可以使用以下命令清除指定账号的全部“学习状态”（不改变显式 capability 覆盖）：

```text
/重置能力              # 重置当前处理账号
/重置能力 <账号 ID>    # 重置指定账号
```

命令只授予 `Permission.Master`，返回实际清除的能力条数。它适用于升级、权限调整或
历史错误状态后的人工恢复，不会绕过下一次真实 action 探测。

### 群内提示与私聊取证

群管理和公告的动作失败统一经过共享格式化工具。群内只返回分类后的短提示：本地权限
拒绝为“权限不足”，能力不可用为“该账号暂不支持此操作（或已被临时限制），已通知开发者”，
检测到平台权限失败为“该账号在此群没有管理员权限”，其他平台执行失败为“平台操作失败，
已通知开发者”。群内提示不会输出 `retcode`、`echo`、`wording`、`ActionFailed` 原文或
traceback。

完整 `ActionFailure` 字段（账号、能力、action、status、retcode、data、message、
wording、echo、错误类型、原始详情）和 traceback 复用 `exception_catcher` 的取证报告，
通过 `[entari].superusers` 对应平台的私聊通道发送；发送失败会继续保留结构化日志和
`[exception].evidence_dir` 本地证据，不阻塞群内错误提示。公告逐群发送也使用同一套
格式化和报告路径，避免多个插件各自暴露平台回执。

## 第⑦步：宿主升级系统（替代旧 `auto_upgrade`）

本步只升级 Tenko 宿主自身，不分发 `tenko-plugins` 外部插件。实现位于
`tenko/host/updater.py`，管理命令位于原生 Entari 插件
`tenko/plugins/updater/`；旧 `modules/required/auto_upgrade/` 保持不变，也不再被
Tenko 运行时加载。

### 旧实现的实际行为基线

实现前先读取了旧插件和相关配置，基线不是只根据旧插件名称推断出来的：

- `utils/self_upgrade.py` 从当前 Git 工作树推导 `origin`，通过 GitHub 的当前分支
  commit/compare 接口查找更新，真正执行时调用 `origin.pull()`；成功消息只说明
  更新将在重启后生效，没有制品校验、独立版本目录或回滚副本。
- `modules/required/auto_upgrade/__init__.py` 监听群消息中的 `-upgrade`，经过
  功能开关、频率、群和 Master 权限检查；同时注册 24 小时一次的定时检查。
- 检查到更新时，旧实现只在 `config.test_group` 通知，展示最多三条 commit 的
  SHA/消息，并发送 GitHub OpenGraph 图片；Master 需要在 30 秒确认窗口中回复
  `y/yes` 才会在后台线程执行 `git pull`。
- 没有更新、没有 Git、GitHub/网络不可用和 pull 失败分别记录日志或返回失败提示；
  pull 失败不会自动恢复到 pull 前的完整代码状态。
- 旧配置是 `core/config.py` 中的布尔 `auto_upgrade`，示例值为 `true`。它只控制
  自动提示，不提供 stable/预发布通道、配置兼容版本、制品哈希、健康检查或回滚策略。

这些行为中“周期检查、人工触发、更新提示、Git 来源和失败可见”被保留为场景，
而 `git pull` 原地覆盖、旧 `-upgrade` 文本协议、OpenGraph 图片通知和旧布尔配置
不会迁移。新系统用 `/检查更新`、`/升级`、`/回滚` 以及结构化审计替代它们。

### 十个设计环节与决策

| 环节 | 实现 | 决策理由 |
| --- | --- | --- |
| 1. 版本发现 | `Version` 实现严格 SemVer 比较；`VersionSource` 可插拔；内置 `GitTagSource`、`GitHubReleaseSource`，并保留 `UrlManifestSource` 扩展点 | 版本发现与制品获取分离，新增源不需要改升级状态机；非法版本不会参与选择 |
| 2. 更新通道 | `stable` 排除 SemVer 预发布版本，`prerelease` 同时允许正式版和预发布版；多源取最高候选 | 通道过滤发生在源和最终选择两层，避免某个源遗漏过滤导致稳定实例误装预发布版 |
| 3. 制品获取与校验 | Git tag 浅克隆后比较完整 commit SHA；GitHub Release/manifest 下载 zip/tar 并强制比较 SHA-256；缺少强校验或校验失败立即停止 | tag、文件名和版本号都不是内容完整性证明；校验失败不能进入 staging 之后的步骤 |
| 4. 配置兼容性 | release 元数据和 `upgrade-manifest.json` 均可声明最低配置版本，取两者较高值，在提升制品前比较 | 兼容性阻断发生在原子切换之前，不把不可兼容配置带入新进程 |
| 5. 原子切换 | 制品先进入随机 staging 目录，再提升到 `versions/`；`active.json` 使用临时文件加 `os.replace` 替换 | 不覆盖当前项目根目录，外部启动器只读一个完整指针，不会读到半写入状态 |
| 6. 健康检查 | 切换前默认检查 `tenko/__init__.py` 和 Python `compileall`，也可配置一次性 `health_command`；切换后检查新进程存活并重复健康检查 | 默认检查不依赖真实 QQ/网络；部署可用最小启动命令补足真实运行时检查 |
| 7. 失败回滚 | 首次激活时把当前代码复制为 `versions/*-baseline-*`；切换后健康检查失败则恢复旧 active 指针并终止新进程 | 回滚依赖完整旧副本，而不是尝试从新代码反向修补旧代码 |
| 8. 配置与数据保留 | 代码版本目录与配置/数据目录分离；当前代码快照明确排除配置、数据、虚拟环境和升级状态目录；新进程通过同一配置/数据路径启动 | 升级不清理或覆盖用户配置和数据，候选制品也不能携带一份同名配置覆盖外部配置 |
| 9. 审计 | `audit.jsonl` 追加 JSON Lines，记录 UTC 时间、动作、当前/目标版本、结果及错误/路径/校验方式 | 检查、下载、安装请求、成功安装和回滚失败都能按记录重建结果；写入时 flush、fsync |
| 10. 手动/自动策略 | `check` 只检查提醒，`download` 自动下载并准备，`install` 自动生成外部安装接管记录；默认 `check` | 同一控制平面覆盖保守提醒、自动预取和自动安装三档；`install` 仍不在当前进程热替换 |

### 版本源与外部事实

GitHub 源使用官方 Releases API 的 repository releases endpoint，读取
`tag_name`、`prerelease`、`draft` 以及资产的 `browser_download_url` 和 `digest`；
官方接口文档见 [List releases](https://docs.github.com/en/rest/releases/releases#list-releases)。
资产没有可验证的 SHA-256 digest 时，GitHub 源仍可用于检查，但不能进入获取/安装阶段。

插件接入使用 Entari 已有的原生 `command.on`、`plugin.listen(Ready)` 和
`scheduler.schedule`，没有再创建 Tenko 自己的事件总线或调度线程；生命周期、命令
和插件能力以 [Entari 官方教程](https://arclet.top/tutorial/entari/index.html) 为准。
`VersionSource` 是升级领域本身的隔离接口，不是对 Entari 插件系统的包装层。

### 状态目录与外部重启接缝

配置的 `install_root` 下会产生以下状态；代码版本和控制记录均不放回当前项目根目录：

```text
.tenko/upgrades/
├── versions/
│   ├── 3.0.1-baseline-<随机后缀>/
│   └── 3.1.0-<commit 或随机后缀>/
├── staging/
├── active.json
├── previous.json
├── pending.json
├── handoff.json
└── audit.jsonl
```

`/升级` 的动作顺序是“发现 → 获取 → 强校验 → 配置兼容性 → 切换前健康检查 →
写入 pending → 写入 activate handoff”。它不会在当前 Python 进程中导入候选目录，
也不会替换 `sys.modules` 或覆盖正在运行的源码。这样处理是因为升级执行器与被升级
对象可能是同一进程；原地热替换会让已注册的事件处理器和新旧依赖混用。

实际部署需要一个稳定的外部启动器或 supervisor 接管 handoff：

1. 停止旧 Tenko 进程，并从仍然可用的稳定启动代码调用
   `UpgradeManager.apply_handoff()`。
2. `activate` 路径以一次原子 `active.json` 替换作为切换点，再由配置的
   `launch_command` 在候选版本目录启动新进程。
3. `SubprocessLauncher` 不使用 shell，并把解析后的 `TENKO_CONFIG_PATH`、
   `TENKO_DATA_DIR` 和 `TENKO_UPGRADE_ROOT` 传给新进程；因此候选版本改变工作目录
   后仍会使用同一份用户配置、数据和升级状态。
4. 新进程存活和健康检查通过后保留 `previous.json`；失败则终止新进程、恢复旧
   active 指针并写入 rollback 审计。`rollback` handoff 使用同一接缝回到
   `previous.json`，成功后交换 active/previous 指针。

自定义 supervisor 必须提供等价的“停旧进程 → 调用 `apply_handoff()` → 传递三个
绝对路径环境变量/参数 → 观察健康结果”流程；本批次不伪造一个无法适配部署环境的
守护进程脚本，也不把重启责任塞进 Entari 事件处理器。

### 配置与命令

`config/tenko.toml.example` 的 `[upgrade]` 是独立于旧 `auto_upgrade` 的配置节：

```toml
[upgrade]
enabled = true
source = "git_tag"             # git_tag / github_release / manifest
repository = "."
github_repository = "owner/repository"
channel = "stable"             # stable / prerelease
policy = "check"               # check / download / install
config_version = "1.0.0"
install_root = ".tenko/upgrades"
config_path = "config/tenko.toml"
data_dir = "data"
health_command = []
launch_command = []
check_interval_hours = 24
superuser_ids = [123456]
```

三个命令使用全局 `/` 前缀，且只允许 `superuser_ids` 中被映射为
`Permission.Master` 的用户：

- `/检查更新`：执行版本发现并返回当前/候选版本、通道和来源；不下载制品。
- `/升级`（旧别名 `/-upgrade`）：执行一次检查，准备并校验候选版本，检查通过后
  生成外部 `activate` handoff；返回制品目录和 handoff 路径，不热替换当前进程。
- `/回滚`：检查是否存在上一可用版本，生成外部 `rollback` handoff；不存在时
  返回可见失败并写入审计，不伪造成功。

`Ready` 事件会按策略执行一次，之后由 Entari 原生调度器按
`check_interval_hours` 执行；默认 24 小时对应旧版周期检查场景。策略为 `check` 时
周期任务只产生提醒和审计，`download` 会自动准备，`install` 只自动生成外部接管
记录，最终进程切换仍由稳定启动器完成。

### 旧 `auto_upgrade` 行为覆盖对照

| 旧行为 | 新系统处理 | 是否保留 |
| --- | --- | --- |
| GitHub 当前分支 commit/compare 检查 | Git tag 源比较版本和 commit SHA；GitHub 源改为官方 Release + asset digest；manifest 可扩展 | 场景保留，数据协议升级 |
| 24 小时自动检查 | `Ready` + Entari 原生 scheduler，周期可配置且默认 24 小时 | 保留 |
| `-upgrade` 群消息触发 | 全局 `/升级`（兼容 `/-upgrade`），仅超级用户，先准备再生成外部接管记录 | 能力保留，命令和权限收紧 |
| `config.test_group`、最多三条 commit、OpenGraph 图片和 30 秒 y/n waiter | 返回结构化文本结果；检查、准备、安装请求和失败都写审计 | 明确不保留图片/等待器，避免把升级确认和消息会话生命周期绑定 |
| `config.auto_upgrade` 布尔开关 | `[upgrade].enabled`、`channel`、`policy`、路径、健康检查和超级用户配置 | 不保留旧键，避免误把 `true` 解释成自动安装 |
| `git pull` 原地更新 | 独立 staging/versions、强校验、原子 active 指针、外部重启 | 明确不保留；同一进程不做热替换 |
| pull/网络/Git 失败日志和手工提示 | 失败关闭、不中途 promote、结构化错误审计；切换后失败自动回滚 | 失败可见场景保留，恢复能力增强 |
| 插件自身分发 | 仅留下 `VersionSource` 扩展点 | 不在本批次实现，避免把宿主升级和插件分发耦合 |

本步测试不进行真实网络调用：Git 源使用本地临时仓库 fixture，HTTP 源使用 mock
client，覆盖版本比较边界、通道选择、commit/asset 校验失败、配置兼容性、staging、
健康失败回滚、策略档位、状态审计和三个命令的正向/负向/权限矩阵。

## 依赖来源

- [Entari](https://github.com/ArcletProject/Entari)
- [Satori Python SDK](https://github.com/RF-Tar-Railt/satori-python)
- [OneBot 11 反向 WebSocket 约定](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)
