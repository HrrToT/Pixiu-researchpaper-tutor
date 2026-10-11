import React, { useRef, useState } from 'react';
import WorkbenchPopover from './WorkbenchPopover';
import DocumentOrganizer from './DocumentOrganizer';
import { Save } from 'lucide-react';

export default function DocumentActions({ document, editing, dirty, saving, disabled, onEdit, onSave,
  onLocate, onRecheck, recheckDisabled, onRestore, taskId, tasks, onRename, onMove, onExport, kind = '成果', getPendingMove, displayTitle }) {
  const [action, setAction] = useState(null);
  const root = useRef(null);
  return <div ref={root} className="unified-document-toolbar workbench-document-actions">
    <button type="button" onClick={onEdit}>{editing ? '完成编辑' : '编辑'}</button>
    {(editing || dirty) && <button type="button" className="workbench-primary" disabled={saving || disabled || !dirty} onClick={onSave}><Save size={15} />{saving ? '保存中…' : '保存'}</button>}
    {(editing || dirty || saving) && <span className="unified-document-save-state" role="status">{saving ? '正在保存' : dirty ? '未保存修改' : '已保存'}</span>}
    <WorkbenchPopover label={`${kind}更多操作`}>
      {close => <>
      {onLocate && <button type="button" onClick={() => { onLocate(); close(); }}>在对话中查看</button>}
      {onRecheck && <button type="button" disabled={recheckDisabled} onClick={() => { onRecheck(); close(); }}>重新核查</button>}
      <button type="button" onClick={() => { close(false); setAction('rename'); }}>重命名…</button>
      {onExport && <button type="button" onClick={() => { onExport(); close(); }}>下载 Markdown</button>}
      <button type="button" onClick={() => { close(false); setAction('move'); }}>移到其他任务…</button>
      {document.versions?.length > 0 && <button type="button" onClick={() => { close(false); setAction('history'); }}>历史版本（{document.versions.length}）</button>}
      </>}
    </WorkbenchPopover>
    {action && <DocumentOrganizer action={action} document={document} displayTitle={displayTitle} kind={kind} taskId={taskId} tasks={tasks} dirty={dirty || saving} disabled={saving || disabled}
      onRename={onRename} onMove={onMove} onRestore={onRestore} getPendingMove={getPendingMove} onClose={() => { setAction(null); root.current?.querySelector('.workbench-popover-trigger')?.focus(); }} />}
  </div>;
}
