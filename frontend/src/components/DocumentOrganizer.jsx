import React, { useState } from 'react';

export default function DocumentOrganizer({ document, taskId, tasks, dirty, onRename, onMove }) {
  const [title, setTitle] = useState(document.title || '');
  const [target, setTarget] = useState('');
  const [includeMaterials, setIncludeMaterials] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const perform = async action => {
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(failure.response?.data?.message || failure.message || '操作未确认，请查询原请求'); }
    finally { setBusy(false); }
  };
  return <details className="theme-border rounded border p-2">
    <summary>整理成果</summary>
    <div className="flex flex-wrap items-center gap-2 py-2">
      <input aria-label="成果名称" value={title} disabled={busy} maxLength={500} onChange={event => setTitle(event.target.value)} className="theme-input rounded p-2" />
      <button type="button" disabled={busy || !title.trim()} onClick={() => perform(() => onRename(title.trim()))}>保存名称</button>
    </div>
    <label>移动到 <select aria-label="移动到任务" value={target} disabled={busy} onChange={event => setTarget(event.target.value)} className="theme-input rounded p-2">
      <option value="">选择任务</option>
      {tasks.filter(task => task.id !== taskId).map(task => <option key={task.id} value={task.id}>{task.title}</option>)}
    </select></label>
    <label className="block py-2"><input type="checkbox" checked={includeMaterials} disabled={busy} onChange={event => setIncludeMaterials(event.target.checked)} /> 同时加入来源论文，作为目标任务可用材料</label>
    {dirty && <p>请先保存正文，再移动成果。</p>}
    <div className="flex gap-3 py-2">
      <button type="button" disabled={busy || dirty || !target || !(document.id || document.artifactId)} onClick={() => perform(() => onMove(target, includeMaterials, false))}>{busy ? '处理中…' : '移动成果'}</button>
      <button type="button" disabled={busy} onClick={() => perform(() => onMove(null, false, true))}>查询原移动请求</button>
    </div>
    {error && <p role="alert">{error}</p>}
  </details>;
}
