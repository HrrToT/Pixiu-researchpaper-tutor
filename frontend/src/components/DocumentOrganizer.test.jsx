import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import DocumentOrganizer from './DocumentOrganizer';

const tasks = [{ id: 'a', title: '原任务' }, { id: 'b', title: '目标任务' }];
describe('document organization', () => {
  it('requires a saved document and explicitly carries material consent', async () => {
    const move = vi.fn().mockResolvedValue(undefined);
    const props = { document: { id: 'doc', title: '笔记' }, taskId: 'a', tasks, dirty: true, onRename: vi.fn(), onMove: move };
    const { rerender } = render(<DocumentOrganizer {...props} />);
    fireEvent.change(screen.getByLabelText('移动到任务'), { target: { value: 'b' } });
    expect(screen.getByText('移动成果').disabled).toBe(true);
    rerender(<DocumentOrganizer {...props} dirty={false} />);
    fireEvent.click(screen.getByLabelText('同时加入来源论文，作为目标任务可用材料'));
    fireEvent.click(screen.getByText('移动成果'));
    await waitFor(() => expect(move).toHaveBeenCalledWith('b', true, false));
  });
  it('keeps errors visible and offers querying the original request', async () => {
    const move = vi.fn().mockRejectedValue(new Error('连接中断，结果未确认'));
    render(<DocumentOrganizer document={{ id: 'doc' }} taskId="a" tasks={tasks} onRename={vi.fn()} onMove={move} />);
    fireEvent.click(screen.getByText('查询原移动请求'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('结果未确认'));
    expect(move).toHaveBeenCalledWith(null, false, true);
  });
});
