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
  const [searchTerm, setSearchTerm] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProjectPath, setNewProjectPath] = useState("");
  const [newThreadProjectId, setNewThreadProjectId] = useState<string | null>(null);
  const [newThreadTitle, setNewThreadTitle] = useState("");
  function command(type: string, payload?: unknown) {
    onCommand(payload === undefined ? { type } : { type, payload });
  }
  function openFloatingPanel(panel: string) {
    setProfileOpen(false);
    command("open_panel", { panel });
  }
  const activeProject = model.projects.find((project) => project.active) ?? model.projects[0];
  const normalizedSearch = searchTerm.trim().toLowerCase();
  const visibleProjects = normalizedSearch.length === 0
    ? model.projects
    : model.projects.filter((project) => {
        const projectMatches = project.label.toLowerCase().includes(normalizedSearch);
        const threadMatches = project.active && model.threads.some((thread) => thread.label.toLowerCase().includes(normalizedSearch));
        return projectMatches || threadMatches;
      });
  const visibleThreads = normalizedSearch.length === 0
    ? model.threads
    : model.threads.filter((thread) => thread.label.toLowerCase().includes(normalizedSearch));
  return (
    <aside className={collapsed ? "workbench-pane workbench-pane--navigation navigation--collapsed" : "workbench-pane workbench-pane--navigation"} aria-label="档案、项目与线程">
      <div className="sidebar-chrome" aria-label="窗口导航">
        <span className="traffic-spacer" aria-hidden="true" />
        <button
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          className="chrome-button"
          onClick={() => {
            setCollapsed((value) => !value);
          }}
          type="button"
        >
          ⌘
        </button>
        <button aria-label="撤回" className="chrome-button" type="button">←</button>
        <button aria-label="推进" className="chrome-button" type="button">→</button>
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
          }}
          type="button"
        >
          ⌕
        </button>
      </header>
      {searchOpen ? (
        <label className="sidebar-search">
          <span>搜索</span>
          <input aria-label="搜索项目或线程" onChange={(event) => setSearchTerm(event.currentTarget.value)} placeholder="项目 / 线程" value={searchTerm} />
        </label>
      ) : null}

      <div className="sidebar-status">
        <StatusBadge tone={model.runState === "RUNNING" ? "info" : "neutral"} label={runStateLabel(model.runState)} />
      </div>

      <section className="nav-section project-tree-section" aria-labelledby="projects-heading">
        <div className="nav-section__header">
          <h2 id="projects-heading">Projects</h2>
          <button className="mini-button" onClick={() => setNewProjectOpen((value) => !value)} type="button">
            + 新项目
          </button>
        </div>
        {newProjectOpen ? (
          <div className="inline-create inline-create--project">
            <input aria-label="新项目路径" onChange={(event) => setNewProjectPath(event.currentTarget.value)} placeholder="/path/to/project" value={newProjectPath} />
            <button
              className="mini-button"
              onClick={() => {
                command("open_folder", { path: newProjectPath });
                setNewProjectPath("");
                setNewProjectOpen(false);
              }}
              type="button"
            >
              打开
            </button>
          </div>
        ) : null}
        {visibleProjects.length === 0 ? (
          <div className="sidebar-empty">还没有打开项目。点击“+ 新项目”开始。</div>
        ) : (
          <ul className="project-tree">
            {visibleProjects.map((project) => {
              const projectThreads = project.id === activeProject?.id ? visibleThreads : [];
              return (
                <li className="project-node" key={project.id}>
                  <div className={project.active ? "project-row project-row--active" : "project-row"}>
                    <button
                      aria-label={`打开项目 ${project.label}`}
                      className="project-row__main"
                      onClick={() => command("choose_project", { project_id: project.id })}
                      type="button"
                    >
                      <span aria-hidden="true">▿</span>
                      <span>{project.label}</span>
                    </button>
                    <button
                      aria-label={`在 ${project.label} 下新建线程`}
                      className="project-row__add"
                      onClick={() => setNewThreadProjectId((value) => (value === project.id ? null : project.id))}
                      type="button"
                    >
                      +
                    </button>
                  </div>
                  {newThreadProjectId === project.id ? (
                    <div className="inline-create inline-create--thread">
                      <input aria-label={`新线程标题：${project.label}`} onChange={(event) => setNewThreadTitle(event.currentTarget.value)} placeholder="新线程标题" value={newThreadTitle} />
                      <button
                        className="mini-button"
                        onClick={() => {
                          command("create_thread", { title: newThreadTitle });
                          setNewThreadTitle("");
                          setNewThreadProjectId(null);
                        }}
                        type="button"
                      >
                        创建
                      </button>
                    </div>
                  ) : null}
                  {projectThreads.length > 0 ? (
                    <ul className="thread-tree">
                      {projectThreads.map((thread) => (
                        <li key={thread.id}>
                          <button className="thread-row" onClick={() => command("choose_thread", { thread_id: thread.id })} type="button">
                            <span>{thread.label}</span>
                            <small>
                              {thread.unreadApprovals} 批准 · {thread.memorySuggestions} 记忆建议
                            </small>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : project.active ? (
                    <div className="sidebar-empty sidebar-empty--thread">点击项目右侧 + 创建线程</div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="profile-dock">
        <button
          aria-expanded={profileOpen}
          className="profile-button"
          onClick={() => {
            setProfileOpen((value) => !value);
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
            <button onClick={() => openFloatingPanel("切换")} role="menuitem" type="button">切换 AGENT</button>
            <button onClick={() => openFloatingPanel("创建")} role="menuitem" type="button">创建 AGENT</button>
            <hr />
            {["记忆", "隐私", "权限", "审阅", "审计"].map((label) => (
              <button key={label} onClick={() => openFloatingPanel(label)} role="menuitem" type="button">
                {label}
              </button>
            ))}
            <hr />
            <button onClick={() => openFloatingPanel("设置")} role="menuitem" type="button">设置</button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
