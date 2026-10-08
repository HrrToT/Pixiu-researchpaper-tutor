import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import ConversationExecution from './ConversationExecution';

it('shows concise failure recovery with original question and folded details', () => {
  const retry = vi.fn();
  render(<ConversationExecution task={{ id: 'task' }} records={{ failed: { taskId: 'task', requestId: 'failed', status: 'failed',
    request: { message: 'original question' }, error: 'long diagnostic' } }} onRetry={retry} />);
  expect(screen.getByText('original question')).toBeInTheDocument();
  expect(screen.getByText('long diagnostic').closest('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(retry).toHaveBeenCalledWith('failed');
});

it('offers status checking and stopping instead of retry while the result is unconfirmed', () => {
  render(<ConversationExecution task={{ id: 'task' }} records={{ pending: { taskId: 'task', requestId: 'pending', status: 'unknown' } }} />);
  expect(screen.getByText('正在确认结果')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '查询状态' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '停止' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument();
});

it('does not offer paid retry for a generated result that could not be applied', () => {
  const open = vi.fn();
  const record = { taskId: 'task', requestId: 'conflict', status: 'conflicted', result: { artifact: { text: 'complete report' } } };
  render(<ConversationExecution task={{ id: 'task' }} records={{ conflict: record }} onOpenResult={open} />);
  fireEvent.click(screen.getByRole('button', { name: '打开已生成结果' }));
  expect(open).toHaveBeenCalledWith(record);
  expect(screen.queryByText('complete report')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument();
});
