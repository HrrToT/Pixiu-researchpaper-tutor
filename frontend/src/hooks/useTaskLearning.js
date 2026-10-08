import { useEffect, useRef, useState } from 'react';
import { taskWorkspaceApi } from '../services/taskWorkspaceApi';
import { useTaskOperations } from './useTaskOperations';

export function useTaskLearning(workspace, api = taskWorkspaceApi) {
  const operations = useTaskOperations(workspace, api);
  const [inputModes, setInputModes] = useState({});
  const handledDetours = useRef(new Set());
  const activityKey = task => `${task.id}:${task.activeActivity?.activityId || ''}`;
  const activeTask = workspace.tasks?.find(task => task.id === workspace.activeTaskId);
  const currentKey = activeTask ? activityKey(activeTask) : '';
  const concepts = activeTask?.activeActivity?.concepts || [];
  const completionSuggested = concepts.length > 0 && concepts.every(concept => concept.status === 'demonstrated');
  const inputMode = completionSuggested ? 'ask' : inputModes[currentKey] || 'answer';
  const setInputMode = mode => setInputModes(previous => ({ ...previous, [currentKey]: mode }));
  useEffect(() => {
    for (const record of Object.values(operations.records)) {
      if (record.kind !== 'learning.action' || record.status !== 'succeeded'
          || record.request?.action !== 'ask' || handledDetours.current.has(record.requestId)) continue;
      handledDetours.current.add(record.requestId);
      const key = `${record.taskId}:${record.request.activityId}`;
      setInputModes(previous => ({ ...previous, [key]: 'answer' }));
    }
  }, [operations.records]);
  const start = (task, pdfId, mode, goal) => {
    setInputModes(previous => ({ ...previous, [activityKey(task)]: 'answer' }));
    return operations.start(task, 'learning.start', { pdfId, mode, goal: goal || '理解论文的关键问题、方法和证据', expectedTaskRevision: task.revision });
  };
  const act = (task, action, text = '') => {
    if (action === 'resume' || action === 'retry') setInputModes(previous => ({ ...previous, [activityKey(task)]: 'answer' }));
    return operations.start(task, 'learning.action', { activityId: task.activeActivity.activityId,
      expectedRevision: task.activeActivity.revision, expectedTaskRevision: task.revision, action, text });
  };
  return { start, act, refresh: operations.refresh, cancel: operations.cancel,
    busyTasks: operations.busyTasks, error: operations.error, inputMode, setInputMode, completionSuggested, operations };
}
