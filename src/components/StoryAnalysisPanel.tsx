import { MapPin, ScrollText, Users } from "lucide-react";
import { useState } from "react";
import type { AnalysisCandidate, StoryAnalysis } from "../types";

type AnalysisTab = "characters" | "scenes" | "plot";

interface StoryAnalysisPanelProps {
  analysis: StoryAnalysis;
  stale: boolean;
}

function CandidateRows({ items }: { items: AnalysisCandidate[] }) {
  return (
    <div className="analysis-candidate-list">
      {items.map((item) => (
        <div className="analysis-candidate-row" key={item.name}>
          <strong>{item.name}</strong>
          <span>出现 {item.mentions} 次</span>
          <em>{item.chapters.map((chapter) => `第 ${chapter} 章`).join(" · ")}</em>
        </div>
      ))}
    </div>
  );
}

export function StoryAnalysisPanel({ analysis, stale }: StoryAnalysisPanelProps) {
  const [activeTab, setActiveTab] = useState<AnalysisTab>("characters");

  return (
    <section className="analysis-panel" aria-label="本地结构分析结果">
      <div className="analysis-heading">
        <div>
          <h2>结构分析</h2>
          <p>本地规则初筛 · 不会上传小说正文</p>
        </div>
        {stale ? <span className="analysis-stale">原文已更新，需要重新分析</span> : null}
      </div>

      <div className="analysis-tabs" role="tablist" aria-label="分析结果分类">
        <button
          className={activeTab === "characters" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "characters"}
          onClick={() => setActiveTab("characters")}
        >
          <Users size={16} /> 人物候选 {analysis.characters.length}
        </button>
        <button
          className={activeTab === "scenes" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "scenes"}
          onClick={() => setActiveTab("scenes")}
        >
          <MapPin size={16} /> 场景候选 {analysis.scenes.length}
        </button>
        <button
          className={activeTab === "plot" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "plot"}
          onClick={() => setActiveTab("plot")}
        >
          <ScrollText size={16} /> 剧情节点 {analysis.plotNodes.length}
        </button>
      </div>

      {activeTab === "characters" ? <CandidateRows items={analysis.characters} /> : null}
      {activeTab === "scenes" ? <CandidateRows items={analysis.scenes} /> : null}
      {activeTab === "plot" ? (
        <div className="plot-node-list">
          {analysis.plotNodes.map((node) => (
            <article className="plot-node" key={`${node.index}-${node.title}`}>
              <div className="plot-node-index">{String(node.index).padStart(2, "0")}</div>
              <div>
                <div className="plot-node-title">
                  <h3>{node.title}</h3>
                  <span>{node.charCount.toLocaleString("zh-CN")} 字符</span>
                </div>
                <p><strong>开场锚点</strong>{node.opening}</p>
                <p><strong>结尾锚点</strong>{node.closing}</p>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
