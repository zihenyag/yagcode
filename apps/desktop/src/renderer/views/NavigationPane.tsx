import React from "react";
import { StatusBadge } from "@yagcode/ui/desktop";
import type { NavigationModel } from "../api/adapters.js";

function runStateLabel(state: string): string {
  const labels: Record<string, string> = {
    IDLE: "空闲",
    RUNNING: "运行中",
    COMPACTING: "压缩中",
    WAITING_PERMISSION: "等待权限",
    WAITING_PRIVACY: "等待隐私确认",
    STOPPING: "停止中",
    INTERRUPTED: "已中断",
    FINISHED: "已完成",
    FAILED: "失败",
  };
  return labels[state] ?? state;
}

export function NavigationPane({ model }: { model: NavigationModel }) {
  return (
    <aside className="workbench-pane workbench-pane--navigation" aria-label="档案、项目与线程">
      <div className="sidebar-chrome" aria-label="窗口导航">
        <span className="traffic-spacer" aria-hidden="true" />
        <button aria-label="收起侧边栏" className="chrome-button" type="button">⌘</button>
        <button aria-label="撤回" className="chrome-button" type="button">←</button>
        <button aria-label="推进" className="chrome-button" type="button">→</button>
      </div>

      <header className="brand-row">
        <div>
          <p className="pane-kicker">YagCode</p>
          <h1>本地 Agent 工作台</h1>
        </div>
        <button aria-label="搜索" className="search-button" type="button">⌕</button>
      </header>

      <div className="sidebar-status">
        <StatusBadge tone={model.runState === "RUNNING" ? "info" : "neutral"} label={runStateLabel(model.runState)} />
      </div>

      <section className="nav-section" aria-labelledby="profiles-heading">
        <h2 id="profiles-heading">Project</h2>
        <ul className="nav-list">
          {model.projects.map((project) => (
            <li key={project.id}>
              <button className={project.active ? "nav-item nav-item--active" : "nav-item"} type="button">
                {project.label}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="nav-section" aria-labelledby="threads-heading">
        <h2 id="threads-heading">Threads</h2>
        <ul className="nav-list">
          {model.threads.map((thread) => (
            <li key={thread.id}>
              <button className="nav-item nav-item--thread" type="button">
                <span>{thread.label}</span>
                <span className="nav-item__meta">
                  {thread.unreadApprovals} 批准 · {thread.memorySuggestions} 记忆建议
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <div className="profile-dock">
        <button className="profile-button" type="button">
          <span className="profile-avatar">AG</span>
          <span>
            <strong>{model.profiles[0]?.label ?? "默认档案"}</strong>
            <small>记忆 · 隐私 · 权限 · 审查 · 设置</small>
          </span>
        </button>
      </div>
    </aside>
  );
}
