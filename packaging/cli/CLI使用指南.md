# YagCode CLI 使用指南

YagCode CLI 是 YagCode 的终端工作台。它和桌面端使用同一套本地治理流程：读取当前 Git 项目，绑定 Provider，创建线程，运行 Agent，查看候选 diff，最后由用户接受、拒绝或回滚。桌面端提供图形界面；CLI 用命令在终端里完成同样的步骤。

## 1. 解压并进入项目

macOS:

```bash
tar -xzf yagcode-cli-mac-arm64.tar.gz
cd yagcode-cli
cd /path/to/your/git-project
/path/to/yagcode-cli/yagcode-cli
```

Windows PowerShell:

```powershell
Expand-Archive .\yagcode-cli-win-x64.zip
cd .\yagcode-cli
cd C:\path\to\your\git-project
.\yagcode-cli.exe
```

也可以把 `yagcode-cli` 或 `yagcode-cli.exe` 加入 `PATH`，之后在任意 Git 项目目录里直接运行。

## 2. 绑定 Provider

进入 TUI 后先绑定模型 Provider：

```text
/provider add openai --model gpt-5.6-sol
```

自定义 Provider 需要提供 HTTPS 接口地址：

```text
/provider add localai --label "Local AI" --base-url https://llm.example.com/v1/chat/completions --docs-url https://llm.example.com/docs --model localai-coder
```

CLI 会在终端里隐藏输入 API key。key 不会打印到屏幕、日志或 diff 里，验证通过后写入系统 keyring。内置 Provider 可以只写厂商名和模型；自定义 Provider 必须写 `--base-url`，建议同时写 `--docs-url`，方便之后审计配置来源。

常用命令：

```text
/provider status
/model gpt-5.6-sol
/plan on
/plan off
```

切换模型前需要当前 run 已停止或结束。

## 3. 创建线程并输入任务

```text
/thread 修复登录页空指针
请阅读 src/login.py，修复用户信息为空时的崩溃，并给我看 diff。
```

线程标题只用于本地工作台显示。真正发给 Provider 的上下文来自你输入的任务内容、工具观察结果和本地治理状态。

## 4. 运行、审查和确认

```text
/run
/changes
/diff
/accept
```

`/run` 会执行受控 Agent step。Agent 只能通过结构化 action 读取文件、搜索、应用补丁和请求审查。生成候选修改后，先用 `/changes` 看文件列表，再用 `/diff` 看具体改动。确认无误后执行 `/accept`。

## 5. 拒绝和回滚

```text
/reject
/rollback checkpoint-1
```

`/reject` 会拒绝当前审查项。需要撤回候选修改时，执行 `/rollback <checkpoint>`。CLI 会按 checkpoint 快照恢复真实工作区里的相关文件。

如果忘记 checkpoint 名称，可以先看 `/memory` 或 `/audit` 的记录；当前实现会在创建线程和生成候选修改时记录 checkpoint。

## 6. 查看记忆和审计

```text
/memory
/audit
/quit
```

`/memory` 展示项目记忆。`/audit` 展示本地关键事件，例如打开项目、绑定 API、启动 run、完成 run、接受审查和回滚。`/quit` 退出 TUI。

## 7. 自动化和诊断入口

这些命令主要用于 CI、smoke 或演示：

```text
yagcode-cli health
yagcode-cli version
yagcode-cli demo --workspace ./tmp-demo --json
```

`health` 和 `version` 只检查 CLI 本身。`demo` 使用本地脚本化流程复现机制演示，适合验证安装包和离线测试环境。
