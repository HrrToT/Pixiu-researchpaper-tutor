import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ConversationResearch from './ConversationResearch';

const task = { id: 't', researchRuns: [{ researchId: 'r', question: '比较方法' }] };
describe('research review in conversation', () => {
  it('requires a user action before approving the research plan', async () => {
    const action = vi.fn(async () => {});
    render(<ConversationResearch task={task} research={{ action, runs: { 't/r': {
      status: 'awaiting_plan_review', plan: [{ question: '方法的假设是什么？' }],
    } } }} />);
    expect(action).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('textbox', { name: '研究问题列表' }), { target: { value: '实验是否公平？' } });
    fireEvent.click(screen.getByRole('button', { name: '按这些问题研究' }));
    await waitFor(() => expect(action).toHaveBeenCalledWith('t', 'r', 'plan-review', { subQuestions: ['实验是否公平？'], reviewNotes: '' }));
  });
  it('does not silently mark unresolved evidence risks as reviewed', async () => {
    const action = vi.fn(async () => {});
    render(<ConversationResearch task={task} research={{ action, runs: { 't/r': {
      status: 'awaiting_final_review', report: '结论', reviewRisks: [{ riskId: 'risk', label: '证据缺口', detail: '缺少对照' }],
    } } }} />);
    expect(screen.getByRole('button', { name: '确认并保存结果' })).toBeDisabled();
    fireEvent.change(screen.getByRole('combobox', { name: '核对：缺少对照' }), { target: { value: 'needs_follow_up' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并保存结果' }));
    await waitFor(() => expect(action).toHaveBeenCalledWith('t', 'r', 'final-review', { reviewNotes: '', riskReviews: [{ riskId: 'risk', reviewStatus: 'needs_follow_up' }] }));
  });
  it('opens the full draft outside the conversation instead of expanding a long report inline', () => {
    const open = vi.fn();
    const result = { status: 'awaiting_final_review', report: '完整研究正文'.repeat(300), reviewRisks: [] };
    render(<ConversationResearch task={task} research={{ action: vi.fn(), runs: { 't/r': result } }} onOpenReport={open} />);
    expect(screen.queryByText(result.report)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开研究报告' }));
    expect(open).toHaveBeenCalledWith(task.researchRuns[0], result);
  });
});
