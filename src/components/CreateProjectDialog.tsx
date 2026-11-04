import { useState } from "react";
import { X } from "lucide-react";

interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (input: { name: string; description: string }) => Promise<unknown>;
}

export function CreateProjectDialog({ open, onClose, onCreate }: CreateProjectDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  if (!open) return null;

  const close = () => {
    setSubmitError(null);
    onClose();
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await onCreate({ name, description });
      setName("");
      setDescription("");
      onClose();
    } catch (error: unknown) {
      setSubmitError(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={close}>
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-project-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-header">
          <div>
            <p className="section-label">新建工作区</p>
            <h2 id="create-project-title">创建视频项目</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭" onClick={close}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={submit}>
          <label>
            项目名称
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：品牌故事短片"
            />
          </label>
          <label>
            项目说明
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="简要描述视频主题和目标"
              rows={3}
            />
          </label>
          {submitError ? <p className="form-error">{submitError}</p> : null}
          <div className="dialog-actions">
            <button className="button secondary" type="button" onClick={close} disabled={submitting}>
              取消
            </button>
            <button className="button primary" type="submit" disabled={!name.trim() || submitting}>
              {submitting ? "正在创建…" : "创建项目"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
