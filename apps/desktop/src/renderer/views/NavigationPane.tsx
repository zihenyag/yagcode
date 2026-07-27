import React, { useState } from "react";
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

export function NavigationPane({
  model,
  onCommand,
}: {
  model: NavigationModel;
  onCommand(command: { type: string; payload?: unknown }): void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  function command(type: string, payload?: unknown) {
    onCommand(payload === undefined ? { type } : { type, payload });
  }
  return (
    <aside className={collapsed ? "workbench-pane workbench-pane--navigation navigation--collapsed" : "workbench-pane workbench-pane--navigation"} aria-label="档案、项目与线程">
      <div className="sidebar-chrome" aria-label="窗口导航">
        <span className="traffic-spacer" aria-hidden="true" />
        <button
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          className="chrome-button"
          onClick={() => {
            setCollapsed((value) => !value);
            command("toggle_sidebar");
          }}
          type="button"
        >
          ⌘
        </button>
        <button aria-label="撤回" className="chrome-button" onClick={() => command("history_back")} type="button">←</button>
        <button aria-label="推进" className="chrome-button" onClick={() => command("history_forward")} type="button">→</button>
      </div>

      <header className="brand-row">
        <div>
          <p className="pane-kicker">YagCode</p>
          <h1>本地 Agent 工作台</h1>
        </div>
        <button
          aria-label="搜索"
          className="search-button"
          onClick={() => {
            setSearchOpen((value) => !value);
            command("open_search");
          }}
          type="button"
        >
          ⌕
        </button>
      </header>
      {searchOpen ? (
        <label className="sidebar-search">
          <span>搜索</span>
          <input aria-label="搜索项目或线程" placeholder="项目 / 线程" />
        </label>
      ) : null}

      <div className="sidebar-status">
        <StatusBadge tone={model.runState === "RUNNING" ? "info" : "neutral"} label={runStateLabel(model.runState)} />
      </div>

      <section className="nav-section" aria-labelledby="profiles-heading">
        <h2 id="profiles-heading">Project</h2>
        {model.projects.length === 0 ? (
          <div className="sidebar-empty">还没有打开项目</div>
        ) : (
          <ul className="nav-list">
            {model.projects.map((project) => (
              <li key={project.id}>
                <button
                  className={project.active ? "nav-item nav-item--active" : "nav-item"}
                  onClick={() => command("choose_project", { project_id: project.id })}
                  type="button"
                >
                  {project.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="nav-section" aria-labelledby="threads-heading">
        <h2 id="threads-heading">Threads</h2>
        {model.threads.length === 0 ? (
          <div className="sidebar-empty">创建线程后会显示在这里</div>
        ) : (
          <ul className="nav-list">
            {model.threads.map((thread) => (
              <li key={thread.id}>
                <button className="nav-item nav-item--thread" onClick={() => command("choose_thread", { thread_id: thread.id })} type="button">
                  <span>{thread.label}</span>
                  <span className="nav-item__meta">
                    {thread.unreadApprovals} 批准 · {thread.memorySuggestions} 记忆建议
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="profile-dock">
        <button
          aria-expanded={profileOpen}
          className="profile-button"
          onClick={() => {
            setProfileOpen((value) => !value);
            command("open_profile_menu");
          }}
          type="button"
        >
          <span className="profile-avatar">{model.profiles.length === 0 ? "?" : "AG"}</span>
          <span>
            <strong>{model.profiles[0]?.label ?? "未创建 AGENT"}</strong>
            <small>记忆 · 隐私 · 权限 · 审查 · 设置</small>
          </span>
        </button>
        {profileOpen ? (
          <div className="profile-menu" role="menu">
            {["切换", "创建", "记忆", "隐私", "权限", "审查", "审计", "设置"].map((label) => (
              <button key={label} onClick={() => command("open_panel", { panel: label })} role="menuitem" type="button">
                {label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </aside>
  );
}
