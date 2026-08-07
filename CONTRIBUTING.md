# Contributing / 贡献指南

Thanks for helping improve NGA Wolf Watcher. Small, focused issues and pull requests are easiest to review.

感谢你帮助改进 NGA Wolf Watcher。范围清晰、目标明确的 Issue 和 Pull Request 最容易处理。

## Before Reporting Issues / 提交 Issue 前

- Search existing issues first. / 请先搜索已有 Issue。
- Do not include NGA Cookies, bot tokens, webhook URLs, email passwords, or other secrets. / 不要提交 NGA Cookie、机器人 Token、Webhook URL、邮箱密码或其他敏感信息。
- Include the runtime you use: Windows installer, Windows portable, Linux install, or source/CLI. / 请说明运行方式：Windows 安装版、Windows 便携版、Linux 安装版或源码/CLI。
- Include the release version or commit hash when possible. / 尽量提供 Release 版本或提交哈希。

## Development Setup / 开发环境

Python / Python 环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pytest
```

Web UI / 前端：

```bash
cd webui
npm ci
```

## Validation / 验证

Run the focused checks before opening a pull request.

提交 Pull Request 前建议先运行以下检查：

```bash
python -m pytest tests
python -m py_compile $(git ls-files '*.py')
cd webui && npm run build
```

## Pull Requests / 提交 PR

- Keep changes scoped to one fix or feature. / 每个 PR 尽量只处理一个修复或功能。
- Update documentation when behavior, commands, config fields, or installation steps change. / 行为、命令、配置字段或安装步骤变化时，请同步更新文档。
- Add or update tests for bug fixes and shared behavior. / 修复 bug 或改动共享逻辑时，请补充或更新测试。
- Keep generated local files, secrets, logs, and runtime configs out of commits. / 不要提交本地生成文件、敏感信息、日志或运行时配置。
