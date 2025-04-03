# ✅ 版本发布流程 Checklist

> 本文档用于规范化版本发布流程，确保每次发布都**一致、可审计、可追溯**  
> 当前项目版本管理方案基于：
>
> - [`bump-my-version`](https://github.com/callowayproject/bump-my-version)：版本号控制
> - 自定义脚本 `bump.py`：自动封装版本更新、changelog 生成、tag 创建、git 提交
> - [`git-cliff`](https://github.com/orhun/git-cliff)：自动生成 changelog
> - 版本号遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)

---

## 📦 准备发布

### ✅ 1. 确保主分支是干净的

- 分支切换至主分支（如 `main` 或 `master`）：

  ```bash
  git checkout main
  git pull origin main
  ```

- 所有待发布的功能已合并进主分支
- 本地无未提交更改（`git status` 应为空）

---

## 🧰 2. 运行发布脚本 bump.py

使用封装好的脚本自动完成以下内容：

- 更新版本号（修改 `pyproject.toml`、`core/__init__.py` 等）
- 同步 `uv.lock` 中的版本元信息
- 自动生成 `CHANGELOG.md`（调用 `git-cliff`）
- 使用规范化格式提交变更
- 自动打 Git tag（如 `v1.2.4`）

### 🎯 命令示例

```bash
# 增加补丁版本号（默认添加预发布标签）
python -m utils.bump patch --commit --tag --changelog

# 增加补丁版本号（不添加预发布标签）
python -m utils.bump patch --no-pre --commit --tag --changelog

# 使用其他版本级别
python -m utils.bump minor --no-pre --commit --tag --changelog
python -m utils.bump major --no-pre --commit --tag --changelog

# 添加预发布标签
python -m utils.bump alpha --commit --tag
python -m utils.bump beta --commit --tag
python -m utils.bump rc --commit --tag

# 发布正式版（移除预发布标签）
python -m utils.bump release --commit --tag --changelog

# 直接指定目标版本号（跨版本升级，如从预发布版本直接升级到正式版）
python -m utils.bump patch --new-version 0.2.0 --commit --tag --changelog

# 强制更新版本号（当 bump-my-version 自动更新失败时）
python -m utils.bump patch --new-version 0.2.0 --force --commit --tag
```

---

## 📜 3. 自动生成的内容

### ✅ 提交信息格式

```text
chore(release): 版本更新 v1.2.3 → v1.2.4
```

### ✅ 更新的文件包括

- `pyproject.toml`：版本号
- `core/__init__.py`：`__version__`
- `uv.lock`：元信息 version
- `CHANGELOG.md`：根据 git 提交历史生成（分组）

---

## 🏷️ 4. Git tag 自动生成

- 生成格式为 `v1.2.4`
- tag 创建在主分支最新提交上
- 可用于 CI/CD 构建与发布流程触发器

---

## ☁️ 5. 推送提交与 tag

完成变更后，统一推送代码和 tag：

```bash
git push origin main --tags
```

---

## 🧪 6. 后续验证

- CI/CD 会监听 tag 推送并触发构建
- 可在 Git 平台（如 Gitea、GitHub）中验证：
  - tag 是否存在
  - changelog 是否正确
  - changelog 段落是否匹配该版本

---

## 🔒 7. 注意事项与最佳实践

| 项目                  | 说明                             |
|---------------------|--------------------------------|
| tag 必须在主分支上创建       | 避免 tag 指向临时或未发布的提交             |
| 版本号应与 changelog 对应  | 生成日志前确保 `git log` 包含完整提交       |
| commit message 遵循规范 | `chore(release): 版本更新 vX → vY` |
| 每次发布都 bump          | 避免重复使用旧版本号                     |
| 将 `uv.lock` 纳入 Git  | 保证依赖版本一致，避免构建漂移                |

---

## 🔄 8. 版本号管理策略

### 版本号格式

我们的版本号遵循如下格式：

- 标准版本：`X.Y.Z`（例如 `3.0.0`）
- 预发布版本：`X.Y.Z-labelN`（例如 `3.0.1-dev1`、`3.1.0-rc2`）

### 预发布版本流程

典型的版本发布流程为：

1. 开发阶段：`3.0.0` → `3.0.1-dev1` → `3.0.1-dev2`...
2. 内部测试：`3.0.1-alpha1` → `3.0.1-alpha2`...
3. 外部测试：`3.0.1-beta1` → `3.0.1-beta2`...
4. 发布候选：`3.0.1-rc1` → `3.0.1-rc2`...
5. 正式发布：`3.0.1`

### 何时使用 `--no-pre` 选项

使用 `--no-pre` 选项在以下情况下特别有用：

- 发布紧急修复（hotfix）直接发布正式版本
- 跳过预发布流程直接发布小功能更新
- 直接从一个正式版升级到另一个正式版

```bash
# 直接升级到下一个补丁版本而不添加预发布标签
python -m utils.bump patch --no-pre --commit --tag --changelog
```

### 何时使用 `--new-version` 和 `--force` 选项

使用 `--new-version` 选项在以下情况下特别有用：

- 从预发布版本直接升级到指定的正式版本（如 `0.1.1-dev1` → `0.2.0`）
- 跳过多个版本进行升级（如 `1.0.0` → `2.0.0`），不遵循常规版本增量
- 当需要进行版本号规范化调整时

```bash
# 直接指定目标版本号
python -m utils.bump patch --new-version 0.2.0 --commit --tag
```

当 bump-my-version 自动更新版本号失败时（特别是从预发布版本升级时），可以使用 `--force` 选项强制更新：

```bash
# 强制更新版本号
python -m utils.bump patch --new-version 0.2.0 --force --commit --tag
```

---

## ✅ 参考命令速查表

| 操作                       | 封装脚本方式                                                   | 直接命令方式                                                              |
|--------------------------|----------------------------------------------------------|---------------------------------------------------------------------|
| 增加补丁版本（不带预发布标签）          | `python -m utils.bump patch --no-pre`                    | `bump-my-version bump patch --serialize "{major}.{minor}.{patch}"`  |
| 增加补丁版本（添加预发布标签）          | `python -m utils.bump patch`                             | `bump-my-version bump patch`                                        |
| 增加次版本（不带预发布标签）           | `python -m utils.bump minor --no-pre`                    | `bump-my-version bump minor --serialize "{major}.{minor}.{patch}"`  |
| 增加主版本（不带预发布标签）           | `python -m utils.bump major --no-pre`                    | `bump-my-version bump major --serialize "{major}.{minor}.{patch}"`  |
| 设为 alpha 预发布版本           | `python -m utils.bump alpha`                             | `bump-my-version bump pre alpha`                                    |
| 设为 beta 预发布版本            | `python -m utils.bump beta`                              | `bump-my-version bump pre beta`                                     |
| 设为 rc 预发布版本              | `python -m utils.bump rc`                                | `bump-my-version bump pre rc`                                       |
| 发布正式版（移除预发布标签）           | `python -m utils.bump release`                           | `bump-my-version bump pre final`                                    |
| 指定具体版本号                  | `python -m utils.bump patch --new-version X.Y.Z`         | `bump-my-version bump --new-version X.Y.Z`                          |
| 强制更新版本号（当自动更新失败时）        | `python -m utils.bump patch --new-version X.Y.Z --force` | 不支持，需使用脚本                                                           |
| 从预发布版本直接升级到正式版本（如 0.2.0） | `python -m utils.bump patch --new-version 0.2.0`         | `bump-my-version bump --new-version 0.2.0 --current-version "当前版本"` |
| 查看当前版本                   | `python -m utils.bump info`                              | `bump-my-version show current_version`                              |

---

## ✅ 推荐工具版本依赖

| 工具                | 推荐安装方式                             | 说明                                 |
|-------------------|------------------------------------|------------------------------------|
| `bump-my-version` | `uv tool install bump-my-version`  | 使用 uv 工具安装，而非作为项目依赖                |
| `git-cliff`       | 下载二进制或使用 `cargo install git-cliff` | 用于生成规范化的 changelog                 |
| `uv`              | 官方安装指南                             | 用于快速的依赖管理与 lock 文件更新               |
| `tomli`           | 项目依赖                               | 用于解析 pyproject.toml（Python < 3.11） |
