export const operationStatusLabels = { queued: '等待处理', running: '正在处理', unknown: '正在确认结果', cancelling: '正在停止',
  awaiting_submission: '提交未确认', failed: '未完成', interrupted: '处理已中断', cancelled: '已停止', conflicted: '结果已生成，请核对任务', succeeded: '已完成' };

export function operationQuestion(record) {
  const input = record.request || record.input || {};
  return input.displayText || input.message || input.goal || input.question || input.text || '';
}

export function researchTitle(run, result, compactTitle) {
  const title = compactTitle || result?.title || result?.reportTitle || run.title || run.question || '研究';
  const line = String(title).replace(/\s+/gu, ' ').trim();
  return line.length > 32 ? `${line.slice(0, 32)}…` : line;
}

