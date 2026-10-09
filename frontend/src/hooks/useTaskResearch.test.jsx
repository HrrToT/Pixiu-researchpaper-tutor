import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useTaskResearch } from './useTaskResearch';

describe('task research integration', () => {
  it.each(['cancelled', 'failed', 'succeeded'])('stops GET polling after confirmed %s even when another run is added', async status => {
    vi.useFakeTimers();
    try {
      const task = { id:'t', researchRuns:[{researchId:'done'}] };
      const workspace = { tasks:[task], activeTaskId:'t', adoptServerTask:vi.fn() };
      const api = { get:vi.fn(async (_taskId, researchId) => ({workspace:task,
        task:{taskId:researchId,status:researchId === 'done' ? status : 'running'}})) };
      const {rerender,unmount} = renderHook(({current}) => useTaskResearch(current,api), {initialProps:{current:workspace}});
      await act(async () => {});
      await act(async () => vi.advanceTimersByTimeAsync(12000));
      expect(api.get.mock.calls.filter(([,id])=>id==='done')).toHaveLength(1);
      rerender({current:{...workspace,tasks:[{...task,researchRuns:[...task.researchRuns,{researchId:'new'}]}]}});
      await act(async () => vi.advanceTimersByTimeAsync(4000));
      expect(api.get.mock.calls.filter(([,id])=>id==='done')).toHaveLength(1);
      expect(api.get.mock.calls.filter(([,id])=>id==='new').length).toBeGreaterThan(1);
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it('resumes GET recovery after an explicit action with an uncertain response without repeating the action', async () => {
    vi.useFakeTimers();
    try {
      const task = {id:'t',researchRuns:[{researchId:'r'}]};
      const workspace = {tasks:[task],activeTaskId:'t',adoptServerTask:vi.fn()};
      let status='cancelled';
      const api = {get:vi.fn(async () => ({workspace:task,task:{taskId:'r',status}})),
        action:vi.fn(async () => {status='running';throw new Error('操作返回未确认');})};
      const {result,unmount} = renderHook(() => useTaskResearch(workspace,api));
      await act(async () => {});
      await act(async () => vi.advanceTimersByTimeAsync(4000));
      expect(api.get).toHaveBeenCalledTimes(1);
      await act(async () => result.current.action('t','r','retry',{}));
      await act(async () => vi.advanceTimersByTimeAsync(8000));
      expect(result.current.runs['t/r'].status).toBe('running');
      expect(api.get.mock.calls.length).toBeGreaterThan(1);
      expect(api.action).toHaveBeenCalledTimes(1);
      expect(result.current.error).toBe('操作返回未确认');
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it('clears a recovered poll error and keeps other task failures out of the current task', async () => {
    vi.useFakeTimers();
    try {
      const a = { id:'a', researchRuns:[{ researchId:'ra' }] };
      const b = { id:'a/child', researchRuns:[{ researchId:'rb' }] };
      let recovered = false;
      const api = { get:vi.fn(async (taskId, researchId) => {
        if (taskId !== 'a' || !recovered) throw new Error(taskId + ':502');
        return { task:{ taskId:researchId, status:'awaiting_final_review' } };
      }) };
      const workspace = { tasks:[a,b], activeTaskId:'a', adoptServerTask:vi.fn() };
      const { result, rerender, unmount } = renderHook(({ current }) => useTaskResearch(current,api), { initialProps:{ current:workspace } });
      await act(async () => {});
      expect(result.current.error).toBe('a:502');
      recovered = true;
      await act(async () => vi.advanceTimersByTimeAsync(4000));
      expect(result.current.error).toBe('');
      rerender({ current:{ ...workspace, activeTaskId:b.id } });
      expect(result.current.error).toBe('a/child:502');
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it('does not hide an unconfirmed action error merely because polling recovers', async () => {
    vi.useFakeTimers();
    try {
      const task = { id:'t', researchRuns:[{ researchId:'r' }] };
      const workspace = { tasks:[task], activeTaskId:'t' };
      const api = { get:vi.fn(async () => ({ task:{ taskId:'r', status:'awaiting_plan_review' } })),
        action:vi.fn(async () => { throw new Error('计划保存未确认'); }) };
      const { result, unmount } = renderHook(() => useTaskResearch(workspace,api));
      await act(async () => result.current.action('t','r','plan-review',{}));
      await act(async () => vi.advanceTimersByTimeAsync(4000));
      expect(result.current.error).toBe('计划保存未确认');
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it('creates research with a material snapshot and external retrieval disabled', async () => {
    const task = { id: 't', revision: 4, focusedPaperId: 'a', researchRuns: [] };
    const workspace = { tasks: [task], adoptServerTask: vi.fn(), updateTask: vi.fn() };
    const api = { start: vi.fn(async () => ({ task, result: { task: { taskId: 'r', status: 'pending' } } })) };
    const { result } = renderHook(() => useTaskResearch(workspace, api));
    await act(async () => result.current.start(task, '研究方法', { allowedPaperIds: ['a', 'b'], primaryPaperId: null }));
    expect(api.start).toHaveBeenCalledWith('t', { question: '研究方法', pdfId: 'a', allowedPaperIds: ['a', 'b'], expectedTaskRevision: 4, allowExternalSearch: false, allowWebSearch: false });
    expect(workspace.adoptServerTask).toHaveBeenCalledWith(task);
  });
  it('restores a completed run into its original task without duplicating saved results', async () => {
    const task = { id: 'original', messages: [], artifacts: [], researchRuns: [{ researchId: 'r', question: '研究', paperIds: ['a'], primaryPaperId: 'a' }] };
    const workspace = { tasks: [task], activeTaskId: 'other', updateTask: vi.fn(), adoptServerTask: vi.fn() };
    const saved = { ...task, messages: [{ id: 'research:r:answer', content: '有证据的结果', artifactId: 'research:r:artifact' }],
      artifacts: [{ id: 'research:r:artifact', text: '## 结论\n有证据的结果' }] };
    const response = { workspace: saved, task: { taskId: 'r', status: 'succeeded', report: '## 结论\n有证据的结果', findings: [] } };
    const api = { get: vi.fn(async () => response), action: vi.fn(async () => response) };
    const { result } = renderHook(() => useTaskResearch(workspace, api));
    await waitFor(() => expect(workspace.adoptServerTask).toHaveBeenCalledWith(saved));
    expect(workspace.updateTask).not.toHaveBeenCalled();
    await act(async () => result.current.action('original', 'r', 'final-review', {}));
    expect(workspace.adoptServerTask).toHaveBeenLastCalledWith(saved);
    expect(workspace.updateTask).not.toHaveBeenCalled();
  });
  it('does not fabricate locally saved results when server publication is unconfirmed', async () => {
    const task = { id: 't', researchRuns: [{ researchId: 'r' }] };
    const workspace = { tasks: [task], updateTask: vi.fn(), adoptServerTask: vi.fn() };
    const api = { get: vi.fn(async () => ({ task: { taskId: 'r', status: 'succeeded', report: '完整报告' } })) };
    const { result } = renderHook(() => useTaskResearch(workspace, api));
    await waitFor(() => expect(result.current.error).toContain('保存尚未确认'));
    expect(workspace.updateTask).not.toHaveBeenCalled();
    expect(workspace.adoptServerTask).not.toHaveBeenCalled();
  });
});
