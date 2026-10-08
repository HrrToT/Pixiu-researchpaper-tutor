import React, { useState } from 'react';

export default function TaskRename({ task, onRename }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(task.title || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async event => {
    event.preventDefault();
    if (busy || !title.trim()) return;
    setBusy(true); setError('');
    try { await onRename(title.trim()); setOpen(false); }
    catch (failure) { setError(failure.response?.data?.message || failure.message || '名称保存失败，请重试'); }
    finally { setBusy(false); }
  };
  return <>
    <button type="button" className="unified-header-action" onClick={() => { setTitle(task.title || ''); setError(''); setOpen(true); }}>重命名</button>
    {open && <div className="task-draft-backdrop"><section role="dialog" aria-modal="true" aria-label="重命名任务" className="task-draft-dialog theme-panel"
      onKeyDown={event => { if (event.key === 'Escape' && !busy) setOpen(false); }}>
      <form onSubmit={submit}>
        <h2>任务名称</h2>
        <input autoFocus aria-label="任务名称" value={title} maxLength={500} disabled={busy} onChange={event => setTitle(event.target.value)} className="theme-input unified-rename-input" />
        {error && <p role="alert">{error}</p>}
        <div className="unified-document-toolbar">
          <button type="submit" disabled={busy || !title.trim()}>{busy ? '保存中…' : '保存名称'}</button>
          <button type="button" disabled={busy} onClick={() => setOpen(false)}>取消</button>
        </div>
      </form>
    </section></div>}
  </>;
}
