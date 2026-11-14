import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ResearchReportText from './ResearchReportText';

describe('research citations', () => {
  it('opens external fulltext with its owning task/run and exact quotation page', () => {
    const jump = vi.fn();
    render(<ResearchReportText text="结论 [1](#research-evidence-e)" researchContext={{ taskId: 't', runId: 'r' }} onJumpToSource={jump}
      sources={[{ sourceId: 's', sourceKind: 'arxiv', evidenceIds: ['e'], title: 'External work', accessLevel: 'fulltext',
        evidenceQuotes: { e: { quote: 'Exact quote', location: { page: 5 } } }, url: 'https://arxiv.org/abs/2601.00001v2' }]} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    fireEvent.click(screen.getByRole('button', { name: '查看论文原文' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ researchTaskId: 't', researchRunId: 'r', sourceId: 's', pageIndex: 4 }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('does not promise a fulltext reader for abstract-only external citations', () => {
    render(<ResearchReportText text="结论 [1](#research-evidence-e)" researchContext={{ taskId: 't', runId: 'r' }} onJumpToSource={vi.fn()}
      sources={[{ sourceId: 's', sourceKind: 'arxiv', evidenceIds: ['e'], quote: 'Abstract', accessLevel: 'abstract' }]} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.queryByRole('button', { name: '查看论文原文' })).not.toBeInTheDocument();
  });
  it.each(['unresolved', 'ambiguous'])('does not inherit another quotation page when %s', pageResolution => {
    const jump = vi.fn();
    render(<ResearchReportText text="结论 [1](#research-evidence-ours)" sources={[
      { pdfId: 'p', evidenceIds: ['first', 'ours'], page: 1, pageIndex: 0,
        evidenceQuotes: { ours: { quote: 'Selected quotation', location: { pageResolution } } } },
    ]} onJumpToSource={jump} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.queryByText('第 1 页')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看论文原文' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ evidenceId: 'ours', page: undefined, pageIndex: undefined }));
  });
  it('resolves by evidence identity and jumps to the source page, independent of source ordering', () => {
    const jump = vi.fn();
    render(<ResearchReportText text="结论 [1](#research-evidence-e2)" sources={[
      { pdfId: 'wrong', evidenceIds: ['e1'], quote: 'wrong quote' },
      { pdfId: 'correct', evidenceIds: ['e2'], quote: 'actual quote', title: '论文乙', page: 4 },
    ]} onJumpToSource={jump} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.getByText('actual quote')).toBeInTheDocument();
    const dialog = screen.getByRole('dialog', { name: '引用依据' });
    expect(dialog).toHaveFocus();
    expect(screen.queryByText('wrong quote')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看论文原文' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ pdfId: 'correct', pageIndex: 3 }));
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查看引用/ })).toHaveFocus();
  });
  it('never assigns a missing citation to an available paper', () => {
    render(<ResearchReportText text="结论 [1](#research-evidence-missing)" sources={[{ pdfId: 'other', evidenceIds: ['e'] }]} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.getByText(/这条引用暂不能恢复/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看论文原文' })).not.toBeInTheDocument();
  });
  it('selects the exact quotation when one source owns several evidence rows', () => {
    const jump = vi.fn();
    render(<ResearchReportText text="结论 [1](#research-evidence-ours)" sources={[
      { pdfId: 'p', evidenceIds: ['baseline', 'ours'], quote: 'Baseline row', page: 6,
        evidenceQuotes: { baseline: { quote: 'Baseline row', location: { page: 6 } },
          ours: { quote: 'Exact author row', location: { page: 7 } } } },
    ]} onJumpToSource={jump} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.getByText('Exact author row')).toBeInTheDocument();
    expect(screen.queryByText('Baseline row')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看论文原文' }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ evidenceId: 'ours', pageIndex: 6 }));
  });
  it('does not substitute the first quotation for ambiguous historical evidence', () => {
    render(<ResearchReportText text="结论 [1](#research-evidence-ours)" sources={[
      { pdfId: 'p', evidenceIds: ['baseline', 'ours'], quote: 'Wrong first row' },
    ]} />);
    fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
    expect(screen.getByText(/这条引用暂不能恢复/)).toBeInTheDocument();
    expect(screen.queryByText('Wrong first row')).not.toBeInTheDocument();
  });
});
