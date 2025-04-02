# ✅ 版本发布流程 Checklist

> 本文档用于规范化版本发布流程，确保每次发布都**一致、可审计、可追溯**  
> 当前项目版本管理方案基于：
> - [`bump2version`](https://github.com/c4urself/bump2version)：版本号控制
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

- 更新版本号（修改 `pyproject.toml`、`.bumpversion.cfg`、`core/__init__.py` 等）
- 同步 `uv.lock` 中的版本元信息
- 自动生成 `CHANGELOG.md`（调用 `git-cliff`）
- 使用规范化格式提交变更
- 自动打 Git tag（如 `v1.2.4`）

### 🎯 命令示例：

```bash
python -m utils.bump patch --commit --tag --changelog
```

或使用其他版本级别（major / minor / pre-release）：

```bash
python -m utils.bump minor --commit --tag --changelog
python -m utils.bump alpha --commit --tag
```

---

## 📜 3. 自动生成的内容

### ✅ 提交信息格式：

```
chore(release): 版本更新 v1.2.3 → v1.2.4
```

### ✅ 更新的文件包括：

- `pyproject.toml`：版本号
- `core/__init__.py`：`__version__`
- `.bumpversion.cfg`：current_version
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

## ✅ 参考命令速查表

| 操作               | 命令                                                        |
|------------------|-----------------------------------------------------------|
| 增加补丁版本           | `python -m utils.bump patch --commit --tag --changelog`   |
| 增加次版本            | `python -m utils.bump minor --commit --tag --changelog`   |
| 发布正式版（移除 pre 标签） | `python -m utils.bump release --commit --tag --changelog` |
| 添加预发布标签          | `python -m utils.bump rc --commit --tag`                  |
| 仅查看当前版本          | `python -m utils.bump info`                               |

---

## ✅ 推荐工具版本依赖

| 工具             | 推荐安装方式                                     |
|----------------|--------------------------------------------|
| `bump2version` | `uv add bump2version`                      |
| `git-cliff`    | 下载二进制或使用 `cargo install git-cliff`         |
| `uv`           | 用于依赖管理与 lock 更新                            |
| `tomli`        | Python 解析 pyproject.toml（Python < 3.11 必装） |
