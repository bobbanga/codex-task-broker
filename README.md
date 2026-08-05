# codex-workbuddy-coordinator

[English](README.en.md) | 简体中文

`codex-workbuddy-coordinator` 是 `codex-workbuddy` 跨项目 CLI 的正式源码仓库。它用 V0.9a `mock_only` 协议处理一份显式 Run Request，调用一次受限的本地 Contributor，重新核验 Git 与测试证据，并停在 `REVIEW_READY` 等待 Codex 审阅。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| CLI 版本 | `0.1.0` |
| 支持模式 | 仅 `mock_only` |
| Python | 3.11 及以上 |
| GitHub | 公开 |
| PyPI | 尚未发布 |
| 真实 WorkBuddy adapter | 尚未认证，也未实现 |

## 安装

目前可以从 GitHub 安装：

```powershell
py -3 -m pip install "git+https://github.com/bobbanga/codex-workbuddy-coordinator.git"
```

从本地源码安装：

```powershell
py -3 -m pip install .
```

PyPI 发布将在跨项目观察、包元数据、CI 和 TestPyPI 验证通过后单独进行。

## 使用

```powershell
codex-workbuddy validate <run-request.json>
codex-workbuddy run <run-request.json>
```

- `validate` 只校验请求；成功时返回 `VALIDATED`，不会启动 Contributor。
- `run` 会重复执行预检，只启动一次显式配置的 Contributor，将证据写入外部 `run_store_path`，然后停在 `REVIEW_READY`。
- 两个命令都向 stdout 输出一个 JSON 对象；诊断信息写入 stderr。

Run Request 字段和示例见 [协议文档](docs/protocol.md)。

## 安全边界

- 只接受 `mode="mock_only"`。
- Run Request JSON 是运行输入的唯一可编辑主人。
- Contributor 和验证命令必须使用 argv 数组，并以 `shell=false` 启动。
- 子进程只能收到显式允许的环境变量。
- `run_store_path` 必须位于目标 checkout 之外。
- Contributor 自述不是权威证据；Runner 会重新计算 Git、测试和 artifact 事实。
- `REVIEW_READY` 只是交给 Codex 审阅，不代表批准。
- CLI 不包含调用真实 WorkBuddy 的路径。

真实 WorkBuddy adapter 需要原生 narrow/no-tools 模式，或另行支持和认证的 API adapter；公开本仓库并不会自动开放该能力。

## 源码边界

Python 导入命名空间暂时保留为 `bob_skills.codex_workbuddy_coordinator`，以兼容 V0.1。独立分发包和源码仓库的名称均为 `codex-workbuddy-coordinator`。

- [项目状态](docs/project-status.md)
- [协议说明](docs/protocol.md)
- [设计](docs/superpowers/specs/2026-08-05-codex-workbuddy-cross-project-cli-design.md)
- [实现计划](docs/superpowers/plans/2026-08-05-codex-workbuddy-cross-project-cli.md)

## 开发

```powershell
py -3 -m pytest -q
```

Runtime 不依赖第三方 Python 包。远端变更、包发布以及任何真实 WorkBuddy adapter 工作仍需要 Bob 明确批准。
