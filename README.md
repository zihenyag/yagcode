# YagCode

YagCode is a local coding agent workbench for scoped, reviewable code changes.

## 项目简介

YagCode 面向需要让 AI 修改本地代码、同时保留审查权和回滚能力的开发者。用户把一个代码问题交给本地 Agent，YagCode 负责组织上下文、调用 LLM Provider、解析结构化 action、执行受控工具、回灌测试反馈，并在最终接受前展示 diff、验证证据和回滚点。

这个仓库包含完整产品实现：agent loop、action parser、tool dispatcher、memory、feedback、governance、credential flow、桌面工作台和 CLI 入口都在本项目内实现，并且可以在 mock/stub LLM 下离线验证。

## 安装

开发环境：

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

安装后可以直接进入 CLI 工作台，也可以查看健康状态和版本：

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

## 获取项目

项目源码、说明、版本历史和发布产物都在 GitHub：

- GitHub: https://github.com/zihenyag/yagcode
- README: https://github.com/zihenyag/yagcode#readme
- Releases: https://github.com/zihenyag/yagcode/releases
- Pages: https://zihenyag.github.io/yagcode/

发布版本由 GitHub Release 提供；本地开发直接按上面的安装步骤运行即可。

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
- GitHub Pages 是静态产品落地页，只展示产品、截图和下载/源码链接；它不接收 key、文件或任务输入，也不连接 Provider、sidecar、shell 或在线 Agent runtime。

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

- 当前发布产物未签名；macOS Gatekeeper 和 Windows SmartScreen 可能提示未知开发者。
- Linux 桌面应用和 macOS Intel 构建暂不提供。
- Release 与 Pages 由 GitHub Actions 生成；本地 checkout 默认不包含 `dist/` 产物。

## 第三方依赖与许可证

第三方 runtime 与构建依赖记录在 `LICENSES.md`、`THIRD_PARTY_NOTICES.md` 和 `packaging/shipped-runtime.json`。核心 Harness 代码为本项目实现；第三方库只作为底层 HTTP、API、UI、打包、测试或系统集成组件使用。
