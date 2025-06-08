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

---
## 6. 本项目开发指南

### 6.1 项目架构概览
本项目是一个基于 Graia Ariadne 框架构建的 QQ 机器人。其核心设计围绕事件驱动和模块化插件系统，旨在实现灵活的功能扩展和维护。
-   **核心驱动 (`main.py`)**: 作为整个应用的启动入口，`main.py` 负责：
    -   检查运行环境和配置文件 `config/config.yaml` 的存在性，如果配置文件不存在，会尝试从环境变量读取或引导用户通过 TUI (Text User Interface) 进行初始化配置。
    -   实例化全局配置 (`core.config.GlobalConfig`) 和机器人核心类 (`core.bot.Umaru`)。
    -   初始化并加载 `BroadcastControl` (事件总线) 和 `Saya` (插件系统)。
    -   安装定义在 `modules/` 目录下的所有插件（包括 `required`, `self_contained`, `third_party`）。
    -   调用 `core.bot.Umaru.launch()` 方法，启动 Ariadne 应用的事件循环和所有已注册的服务，使机器人开始接收和处理事件。
-   **配置中心 (`config/config.yaml`)**:
    -   所有关键的运行时配置（如机器人账号信息、Mirai API HTTP 连接参数、数据库连接字符串、功能开关、日志级别等）都存储在此 YAML 文件中。
    -   该文件由用户根据 `config/config_demo.yaml` 模板复制并修改而来。
    -   在程序内部，这些配置通过 `core.config.GlobalConfig` Pydantic 模型进行加载、校验和访问，确保了配置的类型安全和易用性。
-   **核心逻辑 (`core/bot.py` - `Umaru` 类)**:
    -   `Umaru` 类是整个机器人应用的核心控制器和协调者。它封装了与 Graia Ariadne 框架的深度集成。
    -   负责管理一个或多个机器人账号的 `Ariadne` 应用实例。
    -   在初始化阶段 (`__init__` 和 `initialize` 方法)，它会设置日志、注册各种后台服务（如 Playwright、FastAPI Web服务、Alembic数据库迁移、自动更新检查、启动时间记录等）、检查并初始化群组权限、更新管理员权限等。
    -   通过 Saya 服务加载和管理所有插件模块。
-   **数据持久化 (ORM 与 Alembic)**:
    -   项目使用 SQLAlchemy 作为 ORM 工具，配合 `aiosqlite` 驱动实现异步数据库操作。
    -   所有的数据库表模型（如用户权限、群组设置、聊天记录等）统一定义在 `core/orm/tables.py` 中。
    -   数据库的初始化和版本迁移由 Alembic (`utils/alembic.py` 和 `core.bot.Umaru.alembic()` 方法) 管理。尽管在 `Umaru.alembic()` 方法中，检测到模型与数据库有差异时，自动执行迁移的命令当前被注释掉了（转而提示用户手动更新），但项目保留了Alembic进行数据库版本控制的能力。在特定异常情况下（如数据库文件完全不存在），`orm.create_all()` 可能会被触发以创建所有表。
-   **模块化功能实现 (`modules/` 目录与 Saya)**:
    -   机器人的各项具体功能（如命令处理、特定消息响应、定时任务等）均以插件的形式存在于 `modules/` 目录下的子目录中（如 `required`, `self_contained`, `third_party`）。
    -   这些插件遵循 Saya 插件系统的规范，允许独立开发、加载和管理，大大提高了项目的可扩展性和可维护性。每个插件通常包含一个 `metadata.json` 文件来描述其元信息。
-   **工具集 (`utils/` 目录)**:
    -   `utils/` 目录包含了一系列为项目提供支持的辅助脚本和工具类，例如：
        -   `alembic.py`: 集成 Alembic 服务。
        -   `readenv.py`: 从环境变量读取配置。
        -   `tui.py`: 提供文本用户界面进行初始配置。
        -   其他可能的文件，如 `files.py`, `image.py` 等，提供文件操作、图像处理等通用功能。

### 6.2 `core` 目录详解
`core` 目录是 `xiaomai-bot` 项目的核心代码所在地，包含了机器人运行的基础框架、主要业务逻辑的控制器以及数据模型的定义。理解 `core` 目录对于进行深层次的开发和维护至关重要。
-   **`bot.py` (核心类 `Umaru`)**:
    -   **职责**: `Umaru` 类是机器人的“大脑”和总控制器。它负责：
        -   初始化和管理一个或多个QQ机器人账号的 `Ariadne` 应用实例。
        -   加载全局配置 (`GlobalConfig`)。
        -   集成并启动 Graia Ariadne 的各种核心服务，如 `BroadcastControl` (事件总线)、`Saya` (插件系统)、`PlaywrightService` (用于网页截图或交互)、`UvicornService` (如果启用API)、`AlembicService` (数据库迁移) 等。
        -   在应用启动时执行一系列初始化任务，例如设置日志、检查并更新群组和用户权限、加载所有插件模块。
        -   提供 `launch()` 方法来启动整个应用的事件循环。
    -   **主要方法分析**:
        -   `__init__(self, g_config: GlobalConfig, base_path: str | Path)`: 构造函数，接收全局配置和项目基础路径，创建 `Ariadne` 应用列表，并添加各种 `Launchable` 服务。
        -   `initialize(self)`: 异步初始化方法，在 `AccountLaunch` 事件后被触发（间接通过 `main.py` 中的 `bcc.receiver(AccountLaunch)` 调用）。它负责大部分启动时的业务逻辑初始化，如权限同步、多账户响应模型初始化等。
        -   `install_modules(self, base_path: str | Path, recursion_install: bool = False)`: 使用 Saya 服务加载指定路径下的插件模块。
        -   `alembic(self)`: 处理数据库迁移的逻辑，包括在首次运行时初始化 Alembic 环境，并检查数据库模型与实际表结构的差异（尽管自动应用迁移的命令在当前版本中被注释，但提示手动操作）。
        -   `config_check(self)`: 检查 `config.yaml` 中的配置项是否被正确设置，避免使用模板的默认值。
    -   **AI代理交互点**: 当需要访问全局配置、Ariadne应用实例、或触发核心初始化流程时，通常会与 `Umaru` 类或通过 `create(Umaru)` 获取其实例进行交互。
-   **`config.py` (配置模型 `GlobalConfig`)**:
    -   **职责**: 使用 Pydantic 定义了整个应用的全局配置项的数据模型。这确保了从 `config.yaml` 加载的配置具有类型安全，并且易于在代码中以面向对象的方式访问。
    -   **结构**: `GlobalConfig` 类中的字段直接对应 `config.yaml` 文件中的顶级键和嵌套结构。例如，`config.mirai_host` 对应 YAML 中的 `mirai_host`。
    -   **AI代理交互点**: 当需要读取任何全局配置时，应通过 `config = create(GlobalConfig)` 获取配置实例，然后访问其属性。如果需要添加新的全局配置项，则应首先在此文件中扩展 `GlobalConfig` 模型。
-   **`control.py`**:
    -   **职责**: 此文件目前主要包含 `Distribute` 类（在 `Umaru.initialize` 中调用了 `Distribute.distribute_initialize()`），其具体功能可能与多账户消息分发策略或特定事件的预处理/后处理控制有关。
    -   **AI代理交互点**: 如果AI的任务涉及到修改消息的分发行为、添加新的全局事件控制逻辑（如自定义的权限检查、频率限制），可能需要理解和修改此文件。 （*需要AI在实际开发中进一步探查该文件内其他类和函数的具体作用。*）
-   **`orm/tables.py` (数据库表模型)**:
    -   **职责**: 使用 SQLAlchemy 的声明式语法定义了所有应用所需的数据库表结构。每个类代表一个数据表，类属性对应表的列。
    -   **包含的表 (示例)**: `MemberPerm` (成员权限), `GroupPerm` (群组权限), `GroupSetting` (群设置), `ChatRecord` (聊天记录), `KeywordReply` (关键词回复) 等。
    -   **AI代理交互点**:
        -   在进行任何数据库相关的开发（例如，为新功能存储数据，或查询现有数据）之前，必须查阅此文件以了解准确的表名、列名、数据类型和关系。
        -   如果需要添加新的数据表或修改现有表结构，必须在此文件中进行定义或修改，并随后处理数据库迁移 (见 6.6 节)。
-   **`orm/orm.py` (或类似功能的封装)**:
    -   虽然项目中没有一个名为 `orm.py` 的独立文件完全封装所有ORM操作，但 `core.orm` 包（通过 `__init__.py` 可能导出了 `Database` 实例或相关工具函数）以及 `Umaru` 类中对 `orm.fetch_one`, `orm.fetch_all`, `orm.insert_or_update` 等方法的调用，共同构成了项目的ORM操作层。
    -   **职责**: 提供了简便的方法来执行数据库的增删改查操作，封装了底层的 SQLAlchemy 引擎和会话管理。
    -   **`core.orm.__init__.py`** (可能包含 `orm = Database(...)` 的实例化) 和 `core.orm.Database` 类 (如果存在) 是理解其具体实现的关键。
    -   **AI代理交互点**: 当需要执行数据库操作时，应使用这些已封装好的ORM辅助方法，而不是直接操作 SQLAlchemy 的 `Session` 或 `Connection` (除非有特殊需求且了解内部实现)。

### 6.3 插件系统 (`modules/` 与 Saya)
`xiaomai-bot` 的核心优势之一在于其高度模块化的插件系统，这得益于 Graia Saya 框架的集成。所有非核心的、具体的功能实现都应该以插件的形式存在于 `modules/` 目录下。
-   **插件目录结构**:
    -   `modules/` 是所有插件的根目录。它通常包含以下三个标准子目录，用于组织不同类型的插件：
        -   **`modules/required/`**: 存放机器人运行所必需的基础插件或核心功能插件，这些插件通常随主程序一同加载且不建议用户随意禁用。例如，权限管理、帮助系统、插件管理器本身等。
        -   **`modules/self_contained/`**: 存放由本项目主要开发者编写的、功能相对独立的内置插件。这些插件提供了机器人的大部分特色功能。
        -   **`modules/third_party/`**: 存放从其他开发者或社区获取的第三方插件。
    -   AI代理在开发新功能时，应根据插件的性质将其放置在 `self_contained` (如果是项目原生功能) 或 `third_party` (如果是引入外部插件) 目录下。
-   **插件的发现与加载**:
    -   插件的加载由 `core.bot.Umaru` 类中的 `install_modules()` 方法负责。此方法会遍历上述插件目录，并使用 Saya 服务 (`create(Saya)`) 来发现和加载有效的插件模块。
    -   Saya 支持两种主要的插件形式：
        -   **单文件插件**: 一个单独的 `.py` 文件即为一个插件。
        -   **包插件**: 一个包含 `__init__.py` 的目录被视为一个插件包。插件的逻辑可以分散在包内的多个 `.py` 文件中。
-   **`metadata.json` (插件元数据)**:
    -   每个插件（无论是单文件还是包插件）都**必须**在其相同路径下或包的根目录内包含一个名为 `metadata.json` 的文件。此文件用于向 Saya 和机器人核心声明插件的元信息。
    -   **标准字段举例**:
        ```json
        {
          "name": "my_awesome_plugin",
          "display_name": "我的神奇插件",
          "version": "0.1.0",
          "authors": ["作者A", "作者B"],
          "description": "这是一个实现了某某神奇功能的插件。",
          "usage": [
            "命令A：执行操作1",
            "命令B <参数>：执行操作2"
          ],
          "example": [
            "发送：命令A",
            "机器人回复：操作1已完成"
          ],
          "default_switch": true,
          "default_notice": false,
          "level": "self_contained"
        }
        ```
    -   AI代理在创建新插件时，务必正确编写 `metadata.json` 文件。
-   **插件的基本代码结构 (以包插件为例)**:
    -   `my_awesome_plugin/`
        -   `__init__.py`: 插件的入口文件。Saya 会执行此文件来加载插件。
            ```python
            from graia.saya import Channel
            from graia.saya.builtins.broadcast.schema import ListenerSchema
            from graia.ariadne.event.message import GroupMessage
            from graia.ariadne.message.chain import MessageChain
            from graia.ariadne.message.element import Plain
            from graia.ariadne.app import Ariadne

            channel = Channel.current()

            @channel.use(ListenerSchema(listening_events=[GroupMessage]))
            async def group_message_handler(app: Ariadne, event: GroupMessage):
                if event.message_chain.display == "你好":
                    await app.send_message(
                        event.sender.group,
                        MessageChain(f"你好，{event.sender.name}！")
                    )
            ```
        -   `listener.py` (可选): 可以将事件监听器逻辑单独存放到此文件，然后在 `__init__.py` 中通过 `channel.include("my_awesome_plugin.listener")` 导入。
        -   `config.py` (可选): 如果插件有自己独立的配置，可以定义Pydantic模型在此，并通过某种方式加载。
        -   其他辅助模块 (`utils.py`, `data_source.py` 等)。
-   **开发新插件的建议步骤**:
    1.  **确定插件类型和位置**: 在 `modules/` 下合适的子目录创建插件目录。
    2.  **编写 `metadata.json`**。
    3.  **创建 `__init__.py`**: 获取 `Channel.current()`。
    4.  **实现事件监听**: 使用 `@channel.use(ListenerSchema(...))` 或 `@bcc.receiver(...)`。
    5.  **编写核心逻辑**: 解析消息、调用API、与其他服务交互、数据库操作。
    6.  **组织代码**: 拆分逻辑到不同文件。
    7.  **(可选) 添加配置**。
    8.  **(重要) 测试**。
-   **插件间的交互**:
    -   **事件**: 一个插件可以触发事件，另一个插件可以监听。
    -   **共享服务**: 通过 `creart` 注册和获取共享服务。
    -   **直接导入**: (谨慎使用，避免耦合)。
    -   AI代理应优先考虑通过共享服务或定义清晰的事件来进行跨插件协作。

### 6.4 Graia Ariadne 框架在本项目中的应用实践
Graia Ariadne 是 `xiaomai-bot` 实现即时通讯交互的核心框架。理解其在项目中的具体应用方式对AI代理至关重要。AI代理在开发时，可以随时查阅 [Graia Ariadne 官方文档](https://docs.graia.cn/ariadne/) 以获取更全面的API细节。
-   **核心概念速览**:
    -   **Application (`Ariadne`)**: 代表一个机器人账号的实例，是执行所有操作（如发送消息、获取信息）的入口。本项目在 `core.bot.Umaru` 中管理一个或多个 `Ariadne` 实例。
    -   **BroadcastControl (`bcc`)**: 事件总线，负责接收和分发由 `Ariadne` 应用产生的所有事件。插件和核心逻辑通过向 `bcc` 注册监听器来响应事件。实例通过 `bcc = create(Broadcast)` 获取。
    -   **MessageChain**: 消息内容的容器，可以组合多种类型的消息元素（文本、图片、At等）。
    -   **Event System**: Ariadne 的核心机制，机器人接收到的所有信息和内部状态变化都以事件的形式通过 `bcc` 广播。
    -   **Service (`Launart`)**: 用于实现具有独立生命周期的后台任务或服务。
    -   **Saya**: 插件系统，用于管理和加载项目的功能模块。
-   **6.4.1 事件监听与处理**:
    -   **装饰器注册**: 项目中监听事件的主要方式是使用 `graia.broadcast.Broadcast` 实例 (`bcc`) 的 `@bcc.receiver(EventType)` 装饰器。
        ```python
        from graia.broadcast import Broadcast
        from graia.ariadne.event.message import GroupMessage
        from graia.ariadne.app import Ariadne
        from graia.ariadne.model import Group
        from graia.ariadne.message.chain import MessageChain

        bcc = create(Broadcast)

        @bcc.receiver(GroupMessage)
        async def handle_group_message(app: Ariadne, group: Group, message: MessageChain):
            if message.display == "ping":
                await app.send_message(group, MessageChain("pong"))
        ```
    -   **Saya Channel 注册 (插件中)**: 在 Saya 插件 (`modules/` 下) 中，通常通过当前插件的 `Channel` 来注册监听器。
        ```python
        from graia.saya import Channel
        from graia.saya.builtins.broadcast.schema import ListenerSchema
        # ...
        channel = Channel.current()
        @channel.use(ListenerSchema(listening_events=[FriendMessage]))
        async def handle_friend_message(app: Ariadne, friend: Friend, message: MessageChain):
            # ...
        ```
    -   **常见事件类型**: `GroupMessage`, `FriendMessage`, `TempMessage`, `AccountLaunch`, `NudgeEvent`, `BotJoinGroupEvent` 等。 (AI代理应根据需求查阅文档选择事件)。
    -   **获取事件信息**: 通过监听函数的类型注解参数自动注入，如 `app: Ariadne`, `event: SpecificEventType`, `message: MessageChain`, `group: Group`, `member: Member` 等。
-   **6.4.2 消息链 (`MessageChain`) 的构造与发送**:
    -   **构造方法**:
        -   直接字符串初始化: `MessageChain("纯文本消息")`
        -   消息元素列表初始化: `MessageChain([PlainText("文本"), Image(path="...")])`
        -   (项目中观察到的主要是这两种直接使用构造函数的方式)
    -   **常用消息元素API (from `graia.ariadne.message.element`)**:
        -   `PlainText(text: str)`
        -   `Image(path: Optional[Path]=None, url: Optional[str]=None, base64: Optional[str]=None, id: Optional[str]=None)`
        -   `At(target: int)`
        -   `AtAll()`
        -   `Quote(id: int, groupId: int, senderId: int, targetId: int, origin: MessageChain)` (或 `event.message_chain.quote()`)
        -   `Face(id: int)` 或 `Face(name: str)`
        -   `Voice(path: Optional[Path]=None, url: Optional[str]=None, base64: Optional[str]=None)`
    -   **发送消息** (异步):
        -   `await app.send_message(target, message)`
        -   `await app.send_group_message(group_or_id, message)`
        -   `await app.send_friend_message(friend_or_id, message)`
        -   `await app.send_temp_message(group_or_id, member_or_id, message)`
    -   **解析消息链**:
        -   `message_chain.display` (纯文本)
        -   `message_chain.has(ElementType)`
        -   `message_chain.get_first(ElementType)`
        -   `message_chain.get(ElementType)` (列表)
-   **6.4.3 获取框架对象与信息** (异步):
    -   `app: Ariadne = Ariadne.current()` 或事件参数注入。
    -   `await app.get_group_list()`, `await app.get_friend_list()`
    -   `await app.get_group(id)`, `await app.get_friend(id)`, `await app.get_member(group_id, member_id)`
    -   `await app.get_member_list(group_id)`
    -   `await app.get_bot_profile()`
    -   `app.account` (机器人QQ号)
-   **6.4.4 依赖注入 (`creart`)**:
    -   使用 `instance = create(ServiceClass)` 获取单例 (如 `create(GlobalConfig)`, `create(Umaru)`)。
    -   可参考 `core.bot.UmaruClassCreator` 创建自定义 Creator。
-   **6.4.5 Saya 插件接口**:
    -   `channel = Channel.current()`
    -   `@channel.use(ListenerSchema(...))` 或 `@channel.use(BroadcastBehaviour)` 注册监听器。
    -   `channel.include("module_path")` 加载子模块。
-   **6.4.6 服务 (`Launart` Launchable)**:
    -   定义: 继承 `Launchable`, 实现 `id`, `required`, `stages` 属性和 `launch` 方法。
    -   注册: `Ariadne.launch_manager.add_service(MyService())`。
    -   项目中使用示例: `PlaywrightService`, `UvicornService`, `AlembicService` 等。

### 6.5 配置管理 (`config.yaml`)
项目的核心配置都集中在位于 `config/` 目录下的 `config.yaml` 文件中。AI代理在开发过程中，如果需要读取配置或添加新的配置项，务必理解本节内容。
-   **配置文件的来源与结构**:
    -   用户需将 `config/config_demo.yaml` 复制并重命名为 `config/config.yaml`。
    -   YAML 格式，层级结构，具体可配置项参考 `config_demo.yaml`。
-   **配置的加载与访问 (`core.config.GlobalConfig`)**:
    -   使用 Pydantic 模型 `core.config.GlobalConfig` 定义和校验配置。
    -   代码中通过 `config = create(GlobalConfig)` 获取实例，然后通过属性 (如 `config.Master`) 访问。
-   **修改配置**:
    -   通常需要**重启机器人**生效。
    -   可通过 `--set-config` 启动 TUI 工具 (`utils.tui.py`) 修改 `config.yaml` 文件。
    -   目前无运行时配置热重载。
-   **添加新的配置项**:
    1.  在 `core.config.GlobalConfig` 或其内嵌 Pydantic 模型中添加新字段 (类型、默认值)。
    2.  在 `config/config_demo.yaml` 中添加对应项的说明和示例值。
    3.  代码中使用 `config.new_item` 访问。
    4.  通知用户在其 `config.yaml` 中手动添加或通过TUI工具配置。
-   **环境变量配置 (`utils.readenv.py`)**:
    -   支持通过环境变量初始化部分配置，并会保存到 `config.yaml`。

### 6.6 数据库交互与迁移
`xiaomai-bot` 使用数据库来持久化存储多种信息。项目采用 SQLAlchemy 作为 ORM 框架，并结合 Alembic 进行数据库结构的版本控制和迁移。
-   **ORM 模型定义 (`core/orm/tables.py`)**:
    -   所有数据表结构在此定义，继承自 `orm.Base`。
    -   示例表: `MemberPerm`, `GroupPerm`, `ChatRecord` 等。
    -   AI代理进行数据库相关开发前必须查阅此文件。
-   **数据库操作 (通过 `core.orm.orm` 封装)**:
    -   项目封装了常用的数据库操作方法，如 `await orm.fetch_one()`, `await orm.fetch_all()`, `await orm.insert()`, `await orm.update()`, `await orm.insert_or_update()` 等。
    -   AI代理应优先使用这些封装方法。
-   **数据库初始化与表创建**:
    -   Alembic 用于数据库模式版本控制。
    -   `core.bot.Umaru.alembic()` 处理 Alembic 初始化和版本检查。
    -   在特定异常情况下 (如数据库文件不存在)，`utils/alembic.py` 中的 `AlembicService` 会触发 `await orm.create_all()` 来自动创建所有表。
    -   `README.md` 中保留 `sqlite3` 手动创建空数据库文件的步骤是为了保证此流程的稳定性。
-   **数据库迁移 (当模型变更时)**:
    -   若修改了 `core/orm/tables.py` 中的模型，**必须生成并应用数据库迁移**。
    -   **推荐手动流程**:
        1.  `alembic revision --autogenerate -m "migration_message"` (可能需 `poetry run` 或 `uv run` 前缀)
        2.  审查生成的迁移脚本 (`alembic/versions/`)。
        3.  `alembic upgrade head`
    -   `Umaru.alembic()` 中自动应用迁移的命令当前被注释，提示用户手动操作。

### 6.7 通用开发流程建议
为帮助AI代理高效、规范地参与项目开发，建议遵循以下流程：
-   **1. 理解需求与现有功能**: 提问，检查重复，阅读文档。
-   **2. 创建和切换到特性分支**: 遵循 "4.1 分支命名规范" (`git checkout -b type/description v3`)。
-   **3. 实现功能/修复Bug**:
    -   **新功能 (插件)**: 参考 6.3, 6.4, 6.5, 6.6 进行开发。
    -   **Bug修复**: 复现 -> 定位 (利用日志和调试器) -> 修复 -> (推荐)添加回归测试。
-   **4. 编写与运行测试 (如果适用)**: 鼓励为核心逻辑编写测试。
-   **5. 代码格式化与规范检查**: 本地安装 `pre-commit` 钩子，运行 `pre-commit run --all-files` 并修复问题。
-   **6. 编写清晰的 Commit Message**: 遵循 "4.2 Commit Message 规范" (Conventional Commits)。
-   **7. (可选) 合并最新的主分支代码**: 定期 `git merge v3` 到特性分支。
-   **8. 推送特性分支到远程仓库**。
-   **9. 创建 Pull Request (PR)**: 向 `v3` 分支提PR，遵循 "4.3 PR 标题" 和 "4.4 PR 描述"。
-   **10. 跟进 CI 检查与 Code Review**: 确保CI通过，积极响应Review意见。
-   **11. PR 合并后清理**: 删除本地和远程的已合并特性分支。
---
