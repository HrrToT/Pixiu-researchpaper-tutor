import React, { useState } from 'react';
import { getResearchStatusMeta } from './deepResearchPanelModel';

function ResearchCard({ taskId, run, result, onAction, onJumpToSource, onOpenReport }) {
  const [busy, setBusy] = useState(false);
  const [reviews, setReviews] = useState({});
  const [planDraft, setPlanDraft] = useState(null);
  const act = async (action, payload) => {
    setBusy(true);
    try { await onAction(taskId, run.researchId, action, payload); } finally { setBusy(false); }
  };
  if (!result) return <div role="status">正在读取研究：{run.question}</div>;
  const plan = (result.plan || []).map((item) => typeof item === 'string' ? item : item.question || item.subQuestion || '').filter(Boolean);
  const risks = result.reviewRisks || [];
  const sources = (result.findings || []).flatMap((finding) => finding.sources || []);
  return <article className="conversation-research-card">
    <div><strong>{run.question}</strong> · <span>{getResearchStatusMeta(result.status).label}</span></div>
    {result.status === 'awaiting_plan_review' && <>
      <label>研究问题<textarea aria-label="研究问题列表" value={planDraft ?? plan.join('\n')} onChange={(event) => setPlanDraft(event.target.value)} /></label>
      <button type="button" disabled={busy || !(planDraft ?? plan.join('\n')).trim()} onClick={() => act('plan-review', { subQuestions: (planDraft ?? plan.join('\n')).split('\n').map((line) => line.trim()).filter(Boolean), reviewNotes: '' })}>按这些问题研究</button>
    </>}
    {result.status === 'awaiting_final_review' && <>
      <p>报告已生成，核对后可保存为成果。</p>
      <button type="button" onClick={() => onOpenReport?.(run, result)}>打开研究报告</button>
      {risks.map((risk) => <label key={risk.riskId} className="research-risk">{risk.label}：{risk.detail}
        <select aria-label={`核对：${risk.detail}`} value={reviews[risk.riskId] || ''} onChange={(event) => setReviews((value) => ({ ...value, [risk.riskId]: event.target.value }))}>
          <option value="">选择核对结果</option><option value="reviewed">已核对</option><option value="needs_follow_up">仍需后续研究</option>
        </select>
      </label>)}
      <button type="button" disabled={busy || risks.some((risk) => !reviews[risk.riskId])} onClick={() => act('final-review', { reviewNotes: '', riskReviews: risks.map((risk) => ({ riskId: risk.riskId, reviewStatus: reviews[risk.riskId] })) })}>确认并保存结果</button>
    </>}
    {sources.length > 0 && <details><summary>查看来源（{sources.length}）</summary>{sources.map((source, index) => <button type="button" key={`${source.sourceId}-${index}`} onClick={() => onJumpToSource(source)}>{source.title || source.pdfId || '原文'} · {source.text?.slice(0, 120)}</button>)}</details>}
    {result.error && <p role="alert">{result.error}</p>}
    {['failed', 'cancelled'].includes(result.status) && result.plan?.length > 0 && <button type="button" disabled={busy} onClick={() => act('resume')}>继续未完成的研究</button>}
    {!['succeeded', 'failed', 'cancelled'].includes(result.status) && <button type="button" disabled={busy} onClick={() => act('cancel')}>取消研究</button>}
  </article>;
}
export default function ConversationResearch({ task, research, onJumpToSource, onOpenReport }) {
  return <div className="conversation-research-list">{(task.researchRuns || []).map((run) => <ResearchCard key={run.researchId} taskId={task.id} run={run}
    result={research.runs[`${task.id}/${run.researchId}`]} onAction={research.action} onJumpToSource={onJumpToSource} onOpenReport={onOpenReport} />)}</div>;
}
