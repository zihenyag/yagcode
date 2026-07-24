import React from "react";
import type { MemoryModel } from "../api/adapters.js";

export function MemoryView({ model }: { model: MemoryModel }) {
  return (
    <section className="review-section" aria-labelledby="memory-heading">
      <h3 id="memory-heading">记忆</h3>
      <div className="split-list">
        <section aria-label="项目内记忆">
          <h4>项目内记忆</h4>
          <ul className="plain-list">
            {model.projectMemories.map((memory) => (
              <li key={memory.id}>
                <strong>{memory.title}</strong>
                <span>{memory.detail}</span>
                {memory.pinned ? <em>已固定</em> : null}
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="跨项目候选">
          <h4>跨项目候选</h4>
          <ul className="plain-list">
            {model.crossProjectSuggestions.map((suggestion) => (
              <li key={suggestion.id}>
                <strong>{suggestion.title}</strong>
                <span>{suggestion.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}
