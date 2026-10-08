import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TaskNavigation from './TaskNavigation';

const props = () => ({ tasks: [{ id: 'a', title: '任务 A' }, { id: 'b', title: '任务 B' }],
  activeTask: { id: 'a', paperIds: ['p1'], notes: [], artifacts: [] },
  papers: [{ id: 'p1', title: '论文一' }, { id: 'p2', title: '论文二' }], collapsed: false,
  onToggle: vi.fn(), onSelectTask: vi.fn(), onCreateTask: vi.fn(), onOpenPaper: vi.fn(),
  onAddPaper: vi.fn(), onRemovePaper: vi.fn(), onOpenArtifact: vi.fn() });

describe('task navigation', () => {
  it('distinguishes opening a paper from adding a task material', async () => {
    const handlers = props();
    render(<TaskNavigation {...handlers} />);
    fireEvent.click(screen.getByRole('button', { name: '论文一' }));
    expect(handlers.onOpenPaper).toHaveBeenCalledWith('p1');
    expect(handlers.onAddPaper).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('添加已有论文'));
    fireEvent.click(screen.getByRole('button', { name: '论文二' }));
    await waitFor(() => expect(handlers.onAddPaper).toHaveBeenCalledWith('p2'));
  });
  it('shows a persistence failure instead of hiding it', async () => {
    render(<TaskNavigation {...props()} onCreateTask={async () => { throw new Error('保存失败'); }} />);
    fireEvent.click(screen.getByLabelText('新任务'));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存失败');
  });
  it('keeps an accessible restore control when collapsed', () => {
    const handlers = props();
    render(<TaskNavigation {...handlers} collapsed />);
    fireEvent.click(screen.getByLabelText('展开导航'));
    expect(handlers.onToggle).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('当前任务')).not.toBeInTheDocument();
  });
});
