# YagCode Desktop Visual Design Contract

本文件是本轮内置 design tool skill 产出的视觉系统入口。它取代旧 design tool HTML 原型里的布局细节，但不删除历史记录；历史 design tool 接收记录仍保留在 [`OPEN_DESIGN.md`](OPEN_DESIGN.md)。

## 1. Visual Theme & Atmosphere

YagCode Desktop 是本地 Coding Agent 工作台，不是营销后台，也不是大号聊天网页。视觉基调采用 local-engineering 的本地工程工具感：克制、紧凑、低装饰、响应明确、信息密度高。用户应该一眼看出三个问题：当前在哪个项目/线程、Agent 是否在运行、候选代码改了什么。

借鉴 desktop agent 的原则仅限于工程气质、密度、层级和桌面应用感；禁止复制 third-party product 的品牌、商标、图标、专有组件、精确布局或精确配色。

## 2. Color

默认支持 `system` / `light` / `dark` 三档主题。light 是当前主要验收面，必须像系统原生工具一样干净，不能残留深色卡片或高饱和 AI 渐变。

- Light：背景使用 warm off-white / neutral gray，左栏和右栏略低一阶，中间任务区更明亮；边框比阴影更重要。
- Dark：使用 graphite / slate，不使用纯黑；状态色保持低饱和。
- Accent：主操作使用一枚克制蓝色；新增/通过用绿色；删除/危险用红色；等待/权限用琥珀。
- Diff：绿色新增、红色删除、蓝灰 hunk；必须同时使用 `+` / `-` / 文件状态文字，不能只靠颜色。
- 禁止：紫蓝渐变、玻璃拟态、大面积发光、彩色装饰 blob、把状态色当背景涂满。

## 3. Typography

中文 UI 默认系统字体，优先保证 macOS/Windows 字体一致的高度和字重。界面文本紧凑但不能挤压。

- 导航、按钮、状态 badge：11-13px，600 左右字重。
- 正文对话：14px，1.5-1.6 行高。
- 代码、路径、diff、hash、命令：等宽字体，启用稳定数字宽度。
- 项目和线程标题允许单行截断；diff 路径应中间截断，保留文件名。

## 4. Spacing & Grid

使用 4px/8px 网格，整体偏 compact。三栏之间用 1px 边框分隔，不靠厚重阴影制造层级。

- 左栏宽度建议 260-300px，可折叠。
- 中间任务区最小 560px，内容最大宽度 820-900px。
- 右侧 Changes/Diff 默认 360-460px，可在桌面端扩展；窄宽度下文件树和 diff preview 纵向堆叠。
- 列表行高 30-36px；活跃线程用浅底色和左侧细 accent 标记。
- 悬浮窗最小宽度 360px，设置类窗口可到 640px。

## 5. Layout & Composition

固定三栏，但职责重新收敛：

1. 左侧：全局导航、项目树、线程树、搜索、新建项目、新建线程、底部 AGENT/档案入口。
2. 中间：当前线程对话、运行状态、输入框、Plan mode、模型选择、附件入口、停止/发送并运行。
3. 右侧：只展示 Changes/Diff。不要在右侧塞审阅、记忆、权限、隐私、切换、设置。

左侧项目/线程采用用户参考图的树状密度：`Projects` 标题下按项目分组，项目行带文件夹图标，线程行缩进展示，当前线程浅底高亮。项目标题附近提供创建新项目入口；项目 hover 或项目行右侧提供创建新线程入口。空状态也必须允许直接创建项目/线程，而不是只显示说明文字。

右侧 Diff 采用用户参考图的审查结构：顶部显示 Changes 摘要和 `+/-` 计数，下面提供文件过滤框、文件树和选中文件 diff。大 diff 时提示“只显示一个文件”，并让用户切换文件。右侧不承载全局设置。

左下 AGENT/档案按钮点击后向上展开悬浮菜单：切换、创建，分隔，记忆、隐私、权限、审阅，分隔，设置。上述二级内容统一打开悬浮窗或 modal sheet，不再挤占右栏。

## 6. Components

核心组件按产品职责拆分：

- `ProjectThreadTree`：项目分组、线程缩进、当前线程高亮、新建项目、新建线程、搜索过滤、空状态。
- `AgentDock`：底部档案按钮、向上悬浮菜单、运行时禁切提示。
- `FloatingPanel`：设置、记忆、隐私、权限、审阅、切换/创建 Agent 的统一容器。
- `TaskConversation`：local-engineering 对话流，保留用户/Agent/System 三类消息。
- `Composer`：自动伸缩文本框，附件入口，Plan mode，模型选择，停止和发送并运行。
- `ChangesPanel`：右侧唯一主内容，包含 diff summary、filter、file tree、selected file diff、large diff notice、rollback checkpoint shortcut。
- `DiffLine`：行号、前缀、代码、add/delete/hunk/normal 状态；必须支持键盘复制和横向滚动。
- `StatusBadge` / `EvidenceList` / `DangerPanel` / `DiffSummary` 继续作为共享 UI 原语，但视觉要服从本合同。

所有可点击项必须有 hover、active、focus-visible、disabled 状态。运行中禁止切换模型、项目、线程和关闭窗口，但允许追加信息。

## 7. Motion & Interaction

动效只服务可理解的状态变化：

- 左下菜单向上弹出：opacity + translateY，小于 140ms。
- 悬浮窗打开：轻量 fade/scale，不做弹性动画。
- 项目树展开/收起：高度或 opacity 过渡必须可被 reduced-motion 禁用。
- 运行状态变化：状态条、按钮 disabled、模型锁定要同步变化。
- Diff 切换：文件选中后 diff 内容快速替换，不做大面积转场。

在 `prefers-reduced-motion: reduce` 下关闭非必要动画。

## 8. Voice & Brand

默认中文简体，支持中文繁体、English(US)、English(UK)。文案必须解释动作后果和恢复方式。

- 主按钮：空闲/READY/失败/停止时为“发送并运行”；运行中为“发送”或“追加信息”。
- 线程标题只作为 UI 元数据，不发送给模型。
- API key 绑定必须写明“不回显、不进日志、不进 prompt”。
- 权限文案使用规范三档：`仅允许本次操作`、`始终允许相似操作（当前应用会话）`、`完全访问模式（当前应用会话）`。
- 危险、隐私、回滚、删除 API、删除记忆都要说明副作用范围。

YagCode 标识只做轻量产品身份，不使用大型 logo、营销口号或拟人化装饰。

## 9. Anti-patterns

- 禁止右栏继续展示审阅、记忆、隐私、权限、设置、切换等全局内容。
- 禁止项目/线程只是静态列表；必须能创建新项目和新线程。
- 禁止把 Diff 做成摘要卡片而没有红绿逐行预览、文件树和过滤。
- 禁止点击无反馈、按钮未绑定又看起来可点击。
- 禁止全屏 chat-only、SaaS dashboard 模板、厚重阴影、过圆卡片、紫蓝渐变、玻璃拟态。
- 禁止复制 third-party product 品牌、商标、专有图标、精确布局或精确配色。
- 禁止在产品 renderer 中引入 CDN React/Babel、`new Function`、inline mock-only runtime。
- 禁止 UI、日志、测试 fixture、截图中出现凭据原文。
