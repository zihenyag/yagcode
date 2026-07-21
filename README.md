# yagcode

YagCode 期末项目：Coding Agent Harness。


- [Brainstorming 过程与用户决策](design notes)
- [Gate 3 产品规约草案](product spec)
- [初始化候选规划（历史材料）](PROJECT_PLANNING.md)
- [项目与项目要求](YagCode_product brief_A_Coding_Agent_Harness.md)
- [Agent 协作记录](agent log)

当前只允许完成并审阅项目 `product spec`；批准后才由 `writing-plans` 生成 `runtime plan`，再进行陌生 Agent 冷启动验证。在这些门禁全部通过前不提交 Harness 业务实现。

## 已确认的运行形态

- 本地 Harness sidecar 采用 Python 3.12、FastAPI、SQLite 和系统 keyring，Agent 内核自行实现。
- 真实产品采用 Electron 桌面壳；Node.js/TypeScript main process 负责窗口、目录选择、通知、关闭拦截、sidecar 生命周期和安装包，不承载 Agent loop。
- React + TypeScript + Vite renderer 负责 UI，并启用 `contextIsolation`、sandbox、严格 CSP、禁用 `nodeIntegration`；preload 只暴露最小 typed IPC。
- Python Harness 打包为平台 sidecar，由 Electron 启动并监控；FastAPI 在随机 loopback 端口提供带随机握手令牌的 HTTP/SSE API。
- macOS 与 Windows 复用 Electron、React 和 Python 源码；GitHub Release 是唯一桌面分发渠道，每个平台只要求用户下载一个安装产物：macOS 13+ Apple Silicon `.dmg` 或 Windows 10/11 x64 NSIS `.exe`。这里的“单文件”指 Release 下载物，安装后的 App 可以包含 Electron、renderer 和 Python sidecar 等多个文件；不支持 macOS Intel，也不构建 universal binary。
- GitHub Pages 根路径提供产品落地页并嵌入 Bilibili 讲解；`/demo/` 提供 fixture-only 安全交互 WebUI，仅用内置 scripted scenario 展示护栏、反馈闭环和 dirty 隔离，不接真实 Provider/sidecar、用户文件、key 或 shell。
- 默认验证策略可由用户覆盖，标准级要求复现原问题、目标与相关测试通过、静态检查通过且 diff 合规。
- 目标仓库按语言无关方式处理；测试、lint、类型检查和构建命令由项目配置声明并进入 allowlist。

## 已确认的模型支持

- OpenAI 为默认主要 Provider，另行官方支持 Qwen、GLM 和 DeepSeek；不支持 Anthropic。
- Harness 每轮只向 Provider 请求一个结构化候选 action，工具执行、反馈、记忆和停机均由本项目代码控制。
- 用户可在同一个 bug 中切换 Provider 或模型，但必须先手动中断运行、保存 checkpoint，再切换并显式恢复；运行中模型选择器禁用。
- scripted/mock Provider 用于离线确定性测试与仓库内机制演示；公网 `/demo/` 只运行浏览器内固定 scenario interpreter，不复用真实 Harness loop，也不接收访客代码。

## 已确认的权限与隐私模型

- 危险操作提供“仅允许本次操作”“始终允许符合此规则的操作”“为当前应用会话启用完全访问模式”三个选择；规则匹配由确定性策略引擎完成。
- 完全访问模式持续到本地应用或服务退出、崩溃或重启，用户可随时提前撤销；它不关闭审计、凭据隔离或数据外发治理。
- 工作区外访问可按外部根目录授予只读或读写权限。Agent 只能使用命名凭据，不能读取、显示或记录明文。
- 隐私数据首次外发前必须预览；确认后形成跨会话、跨 Provider 的持久授权，直到用户撤销或数据范围、隐私类别发生实质变化。
- API key、密码、Token 与私钥永不发送给模型，不能被普通审批或完全访问模式放行。
- 隐私预览、原始对话和工具输出默认永久保存；原始记录可改为保留 30 天、60 天、90 天、180 天、1 年或 2 年，并支持用户主动删除。
- 删除正文后仍永久保留不含 prompt、文件内容、工具输出和凭据的脱敏结构化审计，以维持变更与审批的可追溯性。
- 标准权限自动执行工作区读取、隔离区计划内源码修改和 allowlist 命令；结构性或受保护修改在计划外或 Plan 关闭时审批，完全访问下自动执行但最终标红。
- 完全访问也不能绕过隔离 worktree、人工接受、凭据隔离、首次隐私预览、审计完整性和显式远程发布意图。

## 已确认的任务交互

- bug 默认通过自然语言对话创建，支持日志、截图和工作区文件；结构化任务表单可选展开，并与对话共享同一份任务状态。
- 对话输入框提供 Agent 级“规划模式”开关，默认开启；开启时先只读分析并等待计划确认，关闭时建立 checkpoint 后直接执行。
- 关闭规划模式只跳过写入前的计划签字，不会授予完全访问，也不会绕过危险操作、隐私、凭据或最终 bug 审阅规则。

## 已确认的记忆模型

- 线程状态只服务当前 bug；项目记忆自动形成并只在当前项目复用，用户可随时增加、编辑、固定或删除。
- 运行中新记忆先标为暂定，只供当前运行使用；bug 接受并通过集成验证后转为正式，拒绝后删除正文。
- 跨项目记忆必须由用户确认提升；建议卡片是非阻塞收件箱，不暂停模型、命令或 action loop。
- MVP 使用本地结构化字段、标签和 SQLite FTS 按需检索，不调用外部 embedding 服务，也不把全部历史对话注入模型。

## 已确认的 Agent 与运行模型

- 应用允许用户创建多个无需认证的本地档案；每个档案拥有一个 Agent 配置、多个项目和多个 bug 线程，并按档案 UUID 逻辑隔离项目、线程、设置、凭据、隐私授权与记忆。
- Plan、权限、Provider 配置、模型列表和数据策略属于本地档案下的 Agent，跨该档案的项目与线程共享；当前选中的 Provider/模型属于线程，项目只提供工作区、命令、验证和路径事实。
- 同一项目一次只允许一个线程运行，不同且可写范围不重叠的项目可以并行；规范化仓库身份阻止同一仓库通过路径别名绕过锁。
- 运行期间可切换项目页面并操作其他无冲突项目，但不能删除或卸载正在运行的项目；档案存在任一运行线程时禁止切换档案或正常关闭，必须分别手动停止。
- 运行中可追加文字、日志、截图和文件；新信息在安全 action 边界进入当前运行，旧的在途模型结果会被取消或丢弃。
- 安全命令和项目 allowlist 可自动执行，其他命令进入统一审批；完全访问模式下允许任意 shell，但不解除隐私、凭据与审计约束。
- 本地档案不防止同一操作系统账号下的其他人查看，操作系统用户才是安全边界；删除档案经一次破坏性确认后清除正文、配置、凭据、checkpoint 与审计。
- 每个 bug 具有可覆盖的运行预算；标准值为 30 次模型决策、60 分钟实际运行、20 个文件、1500 行增删和相同错误连续 3 次，达到上限只暂停并等待用户。
- Token 与可靠费用实时显示，金额硬上限默认关闭；Agent 不会因失败自动切换模型，也不能以自然语言完成声明绕过验证。
- 下一请求预计达到模型上下文 70% 时，主循环在 action 边界进入阻塞式压缩；压缩校验通过并合并排队消息后才继续。
- 压缩只替换发送给模型的活动视图，不删除本地原始证据；连续失败 3 次后暂停，由用户选择重试、切换模型或停止。
- Provider 连接中断、`429`、可重试 `5xx` 和超时统一最多自动尝试 5 次；代码声明为幂等的只读工具最多 3 次，均显示退避和尝试记录。
- 写入、commit、push、安装、发布和部署不自动重试；结果不明时先只读对账，再由用户决定是否重试。

## 已确认的项目接入

- 应用安装或首次启动时检测 Git；缺失时从内置受信安装清单选择对应平台与架构的来源，展示版本、来源、大小和权限要求，并在校验哈希或代码签名后安装。
- 已有 Git 仓库直接以实际 worktree 根目录接入；普通目录经用户确认后执行 `git init`，不会自动创建用户 commit 或暂存文件。
- 安装 Git 与初始化目录必须分别确认：前者发生在应用环境预检，后者发生在以后添加普通目录时；取消初始化不会撤销已经完成的 Git 安装。
- 初始化后建立不修改用户分支历史和 index 的内部基线，并将目录中既有未跟踪文件纳入 diff 与回档。

## 已确认的隔离修改流程

- 允许在 dirty working tree 上运行；bug 开始时保存 `HEAD`、index、staged/unstaged 改动、未跟踪非 ignore 文件与哈希，用户原有改动不会被自动提交、stash、reset 或清理。
- 每个 bug 在专属隔离 worktree 或等价执行副本中修改和测试，真实工作区在用户接受前保持不变；隔离创建失败时不退化为原地修改。
- 接受时比较开始基线、Agent 结果与真实工作区当前状态；外部编辑触发三方冲突检查，绝不静默覆盖。
- 合并以真实工作区集成 checkpoint 保护，并在合并后重新验证；只有集成与验证成功才提升为新基线。

## 已确认的 Git 完成动作

- bug 审阅提供“接受更改”“接受并提交”“继续修改”“拒绝并丢弃”；默认只应用修改，不自动创建 commit。
- “接受并提交”由用户显式选择，message 可编辑并验证 Conventional Commits；Agent 增量无法与既有 dirty 内容可靠分离时禁用自动提交。
- 产品支持用户明确要求的 `git push`，执行前展示 remote、目标分支和 commit 列表；修复、接受或 commit 均不会自动触发 push。
- 完全访问可以免除普通 push 的逐次审批，但不能替代明确的用户 push 指令；force push、删除远程 ref、标签和非 fast-forward 更新使用独立高风险授权。
- 当前项目仓库仍严格禁止 push、远程发布、部署和创建远程 PR。
- 接受修改默认作用于当前分支，不自动创建分支；用户可显式选择“创建新分支并应用”，名称可编辑，dirty 内容无法安全分离时禁用该选项。
- MVP 不内置 GitHub PR 或 GitHub MR 创建与同步；外部 `gh`、`glab` 等工具只作为经过授权的普通 shell 命令使用。

## 已确认的验证与交付

- 六个 Harness 维度均实现可运行基础，确定性治理作为做深的主要贡献；真实 LLM 移除后，路径、权限、隔离、审批、接受和回档仍可离线验证。
- scripted/mock Provider 的机制演示必须展示危险动作被拦截、失败反馈改变下一 action，以及 dirty 工作区隔离与冲突拒绝接受。
- Python 单元测试、临时 Git 仓库集成测试、Vitest、Playwright Electron、凭据 canary、secret scan 和干净安装测试组成发布门禁。
- 故障注入覆盖非法 action、迟到响应、Provider/工具重试上限、副作用结果未知、checkpoint/压缩失败、路径穿越、并发冲突和崩溃恢复。
- `GitHub Actions` 必须包含名称完全为 `offline-check` 的离线 job；GitHub Actions 负责公开仓库检查、Release 产物、Pages 落地页和 fixture-only `/demo/` 的安全/E2E 检查。
- GitHub 是公开开发与 Release 主仓库，GitHub 是Release evidence；当前禁止任何 push、远程 PR、Release、Pages 和 Bilibili 发布，后续必须另行授权。
