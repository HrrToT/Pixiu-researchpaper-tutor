import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ResearchResultCard from './ResearchResultCard';

const props = { taskId: 't', run: { researchId: 'r' }, result: {
  contractVersion: 2, runRevision: 4, status: 'running', outcome: 'none', title: '对照实验设计',
  activity: { label: '核对消融实验' }, allowedActions: ['cancel'], plan: [{ itemId: 'p', question: '区分两个因素' }],
} };

describe('versioned research result', () => {
  it('renders structured failures and a versioned plan without crashing', () => {
    render(<ResearchResultCard {...props} result={{ ...props.result, status: 'paused',
      error: { code: 'unknown_call', message: '上次调用结果未确认' },
      plan: { revision: 2, items: [{ itemId: 'p', question: '核对实验条件' }] } }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('上次调用结果未确认');
    fireEvent.click(screen.getByRole('button', { name: '详情' }));
    expect(screen.getByText('核对实验条件')).toBeInTheDocument();
  });
  it('keeps progress compact and exposes only server-authorized actions', () => {
    render(<ResearchResultCard {...props} onAction={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('正在研究');
    expect(screen.getByText('核对消融实验')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '继续研究' })).not.toBeInTheDocument();
    expect(screen.queryByText('区分两个因素')).not.toBeInTheDocument();
  });

  it('closes details with Escape and restores focus to the trigger', () => {
    render(<ResearchResultCard {...props} />);
    const trigger = screen.getByRole('button', { name: '详情' });
    fireEvent.click(trigger);
    expect(screen.getByText('区分两个因素')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('region', { name: '研究详情' }), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: '研究详情' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('retains partial results without demanding artificial human approval', () => {
    const open = vi.fn();
    const result = { ...props.result, status: 'completed', outcome: 'partial', summary: '可执行四组对照，缺少统一设置下的实测数据。',
      report: { versionId: 'v1' }, allowedActions: ['open_report', 'continue'], sourceCount: 2 };
    render(<ResearchResultCard {...props} result={result} onOpenReport={open} />);
    expect(screen.getByRole('status')).toHaveTextContent('已完成部分研究');
    expect(screen.queryByRole('button', { name: '停止' })).not.toBeInTheDocument();
    expect(screen.queryByText('确认并保存结果')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看已有结果' }));
    expect(open).toHaveBeenCalledWith(props.run, result);
  });

  it('reuses action identity after an uncertain response rather than creating a new action', async () => {
    const action = vi.fn().mockRejectedValueOnce(new Error('网络断开')).mockResolvedValueOnce(undefined);
    render(<ResearchResultCard {...props} onAction={action} />);
    fireEvent.click(screen.getByRole('button', { name: '停止' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('网络断开');
    fireEvent.click(screen.getByRole('button', { name: '停止' }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
    expect(action.mock.calls[0]).toEqual(action.mock.calls[1]);
    expect(action.mock.calls[0][3]).toEqual(expect.objectContaining({ expectedRunRevision: 4, requestId: expect.any(String) }));
  });

  it('distinguishes abstracts from full text when opening material details', () => {
    render(<ResearchResultCard {...props} result={{ ...props.result, sources: [{ workId: 'w', title: '公开论文', accessLevel: 'abstract' }] }} />);
    fireEvent.click(screen.getByRole('button', { name: '详情' }));
    fireEvent.click(screen.getByRole('tab', { name: '资料' }));
    expect(screen.getByText('仅摘要')).toBeInTheDocument();
  });
});
