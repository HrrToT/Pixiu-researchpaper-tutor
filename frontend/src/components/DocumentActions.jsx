import React from 'react';
import WorkbenchPopover from './WorkbenchPopover';
import DocumentVersionHistory from './DocumentVersionHistory';
import DocumentOrganizer from './DocumentOrganizer';
import { Save } from 'lucide-react';

export default function DocumentActions({ document, editing, dirty, saving, disabled, onEdit, onSave,
  onLocate, onRecheck, recheckDisabled, onRestore, taskId, tasks, onRename, onMove, onExport, sources }) {
  return <div className="unified-document-toolbar workbench-document-actions">
    <button type="button" onClick={onEdit}>{editing ? '完成编辑' : '编辑'}</button>
    {(editing || dirty) && <button type="button" className="workbench-primary" disabled={saving || disabled || !dirty} onClick={onSave}><Save size={15} />{saving ? '保存中…' : '保存'}</button>}
    {(editing || dirty || saving) && <span className="unified-document-save-state" role="status">{saving ? '正在保存' : dirty ? '未保存修改' : '已保存'}</span>}
    <WorkbenchPopover label="成果更多操作">
      {onLocate && <button type="button" onClick={onLocate}>定位原对话</button>}
      {onRecheck && <button type="button" disabled={recheckDisabled} onClick={onRecheck}>重新核查</button>}
      <DocumentVersionHistory document={document} onRestore={onRestore} disabled={saving || disabled} />
      <DocumentOrganizer document={document} taskId={taskId} tasks={tasks} dirty={dirty || saving}
        onRename={onRename} onMove={onMove} onExport={onExport} />
      {sources}
    </WorkbenchPopover>
  </div>;
}
