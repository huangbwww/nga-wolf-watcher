# Security Policy / 安全策略

NGA Wolf Watcher handles sensitive local configuration such as NGA Cookies, bot credentials, webhook URLs, email passwords, and local automation context. Treat those values as secrets.

NGA Wolf Watcher 会处理 NGA Cookie、机器人凭据、Webhook URL、邮箱密码和本地自动化上下文等敏感配置。请把这些内容都当作敏感信息处理。

## Reporting Security Issues / 报告安全问题

Please do not post secrets, exploit details, private logs, or live webhook URLs in public issues.

请不要在公开 Issue 中粘贴敏感信息、漏洞细节、私人日志或仍然有效的 Webhook URL。

For sensitive reports, use GitHub's private vulnerability reporting flow if it is available for this repository. If private reporting is not available, open a public issue with a minimal description and no secrets, then coordinate details privately with the maintainer.

如果该仓库启用了 GitHub 私密漏洞报告，请优先使用该流程。若不可用，可以先开一个不包含敏感信息的公开 Issue，只描述最小背景，再与维护者私下沟通细节。

## Supported Versions / 支持版本

Security fixes target the latest release and the `main` branch.

安全修复主要面向最新 Release 和 `main` 分支。

## User Responsibilities / 使用者责任

- Store Cookies, tokens, and passwords only in local config files or environment-specific secret storage. / 只在本地配置文件或环境专用的密钥存储中保存 Cookie、Token 和密码。
- Redact secrets before sharing logs, screenshots, config files, or crash reports. / 分享日志、截图、配置文件或崩溃报告前，请先移除敏感信息。
- Rotate any token, Cookie, webhook, or password that was committed, pasted into an issue, or shared in chat. / 如果 Token、Cookie、Webhook 或密码被提交、贴到 Issue 或发到聊天中，请尽快轮换。
- Confirm that your use of automated access, polling, forwarding, and bot interaction follows the rules of the relevant platforms and your local laws. / 请自行确认自动化访问、轮询、消息转发和机器人交互符合相关平台规则和当地法律法规。
