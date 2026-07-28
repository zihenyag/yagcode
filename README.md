# YagCode

YagCode is a local Coding Agent Harness for scoped, reviewable code changes.

## 项目简介

YagCode 面向需要让 AI 修改本地代码、又不想直接交出工作区控制权的开发者。用户把一个代码问题交给本地 Agent，Harness 负责组织上下文、调用单次 LLM Provider、解析结构化 action、执行受控工具、回灌测试反馈，并在最终接受前展示 diff、验证证据和回滚点。

核心实现由本仓库代码完成：agent loop、action parser、tool dispatcher、memory、feedback、governance、credential flow 和 stop condition 都可在 mock/stub LLM 下离线测试。

## 安装

开发环境：

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

本地 CLI 可通过 editable install 暴露：

```bash
yagcode
yagcode health
yagcode version
```

桌面端开发联调：

```bash
npm run dev:desktop --workspace apps/desktop
```

## 运行

CLI 默认进入终端工作台：

```bash
yagcode
```

常用本地验证：

```bash
npm run test:all
npm run demo
npm run scan:secrets -- --scope worktree --scope history
```

桌面端使用 Electron main 启动本地 Python sidecar。真实 Provider key 通过产品凭据流程写入系统 keyring；测试和机制演示使用 scripted/mock Provider，不需要真实 key。

## 分发

计划发布渠道是 GitHub Release。桌面端和 CLI 端分开打包：

- macOS 13+ Apple Silicon 桌面端：`yagcode-mac-arm64.dmg`
- Windows 10/11 x64 桌面端：`yagcode-win-x64.exe`
- macOS CLI：`yagcode-cli-mac-arm64.tar.gz`
- Windows CLI：`yagcode-cli-win-x64.zip`

“单文件”指用户在 Release 页面下载的安装包或压缩包。安装后的 Electron App、Python sidecar 或 CLI 解包目录可以包含多个 runtime 文件。

## 目录结构

```text
apps/desktop/              Electron main/preload 和 React renderer
docs/landing/              GitHub Pages 根落地页资源
packages/contracts/        Python/TypeScript 共享 API contract
packages/ui/               桌面 UI 原语和设计 token
packaging/                 Electron/PyInstaller runtime inventory 与 builder 配置
scripts/                   测试、打包、manifest、CI evidence 和 Pages 构建脚本
src/yagcode/               Harness core、policy、tools、memory、providers、API、CLI
tests/                     mock LLM 单元测试、集成测试、对抗测试和发布合同测试
```

## 安全边界

YagCode 的安全边界是本机操作系统账号和用户明确授权的项目目录。Agent 默认不能越界读写、不能读取明文凭据、不能绕过危险命令审批、不能自动 push/release/deploy。

主要机制：

- 路径、shell、网络、隐私和发布动作由确定性 policy/capability code 拦截。
- 真实 key 存在 OS keyring；状态查询只返回存在与否、Provider 和更新时间，不回显明文。
- 工作区修改在隔离 worktree 或等价副本中完成；用户接受前不覆盖真实工作区。
- `scan:secrets` 覆盖 worktree 和 Git history，输出只包含 detector 与位置，不打印匹配值。
- GitHub Pages 是静态产品落地页，只展示产品、截图、机制演示命令和下载/源码链接；它不接收 key、文件或任务输入，也不连接 Provider、sidecar、shell 或在线 Agent runtime。

## 目标机器凭据配置

目标机器第一次使用真实 Provider 时，通过桌面端或 CLI 的隐藏输入录入 key。支持状态查看、更新和清除；查看状态不会显示 key。

支持的 Provider 路径包括 OpenAI-compatible endpoint、Qwen、GLM、DeepSeek 和 NJU SE Hub。当前不支持 Anthropic。离线测试和机制演示使用 scripted/mock Provider，不需要真实网络 key。

## 测试与机制演示

完整本地门禁：

```bash
npm run test:all
```

确定性机制演示：

```bash
npm run demo
```

演示覆盖危险动作拦截、失败反馈改变下一步 action、隔离工作区与 checkpoint 回滚。

## 已知限制

- macOS Intel、Linux 桌面安装包和 universal binary 不在本项目范围内。
- 当前安装包未签名；macOS Gatekeeper 和 Windows SmartScreen 可能提示未知开发者。
- Windows 桌面 `.exe` 与 CLI `.zip` 需要在 Windows runner 上构建和 smoke。
- Release、Pages 和平台包由 GitHub Actions 生成；本地 checkout 默认不包含 `dist/` 产物。

## 第三方依赖与许可证

第三方 runtime 与构建依赖记录在 `LICENSES.md`、`THIRD_PARTY_NOTICES.md` 和 `packaging/shipped-runtime.json`。核心 Harness 代码为本项目实现；第三方库只作为底层 HTTP、API、UI、打包、测试或系统集成组件使用。
