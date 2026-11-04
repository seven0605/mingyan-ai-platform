import { ArrowLeft, Wrench } from "lucide-react";

interface PlaceholderPageProps {
  title: string;
  onBack: () => void;
}

export function PlaceholderPage({ title, onBack }: PlaceholderPageProps) {
  return (
    <main className="placeholder-page">
      <div className="placeholder-icon">
        <Wrench size={28} strokeWidth={1.5} />
      </div>
      <h1>{title}</h1>
      <p>该模块已纳入产品架构，将在后续里程碑中逐步实现。</p>
      <button className="button secondary" type="button" onClick={onBack}>
        <ArrowLeft size={17} />
        返回创作空间
      </button>
    </main>
  );
}
