import React, { useState } from 'react';
import { Plus, ChevronLeft, ChevronRight, FileText, NotebookPen, X } from 'lucide-react';
import { taskDocumentNavigation } from '../utils/taskDocumentNavigation';
import LearningHistory, { learningSearchText } from './LearningHistory';
import './TaskNavigationDetails.css';

export default function TaskNavigation({ tasks, activeTask, papers, collapsed, onToggle,
  onSelectTask, onCreateTask, onOpenPaper, onAddPaper, onRemovePaper, onOpenArtifact, learningRecords = [], onOpenLearning, selectedDocumentId, selectedLearningId, children }) {
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState('');
  const [type, setType] = useState('all');
  React.useEffect(() => { setQuery(''); setType('all'); setAdding(false); }, [activeTask?.id]);
  const matches = value => !query.trim() || `${value || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const kindOf = item => {
    if (activeTask?.notes?.includes(item)) return 'note';
    const storedKind = item.type || item.kind;
    const aliases = { 'translation-page': 'translation', 'research-report': 'research', comparison: 'compare', insight: 'artifact' };
    if (storedKind && storedKind !== 'artifact' && storedKind !== 'insight') return aliases[storedKind] || storedKind;
    if (item.sourceResearchId) return 'research';
    if (Number.isInteger(item.pageIndex) && /译文|翻译/u.test(item.title || '')) return 'translation';
    return activeTask?.messages?.find(message => message.artifactId === (item.id || item.artifactId))?.capability || 'artifact';
  };
  const typeLabels = { note: '笔记', research: '报告', compare: '比较', translation: '译文', critique: '批判', background: '补课', compose: '组合', artifact: '成果' };
  const documents = taskDocumentNavigation(activeTask).filter(({ item, title }) => matches([
    title, item.text, item.content, item.summary, item.aiInterpretation, item.source?.text,
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
      <input className="unified-nav-search" aria-label="搜索材料与记录" placeholder="搜索材料与记录" value={query} onChange={event => setQuery(event.target.value)} />
      {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
      <div className="mb-2 flex items-center justify-between"><h2 className="theme-text-secondary text-sm">论文与材料</h2><button type="button" disabled={!activeTask} onClick={() => setAdding(!adding)} aria-label="添加已有论文"><Plus size={16} /></button></div>
      {paperIds.map((id) => {
        const paper = papers.find((item) => item.id === id);
        return <div key={id} className="group flex items-center gap-1">
          <button type="button" title={paper?.title || paper?.filename || id} aria-current={!selectedDocumentId && !selectedLearningId && activeTask.focusedPaperId === id ? 'page' : undefined} onClick={() => onOpenPaper(id)} className="theme-text-primary flex min-w-0 flex-1 items-center gap-2 rounded py-2 text-left text-sm"><FileText size={15} className="shrink-0" /><span className="truncate">{(paper?.title || paper?.filename || id).split(/[:：]/u)[0]}</span></button>
          <button type="button" disabled={busy} aria-label={`移出任务：${paper?.title || paper?.filename || id}`} title="仅移出当前任务，保留论文文件" onClick={() => perform(() => onRemovePaper(id))} className="theme-text-muted p-1"><X size={13} /></button>
        </div>;
      })}
      {adding && <div className="theme-border my-2 rounded border p-2">
        {papers.filter((paper) => !activeTask?.paperIds.includes(paper.id)).map((paper) => <button type="button" disabled={busy} key={paper.id} onClick={() => perform(() => onAddPaper(paper.id))} className="theme-text-primary block w-full truncate py-2 text-left text-sm">{paper.title || paper.filename}</button>)}
        {!papers.some((paper) => !activeTask?.paperIds.includes(paper.id)) && <p className="theme-text-muted text-xs">暂无其他论文，可上传新论文。</p>}
      </div>}
      {children}
      <h2 className="theme-text-secondary mb-2 mt-5 text-sm">笔记与成果</h2>
      <select className="unified-nav-filter" aria-label="成果类型" value={type} onChange={event => setType(event.target.value)}>
        <option value="all">全部成果</option><option value="note">笔记</option><option value="research">研究报告</option><option value="compare">论文比较</option><option value="translation">译文</option><option value="critique">批判阅读</option><option value="background">补课</option><option value="compose">组合成果</option>
      </select>
      {documents.map(({ item, title, detail, index }) => <button type="button" aria-current={selectedDocumentId && selectedDocumentId === (item.id || item.artifactId) ? 'page' : undefined} key={item.id || item.artifactId || index} aria-label={[title, typeLabels[kindOf(item)] || '成果', detail].filter(Boolean).join(' · ')} title={[title, detail].filter(Boolean).join('\n')} onClick={() => onOpenArtifact(item)} className="task-document-link theme-text-primary flex w-full items-center gap-2 rounded py-2 text-left text-sm"><NotebookPen size={15} className="shrink-0" /><span className="task-document-text min-w-0 flex-1"><span className="block truncate">{title}</span>{detail && <span className="theme-text-muted block truncate text-xs">{detail}</span>}</span><span className="task-document-type theme-text-muted">{typeLabels[kindOf(item)] || '成果'}</span></button>)}
      {!documents.length && <p className="theme-text-muted text-xs">{query || type !== 'all' ? '没有匹配的成果' : '保存的内容会出现在这里'}</p>}
      <LearningHistory key={activeTask?.id} activities={matchingLearning} papers={papers} onOpen={onOpenLearning} searchActive={Boolean(query.trim())} searchQuery={query.trim()} selectedLearningId={selectedLearningId} />
      {noSearchResults && <p role="status" className="task-navigation-empty theme-text-muted">没有匹配的论文、成果或学习记录。请换个关键词，或调整成果类型。</p>}

    </div>}
  </aside>;
}
