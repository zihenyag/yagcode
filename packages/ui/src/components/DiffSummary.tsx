import React from "react";

export interface DiffSummaryProps {
  filesChanged: number;
  additions: number;
  deletions: number;
}

export function DiffSummary({ filesChanged, additions, deletions }: DiffSummaryProps) {
  return (
    <div className="yg-diff-summary" role="group" aria-label="Diff 摘要">
      <span className="yg-diff-summary__metric yg-diff-summary__metric--files">{filesChanged} 个文件</span>
      <span className="yg-diff-summary__metric yg-diff-summary__metric--add">+{additions} 新增</span>
      <span className="yg-diff-summary__metric yg-diff-summary__metric--delete">-{deletions} 删除</span>
    </div>
  );
}
