import { Clapperboard, ListChecks, Network, UsersRound } from "lucide-react";
import { useState } from "react";
import type { ScriptPlan } from "../types";

type ScriptPlanTab = "characters" | "scenes" | "notes";

interface ScriptPlanPanelProps {
  plan: ScriptPlan;
  stale: boolean;
}

function formatGeneratedAt(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ScriptPlanPanel({ plan, stale }: ScriptPlanPanelProps) {
  const [activeTab, setActiveTab] = useState<ScriptPlanTab>("characters");

  return (
    <section className="script-plan-panel" aria-label="AI 剧本策划结果">
      <header className="script-plan-heading">
        <div>
          <h2>AI 剧本策划</h2>
          <p>{plan.model} · 生成于 {formatGeneratedAt(plan.updatedAt)}</p>
        </div>
        {stale ? <span className="analysis-stale">原文已更新，需要重新生成</span> : null}
      </header>

      <div className="script-plan-overview">
        <div>
          <span>故事定位</span>
          <h3>{plan.format}</h3>
          <p>{plan.logline}</p>
        </div>
        <div>
          <span>核心冲突</span>
          <p>{plan.coreConflict}</p>
        </div>
      </div>

      <div className="analysis-tabs script-plan-tabs" role="tablist" aria-label="剧本策划分类">
        <button
          className={activeTab === "characters" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "characters"}
          onClick={() => setActiveTab("characters")}
        >
          <UsersRound size={16} /> 人物与关系 {plan.characters.length}
        </button>
        <button
          className={activeTab === "scenes" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "scenes"}
          onClick={() => setActiveTab("scenes")}
        >
          <Clapperboard size={16} /> 场次拆解 {plan.scenes.length}
        </button>
        <button
          className={activeTab === "notes" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "notes"}
          onClick={() => setActiveTab("notes")}
        >
          <ListChecks size={16} /> 改编建议 {plan.adaptationNotes.length}
        </button>
      </div>

      {activeTab === "characters" ? (
        <div className="script-character-section">
          <div className="script-character-list">
            {plan.characters.map((character) => (
              <article className="script-character-row" key={character.name}>
                <div><strong>{character.name}</strong><span>{character.identity}</span></div>
                <p><b>目标</b>{character.goal}</p>
                <p><b>阻力</b>{character.obstacle}</p>
                <p><b>变化</b>{character.arc}</p>
              </article>
            ))}
          </div>
          <div className="relationship-list">
            <h3><Network size={16} /> 人物关系</h3>
            {plan.relationships.map((relationship, index) => (
              <article className="relationship-row" key={`${relationship.fromCharacter}-${relationship.toCharacter}-${index}`}>
                <div>
                  <strong>{relationship.fromCharacter}</strong>
                  <span>→</span>
                  <strong>{relationship.toCharacter}</strong>
                  <em>{relationship.publicRelation}</em>
                </div>
                <p>{relationship.trueAttitude}</p>
                <small>{relationship.tension}</small>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {activeTab === "scenes" ? (
        <div className="script-scene-list">
          {plan.scenes.map((scene) => (
            <article className="script-scene" key={scene.index}>
              <div className="script-scene-number">{String(scene.index).padStart(2, "0")}</div>
              <div>
                <div className="script-scene-title">
                  <h3>{scene.heading}</h3>
                  <span>{scene.chapter} · {scene.characters.join("、")}</span>
                </div>
                <dl>
                  <div><dt>目标</dt><dd>{scene.objective}</dd></div>
                  <div><dt>冲突</dt><dd>{scene.conflict}</dd></div>
                  <div><dt>转折</dt><dd>{scene.turn}</dd></div>
                  <div><dt>结果</dt><dd>{scene.outcome}</dd></div>
                </dl>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {activeTab === "notes" ? (
        <ol className="adaptation-note-list">
          {plan.adaptationNotes.map((note, index) => <li key={`${index}-${note}`}>{note}</li>)}
        </ol>
      ) : null}
    </section>
  );
}
