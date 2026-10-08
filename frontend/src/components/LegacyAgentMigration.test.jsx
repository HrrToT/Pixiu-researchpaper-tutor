import React from 'react';
import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LegacyAgentMigration from './LegacyAgentMigration';
beforeEach(() => localStorage.clear());
it('previews merged records and imports once while preserving the original browser snapshot', async () => {
  const local = { projects: [{ projectId: 'p', title: '旧项目', paperIds: ['B'] }], tasksByProjectId: { p: [{ taskId: 'r', projectId: 'p', draftReport: '原浏览器报告' }] } };
  localStorage.setItem('pixiu-agent-workspace', JSON.stringify(local));
  const api = { listLegacyAgentProjects: vi.fn(async () => ({ status: 'success', projects: [{ projectId: 'p', title: '旧项目' }] })),
    exportLegacyAgentProject: vi.fn(async () => ({ snapshot: { project: { projectId: 'p', title: '旧项目', paperIds: ['A'] }, messages: [] } })),
    importAgentProject: vi.fn(async () => ({ status: 'imported', task: { id: 'new-task' } })) };
  const onImported = vi.fn(); render(<LegacyAgentMigration api={api} onImported={onImported} />);
  fireEvent.click(screen.getByRole('button', { name: '导入旧研究项目' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '核对项目' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '核对项目' }));
  fireEvent.click(await screen.findByRole('button', { name: '导入为任务' }));
  await screen.findByRole('status');
  expect(api.importAgentProject).toHaveBeenCalledTimes(1);
  expect(api.importAgentProject.mock.calls[0][0].task.paperIds).toEqual(['A', 'B']);
  expect(onImported).toHaveBeenCalledWith({ id: 'new-task' });
  expect(JSON.parse(localStorage.getItem('pixiu-agent-workspace'))).toEqual(local);
});
it('keeps a changed-version conflict visible without adopting an old task over current edits', async () => {
  const api = { listLegacyAgentProjects: async () => ({ status: 'success', projects: [{ projectId: 'p' }] }),
    exportLegacyAgentProject: async () => ({ snapshot: { project: { projectId: 'p' } } }),
    importAgentProject: async () => ({ status: 'conflicted', task: { id: 'existing' }, message: '新版本已备份，现有任务未覆盖' }) };
  const onImported = vi.fn(); render(<LegacyAgentMigration api={api} onImported={onImported} />);
  fireEvent.click(screen.getByRole('button', { name: '导入旧研究项目' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '核对项目' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '核对项目' })); fireEvent.click(await screen.findByRole('button', { name: '导入为任务' }));
  expect(await screen.findByRole('status')).toHaveTextContent('新版本已备份'); expect(onImported).not.toHaveBeenCalled();
});
