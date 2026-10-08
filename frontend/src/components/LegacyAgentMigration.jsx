import React, { useState } from 'react';
import { taskWorkspaceApi } from '../services/taskWorkspaceApi';
import { browserProjectSnapshot, prepareAgentMigration } from '../utils/legacyAgentMigration';

export default function LegacyAgentMigration({ onImported, api = taskWorkspaceApi }) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState([]);
  const [browser, setBrowser] = useState(null);
  const [selected, setSelected] = useState('');
  const [prepared, setPrepared] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [outcome, setOutcome] = useState(null);
  const load = async () => {
    setOpen(true); setBusy(true); setError(''); setPrepared(null); setOutcome(null);
    try {
      const raw = localStorage.getItem('pixiu-agent-workspace');
      const local = raw ? JSON.parse(raw) : null;
      const response = await api.listLegacyAgentProjects();
      if (response.status !== 'success') throw new Error('旧项目读取未完成，请稍后重试');
      const localProjects = [...(Array.isArray(local?.projects) ? local.projects : []), ...(local?.activeProject ? [local.activeProject] : [])];
      const union = new Map([...localProjects, ...response.projects].filter(item => item?.projectId).map(item => [item.projectId, item]));
      setBrowser(local); setProjects([...union.values()]); setSelected([...union.keys()][0] || '');
    } catch (failure) { setError(failure.message || '读取失败，旧数据保留'); }
    finally { setBusy(false); }
  };
  const inspect = async () => {
    setBusy(true); setError(''); setOutcome(null); setPrepared(null);
    try {
      let server = null;
      let materials = [];
      try { const exported = await api.exportLegacyAgentProject(selected); server = exported.snapshot; materials = exported.materials || []; }
      catch (failure) { if (failure.response?.status !== 404) throw failure; }
      const local = browserProjectSnapshot(browser, selected);
      const result = prepareAgentMigration(server, local);
      const unavailable = result.task.paperIds.filter(id => !materials.some(item => item.id === id && item.fileAvailable));
      result.task.focusedPaperId = materials.find(item => item.fileAvailable && result.task.paperIds.includes(item.id))?.id || null;
      setPrepared({ ...result, unavailable });
    } catch (failure) { setError(failure.message || '核对失败，旧数据保留'); }
    finally { setBusy(false); }
  };
  const migrate = async () => {
    setBusy(true); setError('');
    try {
      const result = await api.importAgentProject({ snapshot: prepared.snapshot, task: prepared.task });
      setOutcome(result);
      if (result.status !== 'conflicted') await onImported(result.task);
    } catch (failure) { setError(failure.message || '导入尚未确认，原数据保留；核对同一项目后可重试'); }
    finally { setBusy(false); }
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(prepared.snapshot, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = `${prepared.task.title}-旧项目备份.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <>
    <button type="button" className="unified-upload" onClick={load}>导入旧研究项目</button>
    {open && <div className="task-draft-overlay"><section className="task-draft-dialog theme-panel theme-border" role="dialog" aria-label="导入旧研究项目">
      <div className="unified-document-toolbar"><strong>导入旧研究项目</strong><button type="button" disabled={busy} onClick={() => setOpen(false)}>关闭</button></div>
      <p>旧数据保留。会话、成果和研究记录将整理到一个任务中。</p>
      <select aria-label="旧研究项目" disabled={busy} value={selected} onChange={event => { setSelected(event.target.value); setPrepared(null); setOutcome(null); }}>
        {projects.map(project => <option key={project.projectId} value={project.projectId}>{project.title || '未命名项目'}</option>)}
      </select>
      <button type="button" disabled={busy || !selected} onClick={inspect}>{busy ? '处理中…' : '核对项目'}</button>
      {!busy && !projects.length && !error && <p>没有旧研究项目。</p>}
      {prepared && <>
        <p>{prepared.counts.papers} 篇论文 · {prepared.counts.messages} 条对话 · {prepared.counts.reports} 份成果 · {prepared.counts.runs} 次研究运行</p>
        {prepared.unavailable?.length > 0 && <p>{prepared.unavailable.length} 篇论文的服务端原文件待恢复或核对；已有成果可以先阅读。</p>}
        <details><summary>备份与来源</summary><p>保留服务端与浏览器原始快照，未明确记录来源的旧对话不用于后续 AI 回答。</p><button type="button" onClick={download}>下载原始备份</button></details>
        {!outcome && <button type="button" disabled={busy} onClick={migrate}>导入为任务</button>}
      </>}
      {outcome && <p role="status">{outcome.status === 'imported' ? '已导入，原项目仍保留。' : outcome.message}</p>}
      {error && <p role="alert">{error}</p>}
      {error && <button type="button" disabled={busy} onClick={load}>重新读取</button>}
    </section></div>}
  </>;
}
