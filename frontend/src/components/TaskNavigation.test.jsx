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
  it('distinguishes duplicate saved results and opens the selected original document', () => {
    const handlers = props();
    const old = { id: 'old', title: '第4页译文', createdAt: '2026-10-08T12:00:00Z', pageIndex: 3, text: '旧译文' };
    const recent = { id: 'recent', title: '第4页译文', createdAt: '2026-10-09T12:00:00Z', pageIndex: 3, text: '新译文' };
    const task = { ...handlers.activeTask, artifacts: [old, recent] };
    const snapshot = JSON.stringify(task);
    render(<TaskNavigation {...handlers} activeTask={task} />);
    const results = screen.getAllByRole('button', { name: /第4页译文/ });
    expect(results[0]).toHaveTextContent('记录 2 · 第 4 页');
    expect(results[1]).toHaveTextContent('记录 1 · 第 4 页');
    fireEvent.click(screen.getByRole('button', { name: /第4页译文.*记录 2/ }));
    expect(handlers.onOpenArtifact).toHaveBeenCalledWith(recent);
    expect(JSON.stringify(task)).toBe(snapshot);
  });
  it('keeps undated notes distinguishable without inventing save times', () => {
    const handlers = props();
    const notes = [{ id: 'n1', title: '原文笔记', source: { text: '第一处选区' } },
      { id: 'n2', title: '原文笔记', createdAt: 'invalid', source: { text: '第二处选区', sourcePageIndex: 2 } }];
    render(<TaskNavigation {...handlers} activeTask={{ ...handlers.activeTask, notes }} />);
    const results = screen.getAllByRole('button', { name: /原文笔记/ });
    expect(results[0]).toHaveTextContent('记录 1 · 第一处选区');
    expect(results[1]).toHaveTextContent('记录 2 · 第 3 页 · 第二处选区');
    expect(results[1]).not.toHaveTextContent('Invalid Date');
    fireEvent.click(screen.getByRole('button', { name: /原文笔记.*记录 2/ }));
    expect(handlers.onOpenArtifact).toHaveBeenCalledWith(notes[1]);
  });
});
