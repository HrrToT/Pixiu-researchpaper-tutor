import { identifyLegacyDocuments } from '../services/taskWorkspaceStore';
const array = value => Array.isArray(value) ? value : [];
const nonempty = value => typeof value === 'string' && value.trim().length > 0;
const unique = values => [...new Set(values.filter(nonempty))];
const exactUnion = values => [...new Map(values.map(value => [JSON.stringify(value), value])).values()];
const sourceIdentity = source => ({ ...source, pdfId: source.pdfId || source.sourcePdfId || source.metadata?.id });

export function browserProjectSnapshot(workspace, projectId) {
  if (!workspace) return null;
  const project = array(workspace.projects).find(item => item.projectId === projectId)
    || (workspace.activeProject?.projectId === projectId ? workspace.activeProject : null);
  if (!project) return null;
  const researchTasks = array(workspace.researchTasksByProjectId?.[projectId]);
  const legacyTasks = exactUnion([...array(workspace.tasksByProjectId?.[projectId]),
    ...[workspace.currentTask, workspace.latestTask].filter(item => item?.projectId === projectId)]);
  const taskIds = new Set([...researchTasks, ...legacyTasks].map(item => item.taskId));
  const activeWorkspace = workspace.activeWorkspace?.project?.projectId === projectId ? workspace.activeWorkspace : null;
  return { project, researchTasks, legacyTasks, activeWorkspace,
    messages: exactUnion([...researchTasks.flatMap(task => array(workspace.messagesByTaskId?.[task.taskId])),
      ...legacyTasks.flatMap(task => array(workspace.messagesByTaskId?.[task.taskId])),
      ...array(activeWorkspace?.messages).filter(message => taskIds.has(message.taskId))]) };
}

export function prepareAgentMigration(server, browser) {
  const project = server?.project || browser?.project;
  if (!project?.projectId) throw new Error('旧项目缺少标识，原记录保留');
  if (server && browser && server.project.projectId !== browser.project.projectId) throw new Error('项目快照不一致');
  const provisionalId = `legacy-agent:${project.projectId}`;
  const paperIds = unique([...array(server?.project?.paperIds), ...array(browser?.project?.paperIds)]);
  const runs = [...array(server?.runs), ...array(browser?.legacyTasks)];
  const researchTasks = [...array(server?.researchTasks), ...array(browser?.researchTasks)];
  const sources = exactUnion([...array(server?.artifacts).flatMap(item => [...array(item.reportSources), ...array(item.evidenceItems)]),
    ...runs.flatMap(item => [...array(item.reportSources), ...array(item.evidenceItems)])]);
  const reportItems = [...array(server?.artifacts), ...runs,
    ...(browser?.activeWorkspace?.latestArtifacts ? [browser.activeWorkspace.latestArtifacts] : [])];
  const artifacts = exactUnion(reportItems.filter(item => nonempty(item.draftReport)).map(item => ({
    title: item.title || '旧研究成果', text: item.draftReport,
    paperIds: unique([...array(item.focusedPaperIds), ...array(item.paperIds),
      ...array(item.reportSources).map(source => source.pdfId || source.sourcePdfId || source.metadata?.id)]),
    sources: (array(item.reportSources).length ? item.reportSources : array(item.evidenceItems)).map(sourceIdentity),
    legacyRunId: item.runId || item.taskId, legacyRecord: item,
  })));
  const messages = exactUnion([...array(server?.messages), ...array(browser?.messages)]).map(message => {
    const run = runs.find(item => (item.runId || item.taskId) === message.runId);
    const researchTask = researchTasks.find(item => item.taskId === message.taskId);
    const scope = unique(message.context?.allowedPaperIds || researchTask?.paperIds || run?.focusedPaperIds || []);
    const associatedSources = sources.filter(source => array(message.sourceIds).includes(source.sourceId));
    return { ...message, role: message.role === 'assistant' ? 'ai' : message.role,
      legacyContext: message.context, context: scope.length ? { taskId: provisionalId, allowedPaperIds: scope,
        primaryPaperId: scope[0], strictScope: true } : undefined,
      rag_sources: associatedSources.map(sourceIdentity), legacyScopeUnknown: !scope.length };
  });
  const notes = nonempty(project.goal) || nonempty(project.defaultConstraints) ? [{
    title: '项目目标与约束', content: [project.goal, project.defaultConstraints].filter(nonempty).join('\n\n'), paperIds,
  }] : [];
  if (runs.length || researchTasks.length) {
    artifacts.push({ title: '旧研究记录', text: [...researchTasks, ...runs].map(item =>
      `- ${item.title || item.prompt || item.taskId || item.runId || '研究记录'} · ${item.status || '未记录状态'}`).join('\n'),
      paperIds: [], legacyRecords: { runs, researchTasks, timeline: server?.timeline || [],
        planReviews: server?.planReviews || [], finalReviews: server?.finalReviews || [], debates: server?.debates || [] } });
  }
  const task = identifyLegacyDocuments({ id: provisionalId, title: project.title || '旧研究项目', paperIds, messages,
    notes, artifacts, focusedPaperId: paperIds[0] || null, activeActivity: null, activityHistory: [] });
  const snapshot = { snapshotVersion: 1, project, serverSnapshot: server || null, browserSnapshot: browser || null };
  return { snapshot, task, counts: { papers: paperIds.length, messages: messages.length,
    reports: artifacts.filter(item => item.title !== '旧研究记录').length, runs: unique(runs.map(item => item.runId || item.taskId)).length, researchTasks: unique(researchTasks.map(item => item.taskId)).length,
    sources: sources.length } };
}
