<p align="center">
  <img src="docs/assets/banner.png" alt="TENKO chat group management bot banner">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.13-1E3A52?style=flat-square&labelColor=102D47" alt="Python 3.11 to 3.13">
  <img src="https://img.shields.io/badge/License-GPL--3.0-1E3A52?style=flat-square&labelColor=102D47" alt="GPL 3.0 license">
  <img src="https://img.shields.io/badge/Release%20channel-prerelease-D97D72?style=flat-square&labelColor=102D47" alt="Prerelease channel">
  <img src="https://img.shields.io/badge/Stack-Entari%20%7C%20Satori%20%7C%20OneBot%2011-C7A45B?style=flat-square&labelColor=102D47" alt="Entari Satori OneBot 11 stack">
</p>

Tenko 是一个面向聊天群组的管理 bot，基于 Entari 与 Satori 协议抽象构建，
提供权限、群管理、多账号响应策略、功能开关、状态查询和宿主升级等能力。
Satori 的多协议设计使同一套插件逻辑可以运行在不同聊天平台上——当前通过
OneBot 11 协议接入 QQ（协议端推荐 NapCat，也可替换为任何兼容实现），
后续接入新平台只需增加对应的协议适配层。

<p align="center">
  <img src="docs/assets/sections.png" alt="Tenko feature sections" width="100%">
</p>

## 缘起

Tenko 的名字取自东方 Project 中的比那名居天子——掌管大地的绯想之剑，
有顶天的天人。她不问因果、只按本心行事的气质，恰好是这只 bot
想要成为的样子：安静地悬于群聊之上，该出手时出手，无事时便隐入云端。

她的前身是 xiaomai-bot——诞生于 Graia Ariadne 框架时代的群管工具，
在多个聊天群里服役多年。2026 年夏天，旧骨架随协议与依赖一同老化，
于是推倒重来：以 Entari 为宿主、Satori 为协议抽象，沿用的是那套
沉淀下来的权限模型、群管逻辑与升级体系，舍去的是 Graia 时代的旧船票。
舟已换，航线未变——便是 Tenko。

## 功能说明

Tenko 围绕聊天群组的日常运营提供一组开箱即用的能力：

- **权限体系**——按成员和群两级管理权限，与平台管理角色自动同步；
- **群管理**——禁言、解禁、撤回、踢出、加精、加群审批等动作，带能力探测与失败回执；
- **多账号**——多个 bot 账号在同一宿主下共存，按群绑定响应策略，支持指定账号执行；
- **功能开关**——按群粒度启用或停用某个插件，回应"这个群要不要这个功能"；
- **状态与报告**——运行状态、消息统计、异常捕获，需要时以离线渲染的图片输出；
- **自我升级**——检查更新、下载校验、健康检查与回滚，升级不动你的配置和数据。

命令统一使用 / 前缀。下表与 tenko/plugins/ 中当前注册的插件一致；尖括号表示需要替换的参数。

| 插件 | 能力 | 常用命令 |
| --- | --- | --- |
| perm_manager | 管理成员权限、群权限，并同步群成员的平台管理角色 | /修改权限、/修改群权限、/权限列表 |
| helper | 从当前 command_manager 注册表生成帮助列表和命令详情 | /帮助、/帮助 <编号> |
| group_manager | 查询群设置、审批加群请求，以及执行禁言、解禁、撤回、加精、踢出和指定 BOT 退群等群管理动作 | /群设置、/同意邀请 <请求ID>、/退群 <群号> <BOT账号>、/禁言、/解禁 |
| status | 查看会话、进程资源、消息收发统计、在线账号和群路由状态 | /状态 |
| exception_catcher | 捕获全局异常，向超级用户发送带会话上下文的报告，必要时保存本地证据 | 无命令 |
| response_manager | 查询多账号在线状态、群绑定、禁言状态，并设置群响应策略 | /BOT列表、/在线BOT、/设定响应 |
| announcement | 向已开启指定功能的群推送公告，并返回逐群结果 | /公告 <功能名> <内容...> |
| updater | 按配置通道检查、准备和回滚 Tenko 宿主版本 | /检查更新、/升级、/回滚 |
| feature_manager | 按群启用或停用插件功能；控制平面插件不可由群管理员关闭 | /开启 <插件编号或名称>、/关闭 <插件编号或名称> |

群邀请审批仅允许目标群的 BotAdmin/Master 执行，GroupAdmin 无权审批；邀请人自身为
BotAdmin/Master 时会自动同意，无法取得邀请人 ID 时会保留待审并提示人工处理。

涉及权限变更、群管理或宿主升级的命令会按照当前群权限、账号能力和超级用户
配置执行。渲染不可用或未安装浏览器时，状态和异常报告自动回退文本。
RenderService 是由 Tenko runtime 直接注册的内置宿主服务，不属于插件清单。


## 使用指南

### 环境要求

- Python >=3.11,<3.14；
- 可连接到 OneBot 11 端点的协议端（例如 NapCat）及网络环境；
- 图片输出需要 Chromium 浏览器运行时；浏览器不可用时会回退文本。

### 创建独立环境

推荐使用 uv 管理依赖（基于 pyproject.toml 与 uv.lock）：

    uv sync

uv 会在项目根目录创建 .venv 并按锁文件安装依赖，之后通过 uv run 执行命令：

    uv run python -m tenko
    uv run pytest -q

如果不想使用 uv，也可以手动创建虚拟环境并按 requirements-entari.txt 安装
（该文件是 uv.lock 的 pip 兼容快照，依赖以 pyproject.toml 为准）：

    python -m venv .venv-entari
    source .venv-entari/bin/activate
    pip install -r requirements-entari.txt

Windows PowerShell 的激活命令为：

    .venv-entari\Scripts\Activate.ps1

复制配置模板：

    cp config/tenko.toml.example config/tenko.toml

然后按下节说明编辑 config/tenko.toml。启动：

    python -m tenko      # 或 uv run python -m tenko

生产部署可使用仓库内的标准启动器：

    ./scripts/launcher.sh

启动器把脚本所在仓库目录作为稳定根目录，固定以该目录为 cwd，并通过
`uv run --project <stable_root> --no-sync` 复用项目环境。没有 `active.json` 时运行
稳定根目录中的代码；存在有效的 `active.json` 时只把对应 `versions/` 子目录作为
代码源。启动器不消费 `handoff.json`，handoff 由 `tenko.__main__` 在正常启动时一次性
应用，应用成功后会在 fresh Python 进程中重执行 active 版本。升级命令 arm 的 detached
watcher 会等待当前进程退出，再调用这个启动器一次；因此 Ctrl+C 仍是正常的优雅退出路径。

### 协议端连接（以 NapCat 为例）

默认反向 WebSocket 地址为：

    ws://127.0.0.1:8080/onebot/v11/ws

在所选 OneBot 11 协议端的反向 WebSocket 配置中填写相同地址。下面以 NapCat
为例，在 NapCat 的 OneBot 11 反向 WebSocket 配置中填写相同地址。若配置了
[onebot].access_token，该协议端必须使用相同的 token；示例文件和下方最小配置
只使用占位符，部署时请替换为实际值。

### 图片渲染

图片渲染由内置 RenderService 提供，需要 Chromium 浏览器运行时，
在当前虚拟环境中执行（uv 环境可写为 uv run python -m playwright ...）：

    python -m playwright install chromium

Linux 主机缺少 Chromium 系统依赖时，需要由运维按主机权限安装对应依赖。

## 最小配置

config/tenko.toml 可以从示例复制后按需补充。下面的配置覆盖连接、权限、
数据库、渲染和升级的基本入口；所有敏感字段和账号标识都是占位符：

    # 通知群：邀请审批等管理通知的播报目标；留空表示私发 Master。
    notify_group = ""

    [basic]
    prefix = ["/"]
    ignore_self_message = true
    skip_req_missing = false
    superusers = { onebot = ["<QQ_ID>"] }

    [basic.log]
    level = "INFO"
    # save = { rotation = "00:00", compression = "gz", colorize = false }

    [onebot]
    listen_host = "127.0.0.1"
    listen_port = 8080
    reverse_ws_prefix = "/"
    reverse_ws_path = "onebot/v11"
    reverse_ws_endpoint = "ws"
    access_token = "<ONEBOT_ACCESS_TOKEN>"
    api_timeout = 60
    satori_host = "127.0.0.1"
    satori_path = "satori"
    satori_token = "<SATORI_TOKEN>"

    [debug]
    enabled = false

    [database]
    url = "sqlite+aiosqlite:///./.tenko/tenko.db"
    echo = false
    create_table_at = "preparing"

    [render]
    timeout = 10.0
    width = 800
    quality = 85
    device_scale_factor = 2

    [upgrade]
    enabled = true
    source = "git_tag"
    repository = "https://github.com/g1331/tenko.git"
    tag_prefix = "v"
    channel = "stable"
    policy = "check"

不要把真实 token、平台用户标识、GitHub 凭据或其他密钥写入版本库。邀请审批等管理通知
优先发送到顶层 `notify_group` 指定的群；留空或省略时只私发给一个 Master。

### 顶层通知配置

| 配置 | 说明 |
| --- | --- |
| notify_group | 邀请审批等管理通知的播报群；留空或省略时私发一个 Master |

## 配置参考

配置读取自 tenko/config.py。未写出的配置项使用代码中的默认值；配置表中的
路径相对于启动目录解析。

### [onebot]

| 字段 | 说明 |
| --- | --- |
| listen_host | 反向 WebSocket 监听地址，默认 127.0.0.1 |
| listen_port | 监听端口，默认 8080 |
| reverse_ws_prefix | 反向 WebSocket 路径前缀，默认 / |
| reverse_ws_path | OneBot 11 路径，默认 onebot/v11 |
| reverse_ws_endpoint | WebSocket 端点名，默认 ws |
| access_token | 可选的 OneBot 访问 token；不设置时可留空 |
| api_timeout | OneBot action 超时时间，默认 60 秒 |
| satori_host | 内部 Satori 服务地址；省略时根据监听地址推导 |
| satori_path | 内部 Satori 路径，默认 satori |
| satori_token | 内部 Satori token，可留空关闭鉴权 |
| capability_overrides | 按账号覆盖平台能力学习结果的映射，值为布尔开关 |

### [basic] 与 [debug]

| 配置 | 说明 |
| --- | --- |
| basic.prefix | Entari 官方命令前缀列表；默认兼容 Tenko 的 `/`，可以配置多个前缀 |
| basic.ignore_self_message | 是否忽略机器人自己发送的消息，默认开启 |
| basic.skip_req_missing | 是否跳过缺少依赖的事件监听器，默认关闭 |
| basic.superusers | 超级用户唯一权威来源，格式为“平台名到用户 ID 列表”的映射 |
| basic.log.level | 日志级别，默认 INFO |
| basic.log.ignores | 要忽略的日志记录器名称列表，支持通配符 |
| basic.log.save | 日志保存与轮转；默认 `None`，不落盘 |
| basic.log.save.rotation | 轮转时间或文件大小，例如 `00:00` 或 `10 MB` |
| basic.log.save.compression | 压缩格式，例如 `gz`；留空表示不压缩 |
| basic.log.save.colorize | 是否在文件中保留颜色，默认由官方模型开启 |
| debug.enabled | 是否只处理 debug.masters 中用户产生的事件，默认关闭 |
| debug.masters | 调试白名单；省略时继承 basic.superusers，显式空列表表示不放行用户 |

例如，OneBot 11 的超级用户和日志轮转配置为：

    [basic]
    superusers = { onebot = ["<QQ_ID>"] }

    [basic.log]
    save = { rotation = "00:00", compression = "gz", colorize = false }

`basic.network` 也按 Entari 官方模型解析并保留，但 Tenko 的 OneBot 连接仍由
`[onebot]` 节组装；本批次不会用 `basic.network` 驱动 OneBot 连接。旧配置中的
`[runtime].log_level`、`[runtime].command_prefix` 和 `[entari].superusers` 会在读取时
映射到 `basic`，新配置应直接使用官方节。

### [database]、[features] 与 [exception]

| 配置 | 说明 |
| --- | --- |
| database.url | SQLAlchemy 数据库 URL，默认 sqlite+aiosqlite:///./.tenko/tenko.db |
| database.echo | 是否输出 SQL，默认关闭 |
| database.create_table_at | 建表时机，可选 preparing、prepared 或 blocking；Tenko 运行期状态接入时为保证状态读取晚于建表会使用 preparing |
| accounts / response state | 多账号路由和响应策略保存在 database.url 指定的数据库中 |
| features | 群功能开关保存在 database.url 指定的数据库中 |
| features.default_enabled | 新群或未记录功能的默认开关，默认开启 |
| exception.message_buffer_size | 异常报告保留的最近消息数量，默认 10 |
| exception.evidence_dir | 报告无法投递时的本地证据目录，默认 .tenko/exceptions |

Tenko 的 `/开启`、`/关闭` 使用 `database.url` 指定的数据库保存“群 × 插件”的功能状态，
多账号路由、响应策略、命令频控和启动耗时历史也使用同一数据库。它与 Entari builtin
control 使用的 `local_data` 状态文件（包括全局插件/函数控制）是两套独立边界，不会
互相读写；实际执行需要插件仍被 Entari 注册且没有被全局控制停用，同时通过 Tenko 当前
群的开关检查。Entari 全局控制因此优先于 Tenko 群级开关，而 Tenko 群级开关在命令进入
插件分发前生效。

### [ratelimit]

| 字段 | 说明 |
| --- | --- |
| enabled | 是否启用命令限流，默认开启 |
| window_seconds | 滚动窗口长度，默认 15.0 秒 |
| max_weight | 窗口允许的最大权重，默认 24 |
| default_weight | 未单独指定命令的默认权重，默认 1 |
| cooldown_seconds | 同一来源冷却时间，默认 5.0 秒 |
| blacklist_seconds | 触发限制后的黑名单时间，默认 300.0 秒 |
| override_permission | 可豁免限流的最低权限等级，默认 32 |

### [render]

| 字段 | 说明 |
| --- | --- |
| timeout | 单次渲染超时时间，默认 10.0 秒 |
| width | 图片 viewport 宽度，默认 800 |
| quality | JPEG 质量，范围为 0 到 100，默认 85 |
| device_scale_factor | 浏览器设备像素比，默认 2 |

### [upgrade]

升级配置控制版本发现、制品准备和外部重启接管。默认策略只检查，不会自动下载
或安装。

| 字段 | 说明 |
| --- | --- |
| enabled | 是否启用升级功能，默认开启 |
| source | 版本源：git_tag、github_release 或 manifest |
| repository | `git_tag` 源使用的 Git 仓库地址；默认值 `.` 只适合本地 refs，远端部署必须填写完整 URL，例如 `https://github.com/g1331/tenko.git` |
| github_repository | GitHub 版本源的仓库标识 |
| manifest_url | manifest 版本源的地址 |
| github_token | 可选的 GitHub 访问 token |
| asset_name | 可选的发布制品名称 |
| tag_prefix | Git tag 前缀，默认 v |
| channel | 更新通道；stable 只接受正式版本，prerelease 同时接受正式和预发布版本 |
| policy | 执行策略；常用值为 check、download、install |
| current_version | 当前版本；留空时从项目版本读取 |
| config_version | 配置兼容版本，默认 1.0.0 |
| install_root | 版本和升级状态目录，默认 .tenko/upgrades |
| config_path | 外部配置路径，默认 config/tenko.toml |
| data_dir | 仅传给自定义健康检查/启动命令的外部目录，默认 data；Tenko 自身持久化数据仍在 .tenko |
| health_command | 可选健康检查命令参数列表 |
| launch_command | 可选外部启动命令参数列表 |
| health_timeout | 健康检查超时时间，默认 30 秒 |
| check_interval_hours | 定时检查间隔，默认 24 小时 |
| superuser_ids | 可执行升级命令的用户 ID；省略时继承 basic.superusers |

## 更新机制

升级命令只允许配置的超级用户执行：

    /检查更新
    /升级
    /回滚

### 版本源与更新通道

当 `source = "git_tag"` 时，`repository` 是用于 `git ls-remote --tags` 和
`git clone` 的仓库地址。需要从远端发现新版本的部署必须填写完整 Git URL，例如：

    [upgrade]
    source = "git_tag"
    repository = "https://github.com/g1331/tenko.git"
    tag_prefix = "v"
    channel = "stable"

不要把 `repository = "."` 当作远端地址：它指向当前本地工作树，`git_tag` 只会看到
本地已有的 refs，不会联网发现远端 tag。当前实现兼容已有 Git 工作树中的 named
remote（例如 `origin`），会在加载配置时用 `git remote get-url` 将其解析为 URL；但
直接填写完整 URL 不依赖部署目录中的 remote 配置，也能保证检查和下载使用同一个远端。

`tag_prefix` 默认是 `v`，因此 `v4.0.0` 会被解析为版本 `4.0.0`。通道决定预发布
版本是否进入候选集合，并且候选版本仍必须高于当前版本：

- `stable` 只选择正式版本，适合生产实例；`4.0.0-rc.1` 等预发布 tag 会被排除。
- `prerelease` 同时接受正式版和预发布版，适合验证实例或需要跟进预发布版本的部署。

执行策略的含义是：`policy = "check"` 只发现并记录候选版本，`policy = "download"`
自动准备制品，`policy = "install"` 生成外部安装接管记录。进程切换仍由稳定的外部
启动器完成。

### `/升级`：下载、接管与重启

`/检查更新` 只查询当前通道中高于当前版本的最高候选版本，返回当前版本、候选版本、
标签和来源，不下载制品。

`/升级` 不会在当前进程中热替换代码，完整流程如下：

1. 检查当前通道并选择候选版本。
2. 获取候选制品；`git_tag` 源会按 tag 做浅克隆，并校验 commit SHA。随后升级器
   检查配置兼容性和切换前健康状态，成功后把制品提升到
   `.tenko/upgrades/versions/`，写入 `pending.json`。
3. 写入 `handoff.json`，请求外部重启时执行 `activate`。命令会尝试 arm 一次性
   detached watcher；watcher 只等待当前进程退出，不负责读取或应用升级状态。
4. 收到成功回复后使用 `Ctrl+C` 让当前 Tenko 进程优雅退出。watcher 检测到旧进程
   退出后只启动一次标准启动器 `scripts/launcher.sh`。
5. 启动器固定以部署根目录为工作目录，并使用共享的 uv 环境启动 Tenko。启动早期
   会消费 `handoff.json`，原子更新 `active.json`，执行切换后的健康检查，然后在
   fresh Python 进程中重新执行 active 版本。配置、SQLite 数据库和 `.tenko/` 下的
   运行状态仍使用稳定根目录中的原有路径。

如果 watcher 未能 arm，`/升级` 的回复会提示手动接管；此时退出当前进程后运行
`./scripts/launcher.sh`。如果切换后的健康检查失败，升级器会恢复原 active 指针并
清理本次接管记录，避免失败 handoff 在后续启动中反复执行。

`/回滚` 请求回到 `.tenko/upgrades/previous.json` 指向的上一可用版本：

1. 命令检查是否存在上一版本和当前 `active` 指针。
2. 写入 `action = "rollback"` 的 `handoff.json`，并按与 `/升级` 相同的方式尝试
   arm watcher。
3. 使用 `Ctrl+C` 退出当前进程；下一次由标准启动器启动时，启动早期消费回滚 handoff，
   将 `active.json` 切换到上一版本并执行健康检查。

回滚也不会在当前进程中立即替换代码。回滚后的健康检查失败会恢复原 active 指针并
隔离失败的 handoff；如果不存在上一可用版本，命令会返回“没有可回滚的上一可用版本”。

`[upgrade]` 配置在 Tenko 启动时读取并构造升级管理器，运行期间不会自动重新读取配置。
因此修改 `channel`、`repository`、`source`、`policy` 或其他升级配置后，必须重启
Tenko 才会生效；若配置修改本身需要先停止服务，应按部署方式退出当前进程，再使用
标准启动器（或原有的 `uv run python -m tenko` 启动命令）启动。

启用周期检查时，check_interval_hours 控制定时检查间隔。升级目录、配置目录和
数据目录彼此分离，升级过程不会覆盖用户配置或运行数据；`data_dir` 不会改变
Tenko 自身 `.tenko` 应用数据的落点。

### 配置兼容性清单

仓库根目录的 `upgrade-manifest.json` 是发布制品中的 canonical 配置兼容性清单，
最小内容为：

    {
      "min_config_version": "1.0.0"
    }

清单中的 `min_config_version` 是独立于项目版本的配置协议版本。它表示候选代码
能够读取的最低用户配置版本：普通代码修复或功能增加不需要提升它；只有配置格式
发生破坏性变化、旧配置无法继续被新代码读取时才提升它。项目版本（例如 `4.0.1`）
和配置协议版本（例如 `1.0.0`）不能互相推导。

发布源数据写在 `pyproject.toml` 的 `[tool.tenko.upgrade]` 段：

    [tool.tenko.upgrade]
    min_config_version = "1.0.0"

运行版本脚本时，`scripts.bump` 会在修改版本前校验该字段，并在版本、锁文件和
可选 changelog 步骤成功后生成根目录清单：

    uv run python -m scripts.bump pre_n --no-commit
    uv run python -m scripts.bump patch --commit

字段缺失或不是合法 SemVer 会使发布流程失败，不会从项目版本猜测默认值。使用
`--commit` 时清单会和 `pyproject.toml`、`uv.lock` 一起加入提交；不使用该选项时
仍由发布者自行检查并提交生成的清单。

旧制品可能没有清单。升级器会将这类制品按“未声明最低配置版本”的 legacy 兼容
行为处理并写入审计；新制品应只生成根目录这一份 canonical 清单。为兼容更早的
制品，升级器仍会按固定顺序检查 `tenko/upgrade-manifest.json`，再检查根目录清单。

### 代码、配置、数据与升级状态目录

标准启动器以部署根目录为稳定 `cwd`。候选版本目录只提供代码，不携带配置、虚拟
环境或应用数据；表中的相对路径都相对于稳定 `cwd` 解析：

| 目录或文件 | 用途 | 解析位置 |
| --- | --- | --- |
| 部署根目录 | 稳定启动根、共享依赖和当前工作树 | 启动器确定的稳定根目录 |
| `config/tenko.toml` | 用户配置 | 稳定 `cwd` |
| `.tenko/tenko.db` | Tenko 运行期状态和既有业务表 | 稳定 `cwd` |
| `.tenko/exceptions/` | 异常取证文件 | 稳定 `cwd` |
| `.tenko/upgrades/` | `active.json`、`previous.json`、`pending.json`、`handoff.json` 和版本目录 | 稳定 `cwd` |
| `.tenko/upgrades/versions/<version>/` | 候选代码 | 升级状态目录下，作为代码源 |

`[upgrade].data_dir` 是只传给自定义健康检查/启动命令的外部目录，不是 Tenko
自身应用数据根目录。升级切换后，数据库、JSON 状态、异常取证和配置仍指向稳定
根目录下的原有物理路径；候选版本不会在自己的目录中生成新的 `.tenko/` 或
`config/`。

## 开发环境搭建

### 获取与安装

    git clone https://github.com/g1331/tenko.git
    cd tenko
    uv sync

依赖以 pyproject.toml 声明、uv.lock 锁定；依赖变更使用 uv add / uv remove，
不要直接编辑 pyproject.toml 的依赖表。requirements-entari.txt 是 uv.lock 的
pip 兼容快照，仅用于无 uv 的环境。

### 代码约定

- 插件位于 tenko/plugins/，遵循 Entari 插件生命周期，命令统一 / 前缀；
- 数据库访问集中在 tenko/db/，宿主服务在 tenko/host/；
- 提交遵循 Conventional Commits，功能、修复、文档分开提交；
- 开发细节见 AGENTS.md。

### 运行测试

在项目根目录、并使用已安装依赖的环境执行：

    ./.venv-entari/bin/ruff check tenko tests/tenko
    ./.venv-entari/bin/python -m pytest tests/tenko

使用 uv 环境时可以直接执行：

    uv run ruff check tenko tests/tenko
    uv run pytest -q

如果使用已激活的虚拟环境，也可以执行：

    ruff check tenko tests/tenko
    python -m pytest tests/tenko

## 架构

![Tenko architecture](docs/assets/architecture.png)

<details>
<summary>文本版架构图</summary>

```text
OneBot 11 endpoint (e.g. NapCat)
  │
  ▼
Satori adapter ──► Entari runtime ──► command_manager ──► Tenko plugins
                                      │
                                      ├── account / permission / feature services
                                      ├── SQLite database + repositories
                                      └── RenderService
```

</details>

兼容 OneBot 11 的协议端（以下以 NapCat 为例）通过反向 WebSocket 连接 Tenko，
Satori 负责协议对象和动作抽象，Entari 负责事件分发、插件生命周期和命令处理：

- 插件在 Entari 生命周期中加载和卸载；插件通过原生命令注册表接收命令，
  通过宿主服务访问账号路由、权限、功能开关、限流和升级控制平面。
- command_manager 是帮助系统读取命令列表的来源，因此帮助内容会随当前已注册
  插件变化。
- RenderService 由 Tenko runtime 直接注册到 Launart，使用 Playwright 在本地离线
  渲染 HTML/Markdown；服务异常不会
  阻断文本功能。
- 数据层使用 SQLite、SQLAlchemy 和 entari-plugin-database。新 ORM 位于
  tenko/db/models.py，repository 位于 tenko/db/repositories.py；应用启动时会创建
  或迁移所需表，已有 SQLite 数据库文件可以继续使用。
