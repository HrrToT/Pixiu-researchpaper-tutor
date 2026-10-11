import React, { useState } from 'react';
import { ChevronDown, Check, Plus, Search } from 'lucide-react';
import WorkbenchPopover from './WorkbenchPopover';

export default function TaskSwitcher({ tasks, activeTask, onSelect, onCreate, onRename, children }) {
  const [query, setQuery] = useState(''), [all, setAll] = useState(false);
  const [renaming, setRenaming] = useState(false), [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const filtered = tasks.filter(task => !query.trim() || (task.title || '').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const visible = query.trim() || all ? filtered : filtered.slice(0, 8);
  const perform = async (action, close) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); setRenaming(false); close(); }
    catch (failure) { setError(failure.message || '操作失败，请重试'); }
    finally { setBusy(false); }
  };
  return <WorkbenchPopover label="切换任务" align="left" className="workbench-task-switcher"
    trigger={<><span title={activeTask?.title}>{activeTask?.title || '选择任务'}</span><ChevronDown size={14} /></>}>
    {close => <>
      {renaming ? <form onSubmit={event => { event.preventDefault(); if (title.trim()) perform(() => onRename(title.trim()), close); }}>
        <label>任务名称<input autoFocus aria-label="任务名称" value={title} disabled={busy} maxLength={500} onChange={event => setTitle(event.target.value)} /></label>
        <div className="workbench-menu-actions"><button type="submit" disabled={busy || !title.trim()}>{busy ? '保存中…' : '保存名称'}</button><button type="button" disabled={busy} onClick={() => setRenaming(false)}>取消</button></div>
      </form> : <>
        <label className="workbench-task-search"><Search size={15} /><input aria-label="搜索任务" placeholder="搜索任务" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <p className="workbench-menu-caption">{query ? '匹配任务' : all ? '全部任务' : '最近任务'}</p>
        <div className="workbench-task-options">{visible.map(task => <button type="button" disabled={busy} key={task.id} title={task.title} aria-current={task.id === activeTask?.id ? 'true' : undefined} onClick={() => perform(() => onSelect(task.id), close)}>
          <span>{task.title || '未命名任务'}</span>{task.id === activeTask?.id && <Check size={14} />}
        </button>)}{!visible.length && <p className="workbench-menu-caption">没有匹配的任务</p>}</div>
        {!all && !query && filtered.length > 8 && <button type="button" onClick={() => setAll(true)}>查看全部 {filtered.length} 个任务</button>}
        <div className="workbench-menu-divider" />
        <button type="button" disabled={busy} onClick={() => perform(onCreate, close)}><Plus size={15} />新任务</button>
        {activeTask && <button type="button" disabled={busy} onClick={() => { setTitle(activeTask.title || ''); setRenaming(true); setError(''); }}>重命名</button>}
        {children}
      </>}
      {error && <p className="workbench-menu-error" role="alert">{error}</p>}
    </>}
  </WorkbenchPopover>;
}
