import { useEffect, useRef, useState } from 'react';
import { taskResearchApi } from '../services/taskResearchApi';

const terminal = new Set(['succeeded', 'completed', 'failed', 'cancelled']);
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
  const finished = useRef(new Set());
  const actionVersions = useRef(new Map());
  const pendingActions = useRef(new Set());
  const runRevisions = useRef(new Map());
  const startingRef = useRef(false);
  const runKey = JSON.stringify(workspace.tasks.flatMap((task) => (task.researchRuns || []).map((run) => [task.id, run.researchId])));
  const publish = async (taskId, researchId, result, isCurrent = () => true) => {
    if (!isCurrent()) return null;
    const research = result?.task;
    if (!research || (research.runId || research.taskId) !== researchId
      || (research.contractVersion === 2 && research.runId && research.taskId !== taskId)) throw new Error('研究服务返回的任务不匹配');
    const key = `${taskId}/${researchId}`;
    const revision = research.runRevision ?? research.revision;
    if (research.contractVersion === 2 && Number.isInteger(revision) && revision < (runRevisions.current.get(key) ?? -1)) return null;
    if (result.workspace) {
      if (result.workspace.id !== taskId) throw new Error('研究成果返回的任务不匹配');
      await latest.current.adoptServerTask(result.workspace);
    } else if (research.status === 'succeeded' || (research.status === 'completed' && research.outcome !== 'none')) {
      throw new Error('研究已完成，成果保存尚未确认，请重新查询');
    }
    if (!isCurrent()) return null;
    if (research.contractVersion === 2 && Number.isInteger(revision)) runRevisions.current.set(key, revision);
    setRuns((previous) => ({ ...previous, [key]: research }));
    if (terminal.has(research.status)) finished.current.add(key);
    else finished.current.delete(key);
    return research;
  };
  useEffect(() => {
    let disposed = false;
    let timer;
    const poll = async () => {
      for (const [taskId, researchId] of JSON.parse(runKey)) {
        const key = `${taskId}/${researchId}`;
        if (disposed || finished.current.has(key) || pendingActions.current.has(key)) continue;
        const version = actionVersions.current.get(key) || 0;
        const isCurrent = () => !disposed && !pendingActions.current.has(key)
          && (actionVersions.current.get(key) || 0) === version;
        try {
          const response = await api.get(taskId, researchId);
          if (!isCurrent()) continue;
          await publish(taskId, researchId, response, isCurrent);
          if (isCurrent()) setRunError(JSON.stringify([taskId, researchId]), 'poll', '');
        } catch (failure) { if (isCurrent()) setRunError(JSON.stringify([taskId, researchId]), 'poll', failure.message || '研究状态读取失败'); }
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
    // An explicit action may reopen a finished run or have an uncertain result.
    // Resume GET recovery; never resubmit the action automatically.
    const key = `${taskId}/${researchId}`;
    const version = (actionVersions.current.get(key) || 0) + 1;
    actionVersions.current.set(key, version);
    pendingActions.current.add(key);
    finished.current.delete(key);
    const isCurrent = () => actionVersions.current.get(key) === version;
    setRunError(JSON.stringify([taskId, researchId]), 'action', '');
    try { await publish(taskId, researchId, await api.action(taskId, researchId, name, payload), isCurrent); }
    catch (failure) {
      if (isCurrent()) setRunError(JSON.stringify([taskId, researchId]), 'action', failure.message || '研究操作失败');
      if (payload?.expectedRunRevision !== undefined) throw failure;
    }
    finally { if (isCurrent()) pendingActions.current.delete(key); }
  };
  const refresh = async (taskId, researchId) => {
    const key = `${taskId}/${researchId}`;
    const version = actionVersions.current.get(key) || 0;
    const isCurrent = () => !pendingActions.current.has(key) && (actionVersions.current.get(key) || 0) === version;
    try {
      await publish(taskId, researchId, await api.get(taskId, researchId), isCurrent);
      if (isCurrent()) setRunError(JSON.stringify([taskId, researchId]), 'poll', '');
    } catch (failure) { if (isCurrent()) setRunError(JSON.stringify([taskId, researchId]), 'poll', failure.message || '研究状态读取失败'); }
  };
  return { runs, start, action, refresh, starting, error, errors };
}
