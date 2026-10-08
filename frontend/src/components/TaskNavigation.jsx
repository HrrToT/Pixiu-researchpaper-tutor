import React, { useState } from 'react';
import { Plus, ChevronLeft, ChevronRight, FileText, NotebookPen, X } from 'lucide-react';

export default function TaskNavigation({ tasks, activeTask, papers, collapsed, onToggle,
  onSelectTask, onCreateTask, onOpenPaper, onAddPaper, onRemovePaper, onOpenArtifact, children }) {
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const perform = async (action) => {
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(failure.message || '操作失败，请重试'); }
    finally { setBusy(false); }
  };
  return <aside className={`theme-panel theme-border flex shrink-0 flex-col border-r ${collapsed ? 'w-12' : 'w-64'}`} aria-label="任务导航">
    <div className="flex items-center gap-2 p-2">
      {!collapsed && <select aria-label="当前任务" value={activeTask?.id || ''} onChange={(event) => onSelectTask(event.target.value)} className="theme-input min-w-0 flex-1 rounded p-2 text-sm">
        {!activeTask && <option value="">选择任务</option>}
        {tasks.map((task) => <option key={task.id} value={task.id}>{task.title || '未命名任务'}</option>)}
      </select>}
      <button type="button" onClick={onToggle} className="pixiu-icon-action" aria-label={collapsed ? '展开导航' : '收起导航'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button>
    </div>
    <button type="button" disabled={busy} onClick={() => perform(() => onCreateTask())} className="theme-text-primary m-2 flex items-center gap-2 rounded p-2 text-sm" aria-label="新任务"><Plus size={16} />{!collapsed && '新任务'}</button>
    {!collapsed && <div className="flex-1 overflow-y-auto p-3">
      {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
      <div className="mb-2 flex items-center justify-between"><h2 className="theme-text-secondary text-sm">论文与材料</h2><button type="button" disabled={!activeTask} onClick={() => setAdding(!adding)} aria-label="添加已有论文"><Plus size={16} /></button></div>
      {(activeTask?.paperIds || []).map((id) => {
        const paper = papers.find((item) => item.id === id);
        return <div key={id} className="group flex items-center gap-1">
          <button type="button" aria-current={activeTask.focusedPaperId === id ? 'page' : undefined} onClick={() => onOpenPaper(id)} className="theme-text-primary flex min-w-0 flex-1 items-center gap-2 rounded py-2 text-left text-sm"><FileText size={15} className="shrink-0" /><span className="truncate">{paper?.title || paper?.filename || id}</span></button>
          <button type="button" disabled={busy} aria-label={`移出任务：${paper?.title || paper?.filename || id}`} title="仅移出当前任务，保留论文文件" onClick={() => perform(() => onRemovePaper(id))} className="theme-text-muted p-1"><X size={13} /></button>
        </div>;
      })}
      {adding && <div className="theme-border my-2 rounded border p-2">
        {papers.filter((paper) => !activeTask?.paperIds.includes(paper.id)).map((paper) => <button type="button" disabled={busy} key={paper.id} onClick={() => perform(() => onAddPaper(paper.id))} className="theme-text-primary block w-full truncate py-2 text-left text-sm">{paper.title || paper.filename}</button>)}
        {!papers.some((paper) => !activeTask?.paperIds.includes(paper.id)) && <p className="theme-text-muted text-xs">暂无其他论文，可上传新论文。</p>}
      </div>}
      {children}
      <h2 className="theme-text-secondary mb-2 mt-5 text-sm">笔记与成果</h2>
      {[...(activeTask?.notes || []), ...(activeTask?.artifacts || [])].map((item, index) => <button type="button" key={item.id || item.artifactId || index} onClick={() => onOpenArtifact(item)} className="theme-text-primary flex w-full items-center gap-2 py-2 text-left text-sm"><NotebookPen size={15} className="shrink-0" /><span className="truncate">{item.title || item.text?.slice(0, 30) || '笔记'}</span></button>)}
    </div>}
  </aside>;
}
