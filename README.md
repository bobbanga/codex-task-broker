# Codex Task Broker / Codex 任务管家

[English](README.en.md) | 简体中文

让 Codex 把一件边界清晰的编码任务交给另一个编码工具去做，然后自己独立核验结果。

你写一份 Run Request，说明改哪个仓库、允许动哪些文件、用什么命令验证。`codex-task-broker`
据此调用一次编码工具，等它结束后重新跑一遍 Git 与测试检查，不采信它的自述，最后停在
`REVIEW_READY`，把一份可核对的证据交回给你审阅。

它解决的问题是：委托出去的改动，你不必靠对方的说法来判断是否可信。

兼容的旧版 Run Request 仍使用 `mock_only` 模式；新的 broker 入口提供 WorkBuddy
适配器，但必须先通过 `doctor` 能力检查。协议版本为 V0.9a。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| CLI 版本 | `0.1.0` |
| 支持模式 | `mock_only` 与 WorkBuddy broker |
| Python | 3.11 及以上 |
| GitHub | 公开 |
| PyPI | 尚未发布 |
| 真实 WorkBuddy adapter | 已接入，需本机 doctor 通过后运行 |

## 安装

从本地源码安装：

```powershell
py -3 -m pip install .
```

从 GitHub 安装：

```powershell
py -3 -m pip install "git+https://github.com/bobbanga/codex-task-broker.git"
```

本项目尚未发布到 PyPI。

## 使用

```powershell
codex-broker validate <run-request.json>
codex-broker run <run-request.json>
codex-broker doctor --executor workbuddy --json
codex-broker run --repo <repository> --brief <brief.json> --executor workbuddy --json
```

- `validate` 只校验请求；成功时返回 `VALIDATED`，不会启动 Contributor。
- `run` 会重复执行预检，只启动一次显式配置的 Contributor，将证据写入外部 `run_store_path`，然后停在 `REVIEW_READY`。
- 两个命令都向 stdout 输出一个 JSON 对象；诊断信息写入 stderr。

Run Request 字段见[协议文档](docs/protocol.md)，机器校验见
[JSON Schema](schemas/run-request.schema.json)，最小示例见
[`examples/minimal-run-request.json`](examples/minimal-run-request.json)。

## 安全边界

- 兼容入口接受 `mode="mock_only"`；WorkBuddy 入口使用显式任务 brief。
- Run Request JSON 是运行输入的唯一可编辑主人。
- Contributor 和验证命令必须使用 argv 数组，并以 `shell=false` 启动。
- 子进程只能收到显式允许的环境变量。
- `run_store_path` 必须位于目标 checkout 之外。
- Contributor 自述不是权威证据；Runner 会重新计算 Git、测试和 artifact 事实。
- `REVIEW_READY` 只是交给 Codex 审阅，不代表批准。
- WorkBuddy 运行必须先通过 `doctor`，并在完成后停在 Codex review。

WorkBuddy 是当前 MVP 阶段唯一的 executor adapter。它不会自动绕过权限、合并、推送或发布。

## 源码边界

Python 导入命名空间为 `codex_task_broker`，独立分发包和源码仓库的名称均为 `codex-task-broker`。

- [协议说明](docs/protocol.md)
- [路线图](ROADMAP.md)
- [变更日志](CHANGELOG.md)

## 开发

```powershell
py -3 -m pip install -e ".[dev]"
py -3 -m pytest -q
py -3 -m ruff check src tests
```

Runtime 不依赖第三方 Python 包。修改前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)
中必须保持的设计约束；安全漏洞请按 [SECURITY.md](SECURITY.md) 私下上报；社区行为准则见
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

[MIT](LICENSE)
