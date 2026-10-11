import React from 'react';
import MarkdownContent from './MarkdownContent';
import { SourceChip } from './SourceCitation';
import { normalizeEvidenceSources } from './evidenceCitationModel';

export const hasGroupedCritique = value => value?.critique?.schemaVersion === 2;
const readableCitationSpacing = text => typeof text === 'string' ? text.replace(/([。！？.!?）)])\s+(\[\d+\])/gu, '$1\u00a0$2') : text;

// Only explicit server identities establish relationships. Legacy prose is never parsed.
export function critiqueIssues(value, target = 'chat') {
  if (!hasGroupedCritique(value)) return [];
  const critique = value.critique;
  const claims = new Map((critique.claims || []).map(claim => [claim.id, claim]));
  const issues = new Map((critique.issues || []).map(issue => [issue.id, issue]));
  const sources = value.sources || value.rag_sources || [];
  const lookup = new Map(sources.map(source => [source.sourceId || source.id, source]));
  const blocks = new Map((critique[target === 'chat' ? 'chatBlocks' : 'artifactBlocks'] || []).map(block => [block.issueId, block.text]));
  return (critique.presentation?.[target === 'chat' ? 'chatIssueIds' : 'artifactIssueIds'] || []).flatMap(id => {
    const issue = issues.get(id);
    if (!issue) return [];
    const linked = [issue.conclusionClaimId, ...(issue.supportClaimIds || []), issue.implicationClaimId]
      .filter(Boolean).map(claimId => claims.get(claimId)).filter(Boolean);
    const references = linked.flatMap(claim => (claim.references || []).flatMap(reference => {
      const sourceId = typeof reference === 'string' ? reference : reference.sourceId;
      // The source lookup owns excerpt and paper identity, never the user's prose.
      const source = lookup.get(sourceId);
      return source ? [{ ...source, text: reference.quote || source.text, literalQuote: reference.quote }] : [];
    }));
    const unique = [...new Map(references.map(source => [JSON.stringify([source.sourceId || source.id, source.text]), source])).values()];
    return [{ ...issue, text: blocks.get(id),
      sources: unique, pending: (critique.pending || []).filter(item => issue.relatedPendingIds?.includes(item.id)) }];
  });
}

export default function CritiqueContent({ value, text, target = 'chat', onJumpToSource, onFollowup, className = '' }) {
  const grouped = hasGroupedCritique(value);
  const issues = critiqueIssues(value, target);
  // Edited text remains authoritative for the document view; old claim text must not overwrite it.
  const standalone = value.capability === 'critique' || value.critique?.presentation?.standalone === true;
  const structured = standalone && grouped && !value.edited && issues.length > 0 && issues.every(issue => issue.text);
  const lead = target === 'artifact' ? value.critique?.artifactLead ?? value.critique?.lead : value.critique?.lead;
  const visiblePending = target === 'artifact' ? value.critique?.artifactPending ?? value.critique?.visiblePending : value.critique?.visiblePending;
  const linkedPending = new Set(issues.flatMap(issue => issue.relatedPendingIds || []));
  const pending = (value.critique?.pending || []).filter(item => !linkedPending.has(item.id));
  return <div className={className}>
    {value.edited && grouped && <p className="theme-text-muted text-xs">此版本含用户编辑；修改内容不作为论文原文依据。</p>}
    {structured ? <>
      {typeof lead === 'string' && lead && <MarkdownContent>{readableCitationSpacing(lead)}</MarkdownContent>}
      {issues.map(issue => <section key={issue.id} data-critique-issue-id={issue.id}>
        <MarkdownContent>{readableCitationSpacing(issue.text)}</MarkdownContent>
        {issue.pending.map(item => <p key={item.id}>待核查：{item.whatToCheck || item.topic}</p>)}
        <IssueActions issue={issue} onJumpToSource={onJumpToSource} onFollowup={onFollowup} />
      </section>)}
    </> : <>
      <MarkdownContent>{text}</MarkdownContent>
      {grouped && !value.edited && issues.map((issue, index) => <section key={issue.id} data-critique-issue-id={issue.id}>
        <IssueActions issue={issue} label={`第 ${index + 1} 点`} onJumpToSource={onJumpToSource} onFollowup={onFollowup} />
      </section>)}
    </>}
    {structured && visiblePending && <MarkdownContent>{visiblePending}</MarkdownContent>}
    {target === 'artifact' && grouped && !value.edited && pending.length > 0 && <details><summary>待核查</summary>
      {pending.map(item => <p key={item.id}>{item.whatToCheck || item.topic}</p>)}
    </details>}
  </div>;
}

function IssueActions({ issue, label = '', onJumpToSource, onFollowup }) {
  return <div className="reader-chat-citations critique-issue-actions">
    {issue.sources.length > 0 && <details><summary className="reader-chat-citation">{label} 查看依据 · {issue.sources.length} 处</summary>
      {issue.sources.flatMap(source => normalizeEvidenceSources([source])).map((source, index) => <div key={`${source.sourceId}:${index}`} className="theme-card-soft rounded-lg p-3 text-xs leading-5">
        <MarkdownContent>{source.text}</MarkdownContent>
        <SourceChip source={{ ...source, literalQuote: issue.sources[index]?.literalQuote,
          ...(issue.sources[index]?.literalQuote ? { canJumpToSource: true, locationLabel: '· 按摘录定位' } : {}) }} onJumpToSource={onJumpToSource} />
      </div>)}
    </details>}
    {onFollowup && <button type="button" className="reader-chat-citation" onClick={() => onFollowup(issue.id)}>{label} 追问这一点</button>}
  </div>;
}
