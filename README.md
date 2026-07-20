# yagcode

YagCode 期末项目：Coding Agent Harness。


- [Brainstorming 过程与用户决策](design notes)
- [初始化候选规划（历史材料）](PROJECT_PLANNING.md)
- [项目与项目要求](YagCode_product brief_A_Coding_Agent_Harness.md)
- [Agent 协作记录](agent log)


## 已确认的运行形态

- 本地产品由 Python 3.12、FastAPI、SQLite 和系统 keyring 构成，Harness 内核自行实现。
- React + TypeScript + Vite 前端构建后打包进 Python 发行物，由绑定 `127.0.0.1` 的本地服务提供，不需要单独部署真实产品前端。
- 用户从目标 Git 仓库启动程序；本地后端锁定工作区并负责文件、测试、checkpoint 和审计，浏览器只负责展示与审批。
- 同一前端源码另行构建公网 mock 演示，只运行内置 fixture，不访问访客文件或执行任意代码。
- 默认验证策略可由用户覆盖，标准级要求复现原问题、目标与相关测试通过、静态检查通过且 diff 合规。
- 目标仓库按语言无关方式处理；测试、lint、类型检查和构建命令由项目配置声明并进入 allowlist。

## 已确认的模型支持

- OpenAI 为默认主要 Provider，另行官方支持 Qwen、GLM 和 DeepSeek；不支持 Anthropic。
- Harness 每轮只向 Provider 请求一个结构化候选 action，工具执行、反馈、记忆和停机均由本项目代码控制。
- 用户可在同一个 bug 中随时切换 Provider 或模型；切换前自动建立 checkpoint，并按 action 记录实际使用的 Provider、模型和用量。
- scripted/mock Provider 用于离线确定性测试和公网演示。

## 已确认的权限与隐私模型

- 危险操作提供“仅允许本次操作”“始终允许符合此规则的操作”“为当前应用会话启用完全访问模式”三个选择；规则匹配由确定性策略引擎完成。
- 完全访问模式持续到本地应用或服务退出、崩溃或重启，用户可随时提前撤销；它不关闭审计、凭据隔离或数据外发治理。
- 工作区外访问可按外部根目录授予只读或读写权限。Agent 只能使用命名凭据，不能读取、显示或记录明文。
- 隐私数据首次外发前必须预览；确认后形成跨会话、跨 Provider 的持久授权，直到用户撤销或数据范围、隐私类别发生实质变化。
- API key、密码、Token 与私钥永不发送给模型，不能被普通审批或完全访问模式放行。
