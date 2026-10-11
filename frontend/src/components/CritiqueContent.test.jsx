import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ChatPanel from './ChatPanel';
import CritiqueContent from './CritiqueContent';

const source = { sourceId: 's1', pdfId: 'p1', pageIndex: 3, text: '原文报告的实验条件。' };
const text1 = `第一点完整判断。${'完整必要条件。'.repeat(80)}`;
const fixture = {
  role: 'ai', capability: 'critique', artifactId: 'a1', content: 'stored summary', rag_sources: [source],
  critique: { schemaVersion: 2, lead: '总判断。',
    claims: [{ id: 'c1', text: '论文事实', references: [{ sourceId: 's1', quote: source.text }] }],
    issues: [{ id: 'i1', title: '条件', conclusionClaimId: 'c1', supportClaimIds: [] }, { id: 'i2', title: '范围' }],
    presentation: { chatIssueIds: ['i1', 'i2'], artifactIssueIds: ['i1', 'i2'], standalone: true },
    chatBlocks: [{ issueId: 'i1', text: text1 }, { issueId: 'i2', text: '第二点的事实与推断都完整。' }],
    artifactBlocks: [{ issueId: 'i1', text: text1 }, { issueId: 'i2', text: '第二点详细理由。' }],
    pending: [{ id: 'pending1', whatToCheck: '次要核查目标' }] },
};

describe('grouped critique presentation', () => {
  it('preserves both complete chat points beyond the old preview budget and expands source locally', () => {
    const jump = vi.fn();
    const send = vi.fn();
    const follow = vi.fn();
    render(<ChatPanel messages={[fixture]} onSendMessage={send} onJumpToSource={jump} onFollowupIssue={follow} />);
    expect(screen.getByText(text1)).toBeInTheDocument();
    expect(screen.getByText('第二点的事实与推断都完整。')).toBeInTheDocument();
    expect(screen.queryByText('次要核查目标')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('查看依据 · 1 处'));
    expect(screen.getByText(source.text)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '跳回原文 · 按摘录定位' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ pdfId: 'p1', pageIndex: 3, sourceId: 's1' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ literalQuote: source.text }));
    fireEvent.click(screen.getAllByRole('button', { name: '追问这一点' })[1]);
    expect(follow).toHaveBeenCalledWith(fixture, 'i2');
    expect(send).not.toHaveBeenCalled();
  });

  it('keeps edited and legacy document text without inferring claim relationships', () => {
    const view = render(<CritiqueContent value={{ ...fixture, edited: true }} text="用户修改后的判断" target="artifact" />);
    expect(screen.getByText('用户修改后的判断')).toBeInTheDocument();
    expect(screen.queryByText(text1)).not.toBeInTheDocument();
    expect(screen.getByText(/修改内容不作为论文原文依据/u)).toBeInTheDocument();
    view.rerender(<CritiqueContent value={{}} text="旧成果原始正文" target="artifact" />);
    expect(screen.getByText('旧成果原始正文')).toBeInTheDocument();
    expect(screen.queryByText(/查看依据/u)).not.toBeInTheDocument();
  });

  it('preserves the full composed response instead of replacing it with critique-only blocks', () => {
    render(<CritiqueContent value={{ ...fixture, capability: 'compose', critique: { ...fixture.critique, presentation: { ...fixture.critique.presentation, standalone: false } } }} text="完整解释、比较与批判正文" />);
    expect(screen.getByText('完整解释、比较与批判正文')).toBeInTheDocument();
    expect(screen.queryByText(text1)).not.toBeInTheDocument();
  });
});
