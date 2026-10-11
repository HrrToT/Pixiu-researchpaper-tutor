import React, { useRef, useState } from 'react';
import { Plus, ChevronLeft, ChevronRight, FileText, NotebookPen, Search, SlidersHorizontal } from 'lucide-react';
import { taskDocumentNavigation } from '../utils/taskDocumentNavigation';
import { documentKind, paperShortName } from '../utils/documentPresentation';
import WorkbenchPopover from './WorkbenchPopover';
import LearningHistory, { learningSearchText } from './LearningHistory';
import './TaskNavigationDetails.css';

export default function TaskNavigation({ tasks, activeTask, papers, collapsed, onToggle,
  onSelectTask, onCreateTask, onOpenPaper, onAddPaper, onRemovePaper, onOpenArtifact, onCreateNote,
  onUpload, uploading = false, onCancelUpload, taskControlsInHeader = false, learningRecords = [], onOpenLearning, selectedDocumentId, selectedLearningId, children }) {
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState('');
  const [type, setType] = useState('all');
  const [papersOpen, setPapersOpen] = useState(true);
  const [removedPaper, setRemovedPaper] = useState(null);
  const operationEpoch = useRef(0), busyRef = useRef(false);
  React.useEffect(() => { operationEpoch.current += 1; busyRef.current = false; setBusy(false); setError(''); setQuery(''); setType('all'); setAdding(false); setRemovedPaper(null); }, [activeTask?.id]);
  const matches = value => !query.trim() || `${value || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const kindOf = item => documentKind(item, activeTask);
  const typeLabels = { note: '笔记', research: '报告', compare: '比较', translation: '译文', critique: '批判', background: '补课', compose: '组合', artifact: '成果' };
  const documents = taskDocumentNavigation(activeTask, papers).filter(({ item, title }) => matches([
    title, item.title, item.text, item.content, item.summary, item.aiInterpretation, item.source?.text,
  ].filter(Boolean).join(' ')) && (type === 'all' || kindOf(item) === type));
  const paperIds = (activeTask?.paperIds || []).filter(id => {
    const paper = papers.find(item => item.id === id);
    return matches(`${paper?.title || ''} ${paper?.filename || ''} ${id}`);
  });
  const matchingLearning = learningRecords.filter(activity => matches(learningSearchText(activity, papers)));
  const noSearchResults = query.trim() && !paperIds.length && !documents.length && !matchingLearning.length;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const perform = async (action) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const epoch = ++operationEpoch.current;
    const isCurrent = () => epoch === operationEpoch.current;
    setBusy(true); setError('');
    try { await action(isCurrent); } catch (failure) { if (isCurrent()) setError(failure.message || '操作失败，请重试'); }
    finally { if (isCurrent()) { busyRef.current = false; setBusy(false); } }
  };
  return <aside className={`workbench-navigation theme-panel theme-border ${collapsed ? 'is-collapsed' : ''}`} aria-label="任务导航">
    <div className="workbench-navigation-head">
      {!collapsed && !taskControlsInHeader && <select aria-label="当前任务" value={activeTask?.id || ''} onChange={(event) => onSelectTask(event.target.value)} className="theme-input min-w-0 flex-1 rounded p-2 text-sm">
        {!activeTask && <option value="">选择任务</option>}
        {tasks.map((task) => <option key={task.id} value={task.id}>{task.title || '未命名任务'}</option>)}
      </select>}
      {!collapsed && taskControlsInHeader && <span className="workbench-navigation-caption">任务内容</span>}
      <button type="button" onClick={onToggle} className="pixiu-icon-action" aria-label={collapsed ? '展开导航' : '收起导航'}>{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button>
    </div>
    {!taskControlsInHeader && <button type="button" disabled={busy} onClick={() => perform(() => onCreateTask())} className="theme-text-primary m-2 flex items-center gap-2 rounded p-2 text-sm" aria-label="新任务"><Plus size={16} />{!collapsed && '新任务'}</button>}
    {!collapsed && <>
      <div className="workbench-navigation-search"><Search size={15} /><input className="unified-nav-search" aria-label="搜索材料与记录" placeholder="搜索本任务" value={query} onChange={event => setQuery(event.target.value)} /></div>
      {uploading && <div className="workbench-upload-state" role="status"><span>正在上传…</span>{onCancelUpload && <button type="button" onClick={onCancelUpload}>取消上传</button>}</div>}
      {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
      <div className={`workbench-navigation-lists ${!papersOpen && !query ? 'papers-collapsed' : ''}`}>
      <section className="workbench-navigation-papers" aria-label="论文与材料列表">
      <div className="workbench-section-head"><button type="button" className="workbench-section-toggle" aria-expanded={papersOpen || Boolean(query)} onClick={() => setPapersOpen(value => !value)}><ChevronRight size={13} className={papersOpen || query ? 'expanded' : ''} />论文与材料 <span>{activeTask?.paperIds.length || 0}</span></button>
        {onUpload ? <WorkbenchPopover label="添加论文" trigger={<Plus size={16} />}>
          {close => <><button type="button" disabled={uploading} onClick={() => { onUpload(); close(); }}>{uploading ? '上传中…' : '上传 PDF'}</button><button type="button" disabled={!activeTask} onClick={() => { setAdding(value => !value); setPapersOpen(true); close(); }}>选择已有论文</button></>}
        </WorkbenchPopover> : <button type="button" disabled={!activeTask} onClick={() => setAdding(!adding)} aria-label="添加已有论文"><Plus size={16} /></button>}
      </div>
      {(papersOpen || query) && <div className="workbench-paper-list">
      {paperIds.map((id) => {
        const paper = papers.find((item) => item.id === id);
        return <div key={id} className="workbench-paper-row">
          <button type="button" title={paper?.title || paper?.filename || id} aria-current={!selectedDocumentId && !selectedLearningId && activeTask.focusedPaperId === id ? 'page' : undefined} onClick={() => onOpenPaper(id)} className="workbench-record-link theme-text-primary"><FileText size={15} /><span>{paperShortName(paper, id)}</span></button>
          <WorkbenchPopover label={`论文操作：${paper?.title || paper?.filename || id}`}>
            {close => <><p className="workbench-menu-caption">移出当前任务，保留论文文件。</p><button type="button" disabled={busy} aria-label={`移出任务：${paper?.title || paper?.filename || id}`} onClick={() => perform(async isCurrent => { await onRemovePaper(id); if (isCurrent()) { setRemovedPaper({ id, title: paperShortName(paper, id) }); close(); } })}>移出任务</button></>}
          </WorkbenchPopover>
        </div>;
      })}
      {adding && <div className="theme-border my-2 rounded border p-2">
        {papers.filter((paper) => !activeTask?.paperIds.includes(paper.id)).map((paper) => <button type="button" disabled={busy} key={paper.id} onClick={() => perform(() => onAddPaper(paper.id))} className="theme-text-primary block w-full truncate py-2 text-left text-sm">{paper.title || paper.filename}</button>)}
        {!papers.some((paper) => !activeTask?.paperIds.includes(paper.id)) && <p className="theme-text-muted text-xs">暂无其他论文，可上传新论文。</p>}
      </div>}
      {children}
      </div>}
      </section>
      <section className="workbench-navigation-records" aria-label="笔记与成果列表">
      <div className="workbench-section-head"><h2>笔记与成果</h2><div>
        {onCreateNote && <button type="button" aria-label="新建笔记" disabled={!activeTask || busy} onClick={() => perform(onCreateNote)}><Plus size={16} /></button>}
        <WorkbenchPopover label="筛选成果" trigger={<SlidersHorizontal size={15} />}><label className="workbench-menu-caption">成果类型
      <select className="unified-nav-filter" aria-label="成果类型" value={type} onChange={event => setType(event.target.value)}>
        <option value="all">全部成果</option><option value="note">笔记</option><option value="research">研究报告</option><option value="compare">论文比较</option><option value="translation">译文</option><option value="critique">批判阅读</option><option value="background">补课</option><option value="compose">组合成果</option>
      </select></label></WorkbenchPopover></div></div>
      {type !== 'all' && <button type="button" className="workbench-filter-state" onClick={() => setType('all')}>{typeLabels[type] || '筛选'} · 清除筛选</button>}
      <div className="workbench-record-list">
      {documents.map(({ item, title, detail, index }) => <button type="button" aria-current={selectedDocumentId && selectedDocumentId === (item.id || item.artifactId) ? 'page' : undefined} key={item.id || item.artifactId || index} aria-label={[title, typeLabels[kindOf(item)] || '成果', detail].filter(Boolean).join(' · ')} title={[title, detail].filter(Boolean).join('\n')} onClick={() => onOpenArtifact(item)} className="task-document-link theme-text-primary flex w-full items-center gap-2 rounded py-2 text-left text-sm"><NotebookPen size={15} className="shrink-0" /><span className="task-document-text min-w-0 flex-1"><span className="block truncate">{title}</span>{detail && <span className="theme-text-muted block truncate text-xs">{detail}</span>}</span><span className="task-document-type theme-text-muted">{typeLabels[kindOf(item)] || '成果'}</span></button>)}
      {!documents.length && <p className="theme-text-muted text-xs">{query || type !== 'all' ? '没有匹配的成果' : '保存的内容会出现在这里'}</p>}
      <LearningHistory key={activeTask?.id} activities={matchingLearning} papers={papers} onOpen={onOpenLearning} searchActive={Boolean(query.trim())} searchQuery={query.trim()} selectedLearningId={selectedLearningId} />
      {noSearchResults && <p role="status" className="task-navigation-empty theme-text-muted">没有匹配的论文、成果或学习记录。请换个关键词，或调整成果类型。</p>}

      </div></section></div>
      {removedPaper && <div className="workbench-undo" role="status"><span>已移出 {removedPaper.title}</span><button type="button" disabled={busy} onClick={() => perform(async isCurrent => { await onAddPaper(removedPaper.id); if (isCurrent()) setRemovedPaper(null); })}>撤销</button></div>}
    </>}
  </aside>;
}
