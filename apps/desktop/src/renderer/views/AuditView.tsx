import React from "react";
import type { AuditModel } from "../api/adapters.js";

export function AuditView({ model }: { model: AuditModel }) {
  return (
    <section className="review-section" aria-labelledby="audit-heading">
      <h3 id="audit-heading">审计</h3>
      <ol className="audit-list">
        {model.entries.map((entry) => (
          <li key={entry.id}>
            <time dateTime={entry.at}>{entry.at}</time>
            <strong>{entry.title}</strong>
            <span>{entry.detail}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
