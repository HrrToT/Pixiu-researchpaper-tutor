import { useEffect, useRef, useState } from 'react';
import { taskResearchApi } from '../services/taskResearchApi';

const terminal = new Set(['succeeded', 'failed', 'cancelled']);
export function useTaskResearch(workspace, api = taskResearchApi, operations = null) {
  const [runs, setRuns] = useState({});
  const [errors, setErrors] = useState({});
  const setRunError = (key, channel, message) => setErrors(previous => ({
    ...previous, [key]: { ...previous[key], [channel]: message },
  }));
  const visibleTaskId = workspace.activeTaskId || workspace.tasks[0]?.id;
  const error = Object.entries(errors).filter(([key]) => {
    try { return JSON.parse(key)[0] === visibleTaskId; }
    catch { return false; } // Ignore old transient keys retained by development hot reload.
  })
    .map(([, value]) => value.action || value.poll).find(Boolean) || '';
  const [starting, setStarting] = useState(false);
  const latest = useRef(workspace);
  latest.current = workspace;
  const startingRef = useRef(false);
  const runKey = JSON.stringify(workspace.tasks.flatMap((task) => (task.researchRuns || []).map((run) => [task.id, run.researchId])));
  const publish = async (taskId, researchId, result) => {
    const research = result?.task;
    if (!research || research.taskId !== researchId) throw new Error('研究服务返回的任务不匹配');
    const key = `${taskId}/${researchId}`;
    setRuns((previous) => ({ ...previous, [key]: research }));
    if (result.workspace) {
      if (result.workspace.id !== taskId) throw new Error('研究成果返回的任务不匹配');
      await latest.current.adoptServerTask(result.workspace);
    } else if (research.status === 'succeeded') {
      throw new Error('研究已完成，成果保存尚未确认，请重新查询');
    }
    return research;
  };
  useEffect(() => {
    let disposed = false;
    let timer;
    const finished = new Set();
    const poll = async () => {
      for (const [taskId, researchId] of JSON.parse(runKey)) {
        if (disposed || finished.has(`${taskId}/${researchId}`)) continue;
        try {
          const response = await api.get(taskId, researchId);
          if (disposed) return;
          const research = await publish(taskId, researchId, response);
          if (!disposed) setRunError(JSON.stringify([taskId, researchId]), 'poll', '');
          if (research.status === 'succeeded') finished.add(`${taskId}/${researchId}`);
        } catch (failure) { if (!disposed) setRunError(JSON.stringify([taskId, researchId]), 'poll', failure.message || '研究状态读取失败'); }
      }
      if (!disposed) timer = setTimeout(poll, 4000);
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [runKey, api]);
  const start = async (task, question, context) => {
    if (operations) return operations.start(task, 'research.start', { question, allowedPaperIds: context.allowedPaperIds,
      pdfId: context.primaryPaperId || task.focusedPaperId || context.allowedPaperIds[0],
      expectedTaskRevision: task.revision, allowExternalSearch: false, allowWebSearch: false });
    if (startingRef.current) return;
    startingRef.current = true; setStarting(true); setRunError(JSON.stringify([task.id, '$start']), 'action', '');
    try {
      const response = await api.start(task.id, { question, allowedPaperIds: context.allowedPaperIds,
        pdfId: context.primaryPaperId || task.focusedPaperId || context.allowedPaperIds[0],
        expectedTaskRevision: task.revision, allowExternalSearch: false, allowWebSearch: false });
      await latest.current.adoptServerTask(response.task);
      await publish(task.id, response.result.task.taskId, response.result);
    } catch (failure) { setRunError(JSON.stringify([task.id, '$start']), 'action', failure.message || '研究创建失败'); }
    finally { startingRef.current = false; setStarting(false); }
  };
  const action = async (taskId, researchId, name, payload) => {
    setRunError(JSON.stringify([taskId, researchId]), 'action', '');
    try { await publish(taskId, researchId, await api.action(taskId, researchId, name, payload)); }
    catch (failure) { setRunError(JSON.stringify([taskId, researchId]), 'action', failure.message || '研究操作失败'); }
  };
  return { runs, start, action, starting, error };
}
