# DESIGN.md

本文件是 design tool / design tool 习惯入口。项目内规范性记录以 [`OPEN_DESIGN.md`](OPEN_DESIGN.md) 为准；design tool 导出的原型副本保存在 [`open-design/yagcode-desktop-workbench.html`](open-design/yagcode-desktop-workbench.html)。

## 1. Visual Theme & Atmosphere

证据优先的本地工程工作台。界面严肃、紧凑、中文优先，像 coding agent 控制台而不是营销后台或全屏聊天。

## 2. Color

沿用 graphite/slate 深色工程基调，蓝色作为主操作/焦点，绿色表示验证通过，琥珀表示等待/审批，红色表示危险。diff 和风险必须同时用文字/符号/图标表达，不能只靠颜色。

## 3. Typography

中文 UI 使用系统字体；代码、命令、日志、路径、hash、diff 使用等宽字体并启用稳定数字宽度。

## 4. Spacing & Grid

默认 compact，使用 4/8px 网格。列表和日志保持高密度，审批、隐私和危险确认保留更大的点击与阅读空间。

## 5. Layout & Composition

固定三栏：左侧档案/项目/线程/运行锁，中间任务对话、结构化表单、Plan 和输入，右侧 diff、验证、审批、隐私、记忆、审计和回滚证据栈。

## 6. Components

第一批组件为 `StatusBadge`、`EvidenceList`、`DangerPanel`、`DiffSummary`。design tool 单文件里的视觉片段只能作为参考，最终必须拆成可测试 React/TypeScript 组件。

## 7. Motion & Interaction

动效只服务状态变化。运行中禁止切换模型/项目/线程/关闭，允许追加信息；停止或中断后才能切换模型。

## 8. Voice & Brand

中文文案要明确动作、范围、证据和恢复方式。危险权限按钮必须使用完整文案，不得使用模糊的“允许”。

## 9. Anti-patterns

禁止 CDN/Babel runtime 原型进入产品；禁止全屏 chat-only；禁止隐藏 diff/验证/审批；禁止紫蓝 AI 渐变和玻璃拟态作为主风格；禁止在 UI、日志、截图或 fixture 中显示凭据原文。
