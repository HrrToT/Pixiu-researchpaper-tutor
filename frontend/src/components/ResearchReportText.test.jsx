import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ResearchReportText from './ResearchReportText';

describe('research citations', () => {
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
});
