import React from 'react';

const activeStatuses = new Set(['queued', 'running', 'unknown', 'cancelling']);
const labels = { queued: '等待处理', running: '正在处理', unknown: '正在确认结果', cancelling: '正在停止',
  awaiting_submission: '提交未确认', failed: '未完成', interrupted: '处理已中断', cancelled: '已停止', conflicted: '结果已生成，请核对任务' };

/** Small recovery controls; the full execution history remains folded. */
export default function ConversationExecution({ task, records, busy, onRetry, onSubmitSaved, onRefresh, onCancel, onOpenResult }) {
  const visible = Object.values(records).filter(record => record.taskId === task.id && !record.retriedBy && record.status !== 'succeeded');
  const active = visible.filter(record => activeStatuses.has(record.status));
  const completed = visible.filter(record => !activeStatuses.has(record.status) && labels[record.status])
    .sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')));
  const renderRecord = record => {
    const input = record.request || record.input || {};
    const question = input.displayText || input.message || input.goal || input.question || input.text || '';
    const text = record.result?.artifact?.text || record.result?.message || record.result?.reply;
    return <div className="unified-execution-row" key={record.requestId}>
      <span role="status">{labels[record.status]}</span>
      {question && <span className="unified-execution-question" title={question}>{question}</span>}
      {record.status === 'awaiting_submission'
        ? <><button type="button" onClick={onRefresh}>查询状态</button><button type="button" disabled={busy || !onSubmitSaved} onClick={() => onSubmitSaved(record.requestId)}>继续发送</button><button type="button" onClick={() => onCancel(record.requestId)}>停止</button></>
        : activeStatuses.has(record.status)
        ? <><button type="button" onClick={onRefresh}>查询状态</button><button type="button" disabled={record.status === 'cancelling'} onClick={() => onCancel(record.requestId)}>停止</button></>
        : record.status !== 'conflicted' && input && <button type="button" disabled={busy || !record.request} onClick={() => onRetry(record.requestId)}>重试</button>}
      {record.status === 'conflicted' && text && <button type="button" onClick={() => onOpenResult?.(record)}>打开已生成结果</button>}
      {record.error && <details><summary>详情</summary><p>{record.error}</p></details>}
    </div>;
  };
  if (!active.length && !completed.length) return null;
  return <div className="unified-execution" aria-label="处理与恢复">
    {active.map(renderRecord)}
    {completed.slice(0, 1).map(renderRecord)}
    {completed.length > 1 && <details><summary>其他未完成请求（{completed.length - 1}）</summary>{completed.slice(1).map(renderRecord)}</details>}
  </div>;
}
