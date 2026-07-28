# YagCode v0.1.0

YagCode 是一个本地 Coding Agent 工作台，面向需要让 AI 修改代码、同时保留审查权、回滚能力和权限控制的开发者。

## 本次发布

- 提供完整的本地 Agent loop：结构化 action 解析、受控工具执行、测试反馈回灌、记忆、权限治理和可回滚接受流程。
- 提供 Electron 桌面工作台：项目/线程管理、Provider 配置、对话运行、Changes/Diff 审阅、可信确认和本地 sidecar 生命周期。
- 提供独立 CLI/TUI 入口：运行 `yagcode` 进入终端工作台，也支持 `yagcode health` 和 `yagcode version` 做自动化检查。
- 提供静态 GitHub Pages 落地页：展示产品定位、截图和四个平台下载入口。
- 提供 GitHub Actions 发布链路：离线测试、Pages 部署、macOS/Windows 桌面端和 CLI 打包、manifest 校验与 Release 上传。

## 下载说明

- YagCode Desktop for macOS: `yagcode-mac-arm64.dmg`
- YagCode Desktop for Windows: `yagcode-win-x64.exe`
- YagCode CLI for macOS: `yagcode-cli-mac-arm64.tar.gz`
- YagCode CLI for Windows: `yagcode-cli-win-x64.zip`
- 校验文件: `release-manifest.json`

## 验证说明

发布产物由 GitHub Actions 在对应平台构建并 smoke：

- macOS 桌面端和 CLI 在 `macos-15` runner 上构建、manifest 校验和 smoke。
- Windows 桌面端和 CLI 在 `windows-2022` runner 上构建、安装、manifest 校验和 smoke。
- Release job 会合并四个平台 manifest，并把四个产物和 `release-manifest.json` 上传到 GitHub Release。

## 注意事项

当前发布产物未签名。macOS Gatekeeper 和 Windows SmartScreen 可能提示未知开发者，请先核对 `release-manifest.json` 中的 SHA-256，再按系统提示继续安装。
