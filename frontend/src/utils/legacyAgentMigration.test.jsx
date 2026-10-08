import { describe, it, expect } from 'vitest';
import { browserProjectSnapshot, prepareAgentMigration } from './legacyAgentMigration';

describe('legacy agent import', () => {
  it('preserves both snapshots and differing reports without inventing unknown conversation provenance', () => {
    const server = { project: { projectId: 'p', title: '项目', paperIds: ['A'], goal: '原始目标' },
      runs: [{ runId: 'r', focusedPaperIds: ['A'], status: 'queued', prompt: '旧问题' }],
      researchTasks: [{ taskId: 't', paperIds: ['A'] }], messages: [
        { messageId: 'known', role: 'assistant', taskId: 't', content: '有来源', sourceIds: ['s'] },
        { messageId: 'unknown', role: 'user', taskId: 'untracked', content: '未知范围' }],
      artifacts: [{ runId: 'r', draftReport: '服务端完整正文', reportSources: [{ sourceId: 's', pdfId: 'A', text: '原片段' }] }],
      planReviews: [{ runId: 'r', reviewNotes: '原审核' }], timeline: [{ runId: 'r', message: '原事件' }] };
    const browser = { project: { projectId: 'p', paperIds: ['B'] }, legacyTasks: [
      { taskId: 'r', status: 'failed', draftReport: '浏览器尚未同步正文', reportSources: [{ sourceId: 's2', pdfId: 'B' }] }], messages: [] };
    const original = JSON.stringify({ server, browser });
    const prepared = prepareAgentMigration(server, browser);
    expect(prepared.task.paperIds).toEqual(['A', 'B']);
    expect(prepared.task.artifacts.map(item => item.text)).toContain('浏览器尚未同步正文');
    expect(prepared.task.artifacts[0].text).toBe('服务端完整正文');
    expect(prepared.task.messages[0].rag_sources[0].text).toBe('原片段');
    expect(prepared.task.messages[1].context).toBeUndefined();
    expect(prepared.task.activeActivity).toBeNull();
    expect(prepared.task.researchRuns).toBeUndefined();
    expect(prepared.snapshot.serverSnapshot).toEqual(server);
    expect(prepareAgentMigration(server, browser)).toEqual(prepared);
    expect(JSON.stringify({ server, browser })).toBe(original);
  });
  it('only copies one browser project, includes current/latest records and keeps the old workspace intact', () => {
    const workspace = { projects: [{ projectId: 'A' }, { projectId: 'B' }], tasksByProjectId: { A: [{ taskId: 't', projectId: 'A' }] },
      currentTask: { taskId: 'u', projectId: 'A', draftReport: '新草稿' }, latestTask: { taskId: 'wrong', projectId: 'B' },
      researchTasksByProjectId: { A: [{ taskId: 'rt', projectId: 'A' }] },
      messagesByTaskId: { t: [{ content: '本项目' }], wrong: [{ content: '其他项目' }] } };
    const original = JSON.stringify(workspace);
    const snapshot = browserProjectSnapshot(workspace, 'A');
    expect(snapshot.legacyTasks).toHaveLength(2);
    expect(snapshot.messages).toEqual([{ content: '本项目' }]);
    expect(browserProjectSnapshot(workspace, 'missing')).toBeNull();
    expect(JSON.stringify(workspace)).toBe(original);
  });
});
