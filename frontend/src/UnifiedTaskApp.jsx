import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import TaskRename from './components/TaskRename';
import useCompactLayout from './hooks/useCompactLayout';
import PaperPageNavigation from './components/PaperPageNavigation';
import { selectionNote } from './utils/selectionNote';
import { BookOpen, ChevronLeft, ChevronRight, FileDown, FilePlus2, Languages, MessageSquare, PanelLeftClose, PanelLeftOpen, Save, SunMoon, Upload } from 'lucide-react';
import ChatPanel from './components/ChatPanel';
import MarkdownContent from './components/MarkdownContent';
import PdfViewer from './components/PdfViewer';
import TaskNavigation from './components/TaskNavigation';
import DocumentVersionHistory from './components/DocumentVersionHistory';
import DocumentOrganizer from './components/DocumentOrganizer';
import CollapsedSources from './components/CollapsedSources';
import { documentSources } from './utils/documentSources';
import { documentMarkdownExport } from './utils/documentExport';
import { learningActivityHistory } from './utils/learningActivityHistory';
import { reviseDocument, documentText } from './utils/documentVersions';
import TaskDraftRecovery from './components/TaskDraftRecovery';
import TranslationPanel from './components/TranslationPanel';
import { useTaskWorkspace } from './hooks/useTaskWorkspace';
import { useTaskLearning } from './hooks/useTaskLearning';
import { useTaskResearch } from './hooks/useTaskResearch';
import ConversationResearch from './components/ConversationResearch';
import { sanitizeResearchReport } from './components/deepResearchPanelModel';
import ConversationExecution from './components/ConversationExecution';
import { useThemePreference } from './hooks/useThemePreference';
import { apiService } from './services/api';
import { initDB } from './services/localDb';
import { persistTranslationState } from './services/workspaceSession';
import { taskWorkspaceApi } from './services/taskWorkspaceApi';
import { loadTaskMaterial } from './services/taskMaterialCache';
import { taskWorkspaceRemoteStore } from './services/taskWorkspaceRemoteStore';
import { buildPaperOutlineModel } from './utils/appHelpers';
import { resolveConversationIntent, startsNewCapability } from './utils/conversationSkills';
import { resolveTaskContext } from './utils/taskWorkspaceModel';
import { resolveNamedTaskPapers } from './utils/namedTaskPapers';
import { createEmptyTranslationState, normalizeTranslationState } from './utils/translationState';
import { usePageTranslation } from './hooks/usePageTranslation';
import './UnifiedTaskApp.css';

const LAYOUT_KEY = 'pixiu-unified-layout-v1';
const COMPACT_PANE_KEY = 'pixiu-compact-pane-v1';
const DEFAULT_LAYOUT = { mode: 'split', navigation: true, reader: true, chat: true, navWidth: 258, readerPercent: 54 };
const initialLayout = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}');
    const merged = { ...DEFAULT_LAYOUT, ...saved };
    merged.reader = Boolean(merged.reader);
    merged.chat = Boolean(merged.chat);
    if (!merged.reader && !merged.chat) merged.reader = true;
    merged.readerPercent = Number.isFinite(Number(merged.readerPercent)) ? Math.max(32, Math.min(72, Number(merged.readerPercent))) : DEFAULT_LAYOUT.readerPercent;
    merged.navWidth = Number.isFinite(Number(merged.navWidth)) ? Math.max(180, Math.min(380, Number(merged.navWidth))) : DEFAULT_LAYOUT.navWidth;
    return merged;
  } catch { return DEFAULT_LAYOUT; }
};
const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const createMessage = (role, content, extra = {}) => ({ id: makeId(), role, content, timestamp: Date.now(), ...extra });
const getPaperTitle = (papers, id) => papers.find((paper) => paper.id === id)?.title || papers.find((paper) => paper.id === id)?.filename || id;
const normalizeNoteContent = (note) => `${note?.text ?? note?.content ?? note?.body ?? ''}`;
const documentDraftKey = (selection) => `pixiu-document-draft:${JSON.stringify([selection.taskId, selection.collection, selection.id ?? selection.index])}`;
const readingPositionKey = (taskId, paperId) => `pixiu-reading-position:${JSON.stringify([taskId, paperId])}`;
export default function UnifiedTaskApp() {
  const workspace = useTaskWorkspace();
  const learning = useTaskLearning(workspace);
  const research = useTaskResearch(workspace, undefined, learning.operations);
  const { tasks, activeTask, activeTaskId, createTask, updateTask, selectTask } = workspace;
  const savedLearningActivities = learningActivityHistory(activeTask);
  const { theme, toggleTheme } = useThemePreference('pixiu-theme');
  const [layout, setLayout] = useState(initialLayout);
  const compact = useCompactLayout();
  const [compactPane, setCompactPane] = useState(() => {
    try { return localStorage.getItem(COMPACT_PANE_KEY) === 'reader' ? 'reader' : 'chat'; }
    catch { return 'chat'; }
  });
  const [compactNavigation, setCompactNavigation] = useState(false);
  const compactNavigationButton = useRef(null);
  const compactReaderButton = useRef(null);
  const navigationRef = useRef(null);
  const resizeCleanup = useRef(null);
  useEffect(() => () => resizeCleanup.current?.(), []);
  useEffect(() => {
    if (compact && compactNavigation) navigationRef.current?.querySelector('select, button')?.focus();
  }, [compact, compactNavigation]);
  useEffect(() => {
    if (!compact) { setCompactNavigation(false); return; }
    try { localStorage.setItem(COMPACT_PANE_KEY, compactPane); } catch { /* Layout preference is optional. */ }
  }, [compact, compactPane]);
  const [papers, setPapers] = useState([]);
  const [libraryError, setLibraryError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [processingRefresh, setProcessingRefresh] = useState(0);
  const [processingRequest, setProcessingRequest] = useState(false);
  const [paperView, setPaperView] = useState({ id: null, url: null, deconstruct: null, highlights: [], error: '' });
  const [page, setPage] = useState({ pageIndex: 0, totalPages: 0 });
  const [jump, setJump] = useState({ pageIndex: 0, token: 0, anchorId: null });
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [movingDocument, setMovingDocument] = useState(false);
  const [requestedDocument, setRequestedDocument] = useState(null);
  const [recoveryPreview, setRecoveryPreview] = useState(null);
  const [savingRecovery, setSavingRecovery] = useState(false);
  const activeTaskIdRef = useRef(activeTaskId);
  activeTaskIdRef.current = activeTaskId;
  const [documentDraft, setDocumentDraft] = useState('');
  const [restoringDocument, setRestoringDocument] = useState(false);
  const [documentEditing, setDocumentEditing] = useState(false);
  const [savingDocument, setSavingDocument] = useState(false);
  const selectedDocumentRef = useRef(null);
  selectedDocumentRef.current = selectedDocument;
  const [localError, setLocalError] = useState('');
  const [intentChoice, setIntentChoice] = useState(null);
  const [showOutline, setShowOutline] = useState(false);
  const [translationMode, setTranslationMode] = useState('original');
  const [translationState, setTranslationState] = useState(createEmptyTranslationState());
  const [translationReadyKey, setTranslationReadyKey] = useState('');
  const currentPageTextRef = useRef({ pageIndex: 0, pageText: '', pageLayout: null });
  const fileInputRef = useRef(null);
  const taskRef = useRef(new Map());
  const paperLoadToken = useRef(0);
  const materialProcessingRef = useRef(new Map());
  const focusedPaperId = activeTask?.focusedPaperId || null;
  const translationKey = JSON.stringify([activeTaskId, focusedPaperId]);
  const translationReady = translationReadyKey === translationKey;
  const initialPaperPage = useMemo(() => {
    try {
      const stored = Number(localStorage.getItem(readingPositionKey(activeTaskId, focusedPaperId)));
      return Number.isInteger(stored) && stored >= 0 ? stored : 0;
    } catch { return 0; }
  }, [activeTaskId, focusedPaperId]);
  const setReadingPage = useCallback(next => {
    setPage(next);
    if (activeTaskId && focusedPaperId) {
      try { localStorage.setItem(readingPositionKey(activeTaskId, focusedPaperId), String(next.pageIndex)); }
      catch { /* Reading position is an optional local preference. */ }
    }
  }, [activeTaskId, focusedPaperId]);
  const materialKey = JSON.stringify([activeTaskId, activeTask?.paperIds || []]);

  useEffect(() => {
    if (!activeTaskId || !taskWorkspaceApi.getMaterialProcessing) return;
    let disposed = false;
    let timer;
    const poll = async () => {
      try {
        const ids = activeTask?.paperIds || [];
        const results = await Promise.allSettled(ids.map(id => taskWorkspaceApi.getMaterialProcessing(activeTaskId, id)));
        if (disposed) return;
        let pending = false;
        let retryDelay = 2500;
        const db = await initDB();
        for (const result of results) {
          if (result.status !== 'fulfilled') {
            // Missing legacy files cannot become available through polling.
            // Retry only transient failures, leaving an explicit refresh as
            // the recovery path after restoring a file.
            if ([400, 404].includes(result.reason?.response?.status)) continue;
            pending = true;
            if (result.reason?.response?.status === 429) retryDelay = Math.max(retryDelay, 15000,
              Number(result.reason.response.data?.retryAfter || 0) * 1000);
            continue;
          }
          const status = result.value;
          if (!ids.includes(status?.pdfId)) continue;
          materialProcessingRef.current.set(status.pdfId, status);
          pending ||= ['queued', 'parsing'].includes(status.processingStatus) || status.aiAnalysisStatus === 'running';
          await db.put('deconstructStore', status, status.pdfId);
          if (disposed) return;
          setPapers(current => current.map(paper => paper.id === status.pdfId ? { ...paper, ...status, id: paper.id } : paper));
          setPaperView(current => current.id === status.pdfId ? { ...current, deconstruct: status } : current);
        }
        if (pending && !disposed) timer = setTimeout(poll, retryDelay);
      } catch { if (!disposed) timer = setTimeout(poll, 5000); }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [materialKey, processingRefresh]);

  const requestMaterialProcessing = async (overview) => {
    if (!activeTaskId || !focusedPaperId || processingRequest) return;
    setProcessingRequest(true);
    try {
      if (overview) await taskWorkspaceApi.generateMaterialOverview(activeTaskId, focusedPaperId);
      else await taskWorkspaceApi.retryMaterialParse(activeTaskId, focusedPaperId);
      setProcessingRefresh(value => value + 1);
    } catch (error) { setLocalError(error.response?.data?.message || error.message || '处理请求失败'); }
    finally { setProcessingRequest(false); }
  };

  const { requestPageTranslation, handlePdfPageChange, handlePageTextExtracted, handleRetryTranslation } = usePageTranslation({
    apiService,
    pdfId: focusedPaperId,
    deconstructData: paperView.deconstruct,
    translationState,
    commitTranslationState: setTranslationState,
    setPdfPageState: setReadingPage,
    pdfPageState: page,
    isTranslated: translationReady && translationMode !== 'original',
    currentPageTextRef,
  });
  useEffect(() => {
    if (!translationReady || translationMode === 'original' || !focusedPaperId || paperView.id !== focusedPaperId) return;
    const source = currentPageTextRef.current;
    if (!source.pageText || source.pageIndex !== page.pageIndex) return;
    const status = translationState.pages?.[page.pageIndex]?.status;
    if (['success', 'translating', 'error', 'empty'].includes(status)) return;
    void requestPageTranslation(source);
  }, [translationReady, translationMode, focusedPaperId, paperView.id, page.pageIndex, translationState.pages, requestPageTranslation]);

  useEffect(() => { taskRef.current = new Map(tasks.map((task) => [task.id, task])); }, [tasks]);
  useEffect(() => { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); }, [layout]);
  useEffect(() => { setSelectedDocument(null); setRecoveryPreview(null); setDocumentDraft(''); setLocalError(''); }, [activeTaskId]);
  useEffect(() => {
    if (!requestedDocument || requestedDocument.taskId !== activeTaskId) return;
    const item = activeTask?.artifacts?.find(document => (document.id || document.artifactId) === requestedDocument.id);
    if (!item) { setLocalError('成果已再次移动，请刷新任务列表'); setRequestedDocument(null); return; }
    let draft = null;
    const selection = { taskId: activeTaskId, collection: 'artifacts', id: requestedDocument.id, baseText: normalizeNoteContent(item) };
    try {
      const key = documentDraftKey(selection);
      draft = localStorage.getItem(key);
      if (draft !== null) selection.baseText = JSON.parse(localStorage.getItem(key + ':base') || 'null');
    } catch { setLocalError('本地编辑草稿暂不可用'); }
    setSelectedDocument(selection); setDocumentDraft(draft ?? normalizeNoteContent(item));
    setRequestedDocument(null); patchLayout({ reader: true });
  }, [activeTaskId, activeTask, requestedDocument]);
  useEffect(() => {
    let alive = true;
    initDB().then((db) => db.getAll('libraryStore')).then((records) => {
      if (alive) setPapers(records.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)));
    }).catch((error) => { if (alive) setLibraryError(error.message || '论文资料读取失败'); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let disposed = false;
    const [taskId] = JSON.parse(materialKey);
    if (taskId) taskWorkspaceApi.listMaterials(taskId).then(items => {
      if (disposed) return;
      setLibraryError('');
      setPapers(current => {
        const known = new Map(current.map(item => [item.id, item]));
        for (const item of items) known.set(item.id, { ...item, ...known.get(item.id), fileAvailable: item.fileAvailable });
        return [...known.values()];
      });
    }).catch(error => { if (!disposed) setLibraryError(error.message || '任务论文读取失败'); });
    return () => { disposed = true; };
  }, [materialKey]);

  useEffect(() => {
    let alive = true;
    currentPageTextRef.current = { pageIndex: 0, pageText: '', pageLayout: null };
    setPage({ pageIndex: initialPaperPage, totalPages: 0 });
    setTranslationMode('original');
    setTranslationReadyKey('');
    setTranslationState(createEmptyTranslationState(focusedPaperId));
    if (focusedPaperId) initDB().then((db) => db.get('translationStore', focusedPaperId)).then((stored) => {
      if (!alive) return;
      const restored = normalizeTranslationState(stored, focusedPaperId);
      setTranslationState(current => ({...restored, pages:{
        ...(current.pdfId === focusedPaperId ? current.pages : {}), ...restored.pages,
      }}));
      setTranslationReadyKey(translationKey);
    }).catch(() => { if (alive) setLocalError('译文缓存读取失败，请刷新后重试。'); });
    return () => { alive = false; };
  }, [focusedPaperId, activeTaskId, initialPaperPage]);
  useEffect(() => {
    if (!translationReady || !focusedPaperId || translationState.pdfId !== focusedPaperId) return;
    const timer = setTimeout(() => {
      initDB().then((db) => persistTranslationState(db, focusedPaperId, translationState)).catch((error) => setLocalError(error.message || '译文缓存保存失败'));
    }, 300);
    return () => clearTimeout(timer);
  }, [translationReady, focusedPaperId, translationState]);
  useEffect(() => {
    const token = ++paperLoadToken.current;
    let objectUrl = null;
    if (!focusedPaperId) { setPaperView({ id: null, url: null, deconstruct: null, highlights: [], error: '' }); return undefined; }
    setPaperView({ id: focusedPaperId, url: null, deconstruct: null, highlights: [], error: '' });
    initDB().then(async (db) => {
      const { record, deconstruct, highlights, cacheWarning } = await loadTaskMaterial(db, taskWorkspaceApi, activeTaskId, focusedPaperId);
      if (cacheWarning && token === paperLoadToken.current) setLocalError(cacheWarning);
      objectUrl = URL.createObjectURL(record.blob);
      if (token === paperLoadToken.current) setPaperView({ id: focusedPaperId, url: objectUrl, deconstruct: materialProcessingRef.current.get(focusedPaperId) || deconstruct, highlights: Array.isArray(highlights) ? highlights : [], error: '' });
      else URL.revokeObjectURL(objectUrl);
    }).catch((error) => { if (token === paperLoadToken.current) setPaperView({ id: focusedPaperId, url: null, deconstruct: null, highlights: [],
      error: error.response?.status === 404 ? '这篇论文暂不可读取，请检查任务材料或从原客户端恢复文件。原笔记与成果仍保留。'
        : error.response?.data?.message || error.message || '论文读取失败' }); });
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [focusedPaperId, activeTaskId]);

  const patchLayout = (patch) => {
    if (patch.reader === true) { setCompactPane('reader'); setCompactNavigation(false); compactReaderButton.current?.focus(); }
    setLayout((current) => {
      const next = { ...current, ...patch };
      if (!next.reader && !next.chat) next.reader = true;
      return next;
    });
  };
  const setMode = (mode) => patchLayout(mode === 'reader'
    ? { mode, reader: true, chat: false }
    : mode === 'chat' ? { mode, reader: false, chat: true } : { mode: 'split', reader: true, chat: true });
  const openPaper = useCallback(async (paperId, taskId = activeTaskId) => {
    const task = taskRef.current.get(taskId);
    if (!task?.paperIds.includes(paperId)) throw new Error('这篇论文不属于当前任务');
    setSelectedDocument(null);
    setRecoveryPreview(null);
    patchLayout({ reader: true });
    await updateTask(taskId, { focusedPaperId: paperId });
  }, [activeTaskId, updateTask]);
  const addPaper = async (paperId) => {
    if (!activeTaskId) return;
    await updateTask(activeTaskId, (task) => ({ paperIds: [...new Set([...task.paperIds, paperId])], focusedPaperId: task.focusedPaperId || paperId }));
  };
  const removePaper = async (paperId) => {
    if (!activeTaskId) return;
    await updateTask(activeTaskId, (task) => {
      const paperIds = task.paperIds.filter((id) => id !== paperId);
      return { paperIds, focusedPaperId: task.focusedPaperId === paperId ? paperIds[0] || null : task.focusedPaperId };
    });
  };
  const handleUpload = async (file) => {
    if (!file || uploading) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) { setLocalError('请选择 PDF 论文文件。'); return; }
    setUploading(true); setLocalError('');
    try {
      const targetTaskId = activeTaskId || (await createTask({ title: file.name.replace(/\.pdf$/i, '') })).id;
      const response = await apiService.uploadTaskMaterial(file);
      if (!response || response.status !== 'success' || !response.pdfId) throw new Error(response?.message || '论文上传失败');
      const entry = { ...response, id: response.pdfId, title: response.title || file.name, filename: file.name, authors: response.authors || [], parseStatus: response.parseStatus || '已上传', ragIndexed: response.ragIndexed === true, timestamp: Date.now(), updatedAt: Date.now() };
      const db = await initDB();
      // Reimporting a paper must not reset its legacy notes, history or highlights.
      const transaction = db.transaction(['pdfStore', 'deconstructStore', 'libraryStore'], 'readwrite');
      await Promise.all([
        transaction.objectStore('pdfStore').put(file, response.pdfId),
        transaction.objectStore('deconstructStore').put(response, response.pdfId),
        transaction.objectStore('libraryStore').put(entry),
      ]);
      await transaction.done;
      setPapers((current) => [entry, ...current.filter((paper) => paper.id !== entry.id)]);
      await updateTask(targetTaskId, (task) => ({ paperIds: [...new Set([...task.paperIds, entry.id])], focusedPaperId: entry.id }));
      if (!activeTaskIdRef.current || activeTaskIdRef.current === targetTaskId) {
        selectTask(targetTaskId); patchLayout({ reader: true });
      }
    } catch (error) { setLocalError(error?.response?.data?.message || '论文上传未完成，请重新选择文件再试；当前任务和输入草稿仍保留。'); }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ''; }
  };

  const appendMessage = (taskId, message) => updateTask(taskId, (task) => ({ messages: [...task.messages, message] }));
  const sendMessage = async (rawText, chosenSkill = null) => {
    const task = activeTask;
    if (!task || learning.busyTasks[task.id]) return false;
    const text = rawText.trim();
    if (!text) return false;
    setLocalError('');
    const intent = chosenSkill ? { skill: chosenSkill } : resolveConversationIntent(text);
    const skill = intent.skill;
    if (intent.clarification) {
      setIntentChoice({ taskId: task.id, text, ...intent.clarification });
      return false;
    }
    setIntentChoice(null);
    if (text.startsWith('/') && !skill) {
      setLocalError('未识别这个命令，可使用 /精读、/补课、/自测、/批判、/比较、/研究。');
      return false;
    }
    let explicitPaperIds;
    let initialContext;
    try {
      explicitPaperIds = resolveNamedTaskPapers(text, papers, task.paperIds);
      initialContext = resolveTaskContext(task, { text,
        ...(skill && startsNewCapability(skill.skillId) ? { activity: null } : {}),
        ...(explicitPaperIds !== undefined ? { paperIds: explicitPaperIds } : {}) });
    } catch (error) { setLocalError(error.message); return false; }
    const materialReady = (ids) => {
      const notReady = ids.filter(id => papers.find(paper => paper.id === id)?.questionReady === false);
      if (!notReady.length) return true;
      setLocalError(`以下材料正文尚未就绪：${notReady.map(id => getPaperTitle(papers, id)).join('、')}。可先阅读原文，或在论文栏重试解析。`);
      return false;
    };
    const activityPapers = task.activeActivity?.snapshot?.paperIds || task.activeActivity?.paperIds || (task.activeActivity?.pdfId ? [task.activeActivity.pdfId] : []);
    const targetsCurrentActivity = initialContext.allowedPaperIds.length > 0
      && initialContext.allowedPaperIds.every(id => activityPapers.includes(id))
      && activityPapers.every(id => initialContext.allowedPaperIds.includes(id));
    const sendText = skill ? skill.instruction : text;
    if (skill && ['read', 'quiz'].includes(skill.skillId)) {
      try {
        const explicit = explicitPaperIds;
        const pdfId = explicit?.length === 1 ? explicit[0] : !explicit ? task.focusedPaperId || (task.paperIds.length === 1 ? task.paperIds[0] : null) : null;
        if (!pdfId) throw new Error('请打开或明确指定一篇要学习的论文');
        if (!materialReady([pdfId])) return false;
        await learning.start(task, pdfId, skill.skillId, sendText);
      } catch (error) { setLocalError(error.message); return false; }
      return;
    }
    if (!skill && task.activeActivity?.status === 'active' && targetsCurrentActivity) {
      if (!materialReady(initialContext.allowedPaperIds)) return false;
      await learning.act(task, learning.inputMode, text);
      return;
    }
    if (skill?.skillId === 'background' && task.activeActivity?.status === 'active' && targetsCurrentActivity) {
      if (!materialReady(initialContext.allowedPaperIds)) return false;
      await learning.act(task, 'remediate', sendText);
      return;
    }
    if (skill?.skillId === 'research') {
      try {
        if (!sendText) throw new Error('请在 /研究 后写下要研究的问题');
        const scope = resolveTaskContext(task, { text, activity: null, paperIds: resolveNamedTaskPapers(text, papers, task.paperIds) });
        if (!scope.allowedPaperIds.length) throw new Error('请先为任务加入研究材料');
        if (!materialReady(scope.allowedPaperIds)) return false;
        await research.start(task, sendText, scope);
      } catch (error) { setLocalError(error.message); return false; }
      return;
    }
    if (skill && !sendText && !['critique', 'compare', 'background'].includes(skill.skillId)) {
      await appendMessage(task.id, createMessage('ai', `请在 /${skill.command} 后写下你想解决的问题。`, { isSystem: true }));
      return;
    }
    const requestText = skill?.skillId === 'critique' ? `分析论文的贡献、假设、实验依据和局限，并指出证据不足之处。${sendText}`
      : skill?.skillId === 'compare' ? `比较任务中相关论文的方法、实验、贡献与局限。${sendText}`
        : skill?.skillId === 'background' ? `解释理解论文所需的前置知识。${sendText}` : text;
    let context;
    try {
      const explicitPaperIds = resolveNamedTaskPapers(text, papers, task.paperIds);
      const skillPaperIds = explicitPaperIds;
      context = resolveTaskContext(task, { text: requestText,
        ...(skill && startsNewCapability(skill.skillId) ? { activity: null } : {}),
        ...(skillPaperIds !== undefined ? { paperIds: skillPaperIds } : {}) });
      if ((skill?.skillId === 'compare' || skill?.steps?.includes('compare')) && context.allowedPaperIds.length < 2) throw new Error('比较至少需要两篇论文，请先在任务中加入论文。');
      if (skill?.skillId === 'critique' && context.allowedPaperIds.length === 0) throw new Error('请先加入并打开一篇论文。');
    }
    catch (error) { setLocalError(error.message); return false; }
    if (!materialReady(context.allowedPaperIds)) return false;
    await learning.operations.start(task, 'conversation.execute', {
      capability: skill?.skillId || 'chat', message: sendText || requestText,
      ...(skill?.steps ? { steps: skill.steps } : {}),
      displayText: text, allowedPaperIds: context.allowedPaperIds,
      primaryPaperId: context.primaryPaperId, strictScope: context.strictScope,
      expectedTaskRevision: task.revision,
    });
  };
  const deleteMessage = async (index) => { if (activeTaskId) await updateTask(activeTaskId, (task) => ({ messages: task.messages.filter((_, itemIndex) => itemIndex !== index) })); };
  const saveMessage = async (index, asArtifact = false) => {
    if (!activeTaskId) return;
    const source = activeTask?.messages[index];
    if (!source) return;
    const entry = { id: makeId(), title: `${asArtifact ? '成果' : '笔记'} · ${new Date().toLocaleDateString('zh-CN')}`, text: source.content, paperIds: source.context?.allowedPaperIds || activeTask.paperIds, sources: documentSources(source), sentenceSourceMap: source.sentenceSourceMap || [], sourceMessageId: source.id, createdAt: new Date().toISOString(), versions: [] };
    await updateTask(activeTaskId, (task) => ({ [asArtifact ? 'artifacts' : 'notes']: [...task[asArtifact ? 'artifacts' : 'notes'], entry] }));
    setSelectedDocument({ taskId: activeTaskId, collection: asArtifact ? 'artifacts' : 'notes', id: entry.id, baseText: entry.text });
    setDocumentDraft(entry.text);
    patchLayout({ reader: true });
  };
  const openDocument = (item, collection = null) => {
    setRecoveryPreview(null);
    const source = collection || (activeTask?.artifacts.includes(item) ? 'artifacts' : 'notes');
    const index = activeTask?.[source]?.findIndex((candidate) => candidate === item || (item.id && candidate.id === item.id)) ?? -1;
    const selection = { taskId: activeTaskId, collection: source, index, id: item.id || item.artifactId };
    let draft = null;
    selection.baseText = normalizeNoteContent(item);
    try {
      draft = localStorage.getItem(documentDraftKey(selection));
      if (draft !== null) {
        const base = localStorage.getItem(documentDraftKey(selection) + ':base');
        selection.baseText = base === null ? null : JSON.parse(base);
      }
    }
    catch { setLocalError('本地编辑草稿暂不可用'); }
    setSelectedDocument(selection);
    setDocumentDraft(draft ?? normalizeNoteContent(item));
    patchLayout({ reader: true });
  };
  const preview = recoveryPreview?.taskId === activeTaskId ? recoveryPreview : null;
  const recoverResult = async () => {
    if (!preview || savingRecovery) return;
    const selected = preview;
    setSavingRecovery(true);
    try {
      const receipt = await learning.operations.recoverResult(selected.taskId, selected.requestId);
      const artifact = receipt.task?.artifacts?.find(item => item.sourceRequestId === selected.requestId);
      if (!artifact) throw new Error('保存状态已确认，请在任务成果列表中查看');
      if (activeTaskIdRef.current === selected.taskId) {
        setRecoveryPreview(null);
        setSelectedDocument({ taskId: selected.taskId, collection: 'artifacts', id: artifact.id, baseText: artifact.text });
        setDocumentDraft(artifact.text);
      }
    } catch (error) { setLocalError(error.response?.data?.message || error.message || '成果保存未确认，请查询原请求'); }
    finally { setSavingRecovery(false); }
  };
  const activeDocument = selectedDocument?.taskId === activeTaskId ? (selectedDocument.id
    ? activeTask?.[selectedDocument.collection]?.find((item) => (item.id || item.artifactId) === selectedDocument.id)
    : activeTask?.[selectedDocument.collection]?.[selectedDocument.index]) : null;
  const selectedDocumentKey = selectedDocument ? documentDraftKey(selectedDocument) : null;
  useEffect(() => { setDocumentEditing(false); }, [selectedDocumentKey]);
  const documentDirty = !!activeDocument && documentDraft !== normalizeNoteContent(activeDocument);
  const saveDocumentFromToolbar = async () => {
    if (savingDocument) return;
    setSavingDocument(true); setLocalError('');
    try { await saveDocument(); }
    catch (error) { setLocalError(error.response?.data?.message || error.message || '保存失败，草稿仍保留'); }
    finally { setSavingDocument(false); }
  };
  const saveDocument = async () => {
    if (!activeDocument || !selectedDocument) return;
    const { taskId, collection } = selectedDocument;
    try { await updateTask(taskId, (task) => {
      const entries = [...task[collection]];
      const index = selectedDocument.id ? entries.findIndex((item) => (item.id || item.artifactId) === selectedDocument.id) : selectedDocument.index;
      const previous = entries[index];
      if (!previous) throw new Error('文档已不存在，草稿仍保留');
      if (selectedDocument.baseText === null || normalizeNoteContent(previous) !== selectedDocument.baseText) {
        entries[index] = { ...previous, text: documentDraft };
        throw Object.assign(new Error('笔记已有新版本，草稿已保留。请核对最新正文后再保存。'),
          { code: 'DOCUMENT_CONFLICT', draftTask: { ...task, [collection]: entries } });
      }
      entries[index] = reviseDocument(previous, documentDraft);
      return { [collection]: entries };
    }); } catch (error) {
      if (error.code === 'DOCUMENT_CONFLICT') await taskWorkspaceRemoteStore.retainUnsyncedDraft(error.draftTask, 'document-conflict');
      throw error;
    }
    if (selectedDocumentRef.current && documentDraftKey(selectedDocumentRef.current) === documentDraftKey(selectedDocument)) {
      setSelectedDocument(previous => ({ ...previous, baseText: documentDraft }));
    }
    try {
      const key = documentDraftKey(selectedDocument);
      // Typing may have continued while the server save was pending.
      if (localStorage.getItem(key) === documentDraft) { localStorage.removeItem(key); localStorage.removeItem(key + ':base'); }
      else localStorage.setItem(key + ':base', JSON.stringify(documentDraft));
    } catch { setLocalError('正文已保存，本地草稿清理失败'); }
  };
  const exportDocument = () => {
    if (!activeDocument) return;
    const blob = new Blob([documentMarkdownExport(activeDocument, documentDraft, papers)], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `${activeDocument.title || '笔记'}.md`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const renameDocument = async title => {
    const selection = selectedDocument;
    await updateTask(selection.taskId, task => {
      const entries = [...task[selection.collection]];
      const index = selection.id ? entries.findIndex(item => (item.id || item.artifactId) === selection.id) : selection.index;
      if (!entries[index]) throw new Error('文档已不存在，请刷新');
      entries[index] = { ...entries[index], title };
      return { [selection.collection]: entries };
    });
  };
  const runDocumentMove = async (targetTaskId, includeMaterials, queryOnly) => {
    const selection = selectedDocument;
    const key = documentDraftKey(selection) + ':move';
    let intent = JSON.parse(localStorage.getItem(key) || 'null');
    if (!intent && queryOnly) throw new Error('此文档没有待查询的移动请求');
    if (!intent) {
      if (documentDraft !== normalizeNoteContent(activeDocument)) throw new Error('请先保存正文再移动');
      const [source, target] = await Promise.all([taskWorkspaceApi.getTask(selection.taskId), taskWorkspaceApi.getTask(targetTaskId)]);
      const latest = source[selection.collection].find(item => (item.id || item.artifactId) === selection.id);
      if (!latest || normalizeNoteContent(latest) !== selection.baseText) throw new Error('文档已有新版本，请刷新核对后移动');
      intent = { requestId: makeId(), targetTaskId, documentId: selection.id, collection: selection.collection,
        sourceRevision: source.revision, targetRevision: target.revision, includeMaterials };
      localStorage.setItem(key, JSON.stringify(intent));
    } else if (!queryOnly && (intent.targetTaskId !== targetTaskId || intent.includeMaterials !== includeMaterials)) {
      throw new Error('先查询原移动请求，确认结果后再更改目标');
    }
    let result;
    try { result = queryOnly ? await taskWorkspaceApi.getDocumentMove(selection.taskId, intent.requestId)
      : await taskWorkspaceApi.moveDocument(selection.taskId, intent); }
    catch (error) {
      if ([400, 409].includes(error.response?.status)) localStorage.removeItem(key);
      throw error;
    }
    await workspace.adoptServerTask(result.sourceTask);
    await workspace.adoptServerTask(result.targetTask);
    localStorage.removeItem(key);
    if (selectedDocumentRef.current && documentDraftKey(selectedDocumentRef.current) === documentDraftKey(selection)) {
      setSelectedDocument(null); setDocumentDraft('');
    }
  };
  const moveDocument = async (...args) => {
    setMovingDocument(true);
    try { await runDocumentMove(...args); }
    finally { setMovingDocument(false); }
  };
  const restoreDocument = async (version) => {
    if (savingDocument) throw new Error('正在保存正文，请等待保存结果');
    if (movingDocument) throw new Error('正在移动文档，请等待结果确认');
    const selection = selectedDocument;
    const text = documentText(version);
    const draft = documentDraft;
    setRestoringDocument(true);
    try { await updateTask(selection.taskId, (task) => {
      const entries = [...task[selection.collection]];
      const index = selection.id ? entries.findIndex((item) => (item.id || item.artifactId) === selection.id) : selection.index;
      if (!entries[index]) throw new Error('文档已不存在，无法恢复');
      if (selection.baseText === null || normalizeNoteContent(entries[index]) !== selection.baseText) throw new Error('笔记已有新版本，请核对后再恢复。草稿仍保留。');
      entries[index] = reviseDocument(entries[index], text, { draft, restoredFrom: version.savedAt || 'legacy' });
      return { [selection.collection]: entries };
    });
    if (selectedDocumentRef.current && documentDraftKey(selectedDocumentRef.current) === documentDraftKey(selection)) {
      setDocumentDraft(text); setSelectedDocument(previous => ({ ...previous, baseText: text }));
    }
    try {
      const key = documentDraftKey(selection);
      if (localStorage.getItem(key) === draft) { localStorage.removeItem(key); localStorage.removeItem(key + ':base'); }
      else localStorage.setItem(key + ':base', JSON.stringify(text));
    }
    catch { setLocalError('版本已恢复，本地草稿清理失败'); }
    } finally { setRestoringDocument(false); }
  };
  const jumpToSource = async (source) => {
    const targetPaperId = source?.pdfId || source?.sourcePdfId || activeTask?.focusedPaperId;
    if (!targetPaperId || !activeTask?.paperIds.includes(targetPaperId)) return false;
    setSelectedDocument(null);
    setRecoveryPreview(null);
    if (targetPaperId !== activeTask.focusedPaperId) await openPaper(targetPaperId);
    const index = Number(source.pageIndex ?? source.sourcePageIndex);
    if (Number.isInteger(index) && index >= 0) setJump({ taskId: activeTaskId, pdfId: targetPaperId, pageIndex: index, token: Date.now(), anchorId: source.sourceAnchorId || source.sectionId || null });
    patchLayout({ reader: true });
    return true;
  };
  const syncPdfSelection = (content, role, _isSync, sourceMeta) => {
    const taskId = activeTaskId;
    const pdfId = paperView.id;
    if (!taskId || !pdfId || !content?.trim()) return;
    const context = { taskId, allowedPaperIds: [pdfId], primaryPaperId: pdfId, strictScope: true };
    void appendMessage(taskId, createMessage(role === 'user' ? 'user' : 'ai', content, {
      context,
      sourceAnchorId: sourceMeta?.sourceAnchorId,
      sourcePageIndex: sourceMeta?.sourcePageIndex,
      sourceText: sourceMeta?.sourceText,
      sourcePdfId: pdfId,
    }));
  };
  const captureTranslation = async (artifact) => {
    if (!activeTaskId || !paperView.id || !artifact) return;
    const content = `${artifact.text || artifact.content || translationState.pages?.[page.pageIndex]?.translatedText || ''}`;
    if (!content.trim()) return;
    await updateTask(activeTaskId, (task) => ({ artifacts: [...task.artifacts, {
      id: makeId(), title: artifact.title || `${getPaperTitle(papers, paperView.id)} · 第 ${page.pageIndex + 1} 页译文`,
      text: content, paperIds: [paperView.id], pageIndex: page.pageIndex,
      createdAt: new Date().toISOString(), versions: [],
    }] }));
  };
  const currentTranslationPage = translationState.pages?.[page.pageIndex] || null;
  const goToPage = index => setJump({ taskId: activeTaskId, pdfId: focusedPaperId,
    pageIndex: index, token: Date.now(), anchorId: null });
  const outline = useMemo(() => buildPaperOutlineModel(paperView.deconstruct)?.items || [], [paperView.deconstruct]);
  const startResize = (event) => {
    event.preventDefault();
    const startX = event.clientX;
    const start = layout.readerPercent;
    const width = (event.currentTarget.parentElement?.clientWidth || 800) - (navigationRef.current?.offsetWidth || 0) - 6;
    const move = (moveEvent) => setLayout((current) => ({ ...current, readerPercent: Math.max(32, Math.min(72, start + (moveEvent.clientX - startX) / width * 100)) }));
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); resizeCleanup.current = null; };
    resizeCleanup.current?.(); resizeCleanup.current = stop;
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop); window.addEventListener('pointercancel', stop);
  };

  return <div className="unified-app theme-app-shell">
    <header className="unified-header theme-panel theme-border">
      <div className="unified-brand"><img src="/貔貅紫白.png" alt="" /> <strong>貔貅</strong><span>学术工作台</span></div>
      <div className="unified-title" title={activeTask?.title || ''}>{activeTask?.title || '新任务'}</div>
      <TaskDraftRecovery taskId={activeTaskId} refreshKey={workspace.error || localError} onCreateTask={createTask} />
      {activeTask && <TaskRename key={activeTaskId} task={activeTask} onRename={title => updateTask(activeTaskId, { title })} />}
      <div className="unified-layout-actions" role="group" aria-label="布局">
        <button type="button" className={layout.mode === 'split' ? 'active' : ''} onClick={() => setMode('split')}>并排</button>
        <button type="button" className={layout.mode === 'reader' ? 'active' : ''} onClick={() => setMode('reader')}>专注阅读</button>
        <button type="button" className={layout.mode === 'chat' ? 'active' : ''} onClick={() => setMode('chat')}>专注对话</button>
      </div>
      <button type="button" className="unified-header-action" onClick={toggleTheme} aria-label="切换主题"><SunMoon size={17} /></button>
    </header>
    {compact && <div className="unified-compact-switch" role="group" aria-label="内容视图">
      <button type="button" ref={compactNavigationButton} aria-expanded={compactNavigation} aria-controls="unified-navigation" onClick={() => setCompactNavigation(value => !value)}>任务与材料</button>
      <button type="button" ref={compactReaderButton} aria-pressed={compactPane === 'reader'} onClick={() => { setCompactPane('reader'); setCompactNavigation(false); }}>阅读</button>
      <button type="button" aria-pressed={compactPane === 'chat'} onClick={() => { setCompactPane('chat'); setCompactNavigation(false); }}>对话</button>
    </div>}
    <main className="unified-main" data-compact-pane={compactPane} onKeyDown={event => {
      if (event.key === 'Escape' && compactNavigation) { setCompactNavigation(false); compactNavigationButton.current?.focus(); }
    }}>
      {compact && compactNavigation && <button type="button" tabIndex={-1} className="unified-navigation-backdrop" aria-label="关闭任务导航" onClick={() => { setCompactNavigation(false); compactNavigationButton.current?.focus(); }} />}
      <div id="unified-navigation" ref={navigationRef} className={`unified-task-nav ${compact && !compactNavigation ? 'unified-compact-hidden' : ''}`} style={{ width: layout.navigation ? layout.navWidth : 48 }}>
        <TaskNavigation tasks={tasks} activeTask={activeTask} papers={papers} collapsed={compact ? false : !layout.navigation} onToggle={() => {
          if (compact) { setCompactNavigation(false); compactNavigationButton.current?.focus(); }
          else patchLayout({ navigation: !layout.navigation });
        }}
          onSelectTask={id => { selectTask(id); setCompactNavigation(false); compactNavigationButton.current?.focus(); }} onCreateTask={async () => { await createTask({ title: '新任务' }); setCompactNavigation(false); setCompactPane('chat'); }} onOpenPaper={openPaper} onAddPaper={addPaper} onRemovePaper={removePaper} onOpenArtifact={openDocument}>
          <button type="button" className="unified-upload" disabled={uploading} onClick={() => fileInputRef.current?.click()}><Upload size={15} />{uploading ? '上传中…' : '上传 PDF'}</button>
          {focusedPaperId && <div className="unified-outline">
            <button type="button" onClick={() => setShowOutline((value) => !value)}>{showOutline ? <ChevronLeft size={13} /> : <ChevronRight size={13} />} 当前论文目录</button>
            {showOutline && <div>{outline.map((item) => <button type="button" key={item.id} style={{ paddingLeft: `${Math.max(0, item.level - 1) * 12 + 8}px` }} onClick={() => item.pageIndex != null && jumpToSource({ pdfId: focusedPaperId, pageIndex: item.pageIndex })}>{item.label}</button>)}{outline.length === 0 && <span>暂无目录</span>}</div>}
          </div>}
        </TaskNavigation>
      </div>
      <section className={`unified-reader ${!layout.reader ? 'unified-desktop-hidden' : ''}`} inert={compact && compactNavigation ? true : undefined} style={{ flexBasis: layout.chat ? `${layout.readerPercent}%` : '100%' }} aria-label="论文与成果">
        <div className="unified-pane-head">
          <BookOpen size={17} />
          <strong>{preview ? preview.kind === 'research.report' ? '研究报告' : '已生成结果' : activeDocument ? activeDocument.title || '笔记' : focusedPaperId ? getPaperTitle(papers, focusedPaperId) : '阅读区'}</strong>
          {(activeDocument || preview) && <button type="button" onClick={() => { goToPage(page.pageIndex); setSelectedDocument(null); setRecoveryPreview(null); }}>返回论文</button>}
          {!activeDocument && !preview && paperView.url && <div className="unified-translation-modes" role="group" aria-label="翻译视图">
            <button type="button" className={translationMode === 'original' ? 'active' : ''} onClick={() => setTranslationMode('original')}>原文</button>
            <button type="button" title={['success','partial'].includes(currentTranslationPage?.status) ? '查看已保存译文' : currentTranslationPage?.status === 'error' ? '查看翻译状态，重试需手动操作' : '打开后翻译当前页'} className={translationMode === 'translation' ? 'active' : ''} onClick={() => setTranslationMode('translation')}>译文</button>
            <button type="button" title={['success','partial'].includes(currentTranslationPage?.status) ? '对照原文与已保存译文' : '对照原文并翻译当前页'} className={translationMode === 'parallel' ? 'active' : ''} onClick={() => setTranslationMode('parallel')}>对照</button>
          </div>}
          <button type="button" className="unified-pane-hide" onClick={() => patchLayout({ reader: false, chat: true, mode: 'chat' })} aria-label="收起阅读区"><PanelLeftClose size={16} /></button>
        </div>
        {preview ? <div className="unified-document" aria-label="查看已生成结果">
          {preview.kind !== 'research.report' && <div className="unified-document-toolbar"><button type="button" disabled={savingRecovery || (preview.paperIds || preview.result?.materialScope?.allowedPaperIds || []).some(id => !activeTask.paperIds.includes(id))} onClick={recoverResult}><Save size={15} /> {savingRecovery ? '正在保存…' : '保存为成果'}</button></div>}
          <p>{preview.kind === 'research.report' ? '核对报告后，在对话中确认并保存结果。' : '保存完整结果，保留当前学习位置。'}</p>
          {(preview.paperIds || preview.result?.materialScope?.allowedPaperIds || []).some(id => !activeTask.paperIds.includes(id)) && <p role="status">请先恢复原请求材料，再保存成果。</p>}
          <CollapsedSources value={{ sources: preview.result?.sources || [] }} onJumpToSource={jumpToSource} />
          <div className="unified-document-preview"><MarkdownContent>{preview.result?.artifact?.text || preview.result?.message || preview.result?.reply}</MarkdownContent></div>
        </div> : activeDocument ? <div className="unified-document">
          {(selectedDocument.baseText === null || normalizeNoteContent(activeDocument) !== selectedDocument.baseText) && <div role="alert">
            <p>笔记已有新版本，请核对后再保存。当前草稿已保留。</p>
            <details><summary>最新已保存正文</summary><MarkdownContent>{normalizeNoteContent(activeDocument)}</MarkdownContent></details>
            <button type="button" onClick={() => {
              const baseText = normalizeNoteContent(activeDocument);
              setSelectedDocument(previous => ({ ...previous, baseText }));
              try { localStorage.setItem(documentDraftKey(selectedDocument) + ':base', JSON.stringify(baseText)); }
              catch { setLocalError('草稿核对记录保存失败，请保留当前正文'); }
            }}>已核对，保留我的修改</button>
          </div>}
          <div className="unified-document-toolbar">
            <div className="unified-document-modes" role="group" aria-label="成果视图">
              <button type="button" aria-pressed={!documentEditing} onClick={() => setDocumentEditing(false)}>阅读</button>
              <button type="button" aria-pressed={documentEditing} onClick={() => setDocumentEditing(true)}>编辑</button>
            </div>
            {(documentEditing || documentDirty) && <button type="button" disabled={savingDocument || restoringDocument || movingDocument || !documentDirty} onClick={saveDocumentFromToolbar}><Save size={15} /> {savingDocument ? '保存中…' : '保存'}</button>}
            <button type="button" onClick={exportDocument}><FileDown size={15} /> 下载</button>
            <span className="unified-document-save-state" role="status">{savingDocument ? '正在保存' : documentDirty ? '未保存修改' : '已保存'}</span>
          </div>
          <DocumentVersionHistory key={`${selectedDocument.taskId}/${selectedDocument.collection}/${selectedDocument.id ?? selectedDocument.index}`} document={activeDocument} onRestore={restoreDocument} disabled={savingDocument || movingDocument} />
          <DocumentOrganizer key={`organize/${documentDraftKey(selectedDocument)}`} document={activeDocument} taskId={activeTaskId} tasks={tasks}
            dirty={documentDirty || savingDocument} onRename={renameDocument} onMove={moveDocument} />
          <CollapsedSources value={activeDocument} onJumpToSource={jumpToSource} />
          {documentEditing ? <>
          <textarea aria-label="编辑笔记与成果" disabled={restoringDocument || movingDocument} value={documentDraft} onChange={(event) => {
            const value = event.target.value;
            setDocumentDraft(value);
            try {
              const key = documentDraftKey(selectedDocument);
              localStorage.setItem(key, value);
              if (localStorage.getItem(key + ':base') === null) localStorage.setItem(key + ':base', JSON.stringify(selectedDocument.baseText));
            }
            catch { setLocalError('本地草稿保存失败，请先保存或下载当前正文'); }
          }} />
          <details className="unified-document-edit-preview"><summary>预览</summary><MarkdownContent>{documentDraft || '（空白正文）'}</MarkdownContent></details>
          </> : <article className="unified-document-body" aria-label="成果正文"><MarkdownContent>{documentDraft || '（空白正文）'}</MarkdownContent></article>}
        </div> : paperView.error ? <div className="unified-empty" role="alert">{paperView.error}</div>
          : paperView.url ? <div className={`unified-reader-content unified-reader-content-${translationMode}`}>
            <div className="unified-pdf">
              {paperView.deconstruct?.processingStatus && <div className="unified-material-status" role="status">
                {['queued', 'parsing'].includes(paperView.deconstruct.processingStatus) ? '原文可阅读，正文正在解析…'
                  : paperView.deconstruct.questionReady ? '正文已就绪' : paperView.deconstruct.processingError || paperView.deconstruct.parseMessage || '原文可阅读，正文尚未就绪'}
                {['failed', 'interrupted', 'degraded'].includes(paperView.deconstruct.processingStatus) && !paperView.deconstruct.questionReady && <button type="button" disabled={processingRequest} onClick={() => requestMaterialProcessing(false)}>重试解析</button>}
                {paperView.deconstruct.aiAnalysisStatus === 'running' ? <span> · 正在生成概览…</span>
                  : paperView.deconstruct.questionReady && ['not_requested', 'failed', 'interrupted'].includes(paperView.deconstruct.aiAnalysisStatus) && <button type="button" disabled={processingRequest} onClick={() => requestMaterialProcessing(true)}>{paperView.deconstruct.aiAnalysisStatus === 'not_requested' ? '生成论文概览' : '重试论文概览'}</button>}
              </div>}
              <PdfViewer key={paperView.id} fileUrl={paperView.url} pdfId={paperView.id} paperSkeleton={paperView.deconstruct?.paper_skeleton || null} theme={theme} parseStatus={paperView.deconstruct?.parseStatus || papers.find((paper) => paper.id === paperView.id)?.parseStatus || null} initialHighlights={paperView.highlights}
              onPageChange={handlePdfPageChange} onPageTextExtracted={handlePageTextExtracted} onSelection={syncPdfSelection}
              onHighlightsChange={async (highlights) => { const db = await initDB(); await db.put('highlightStore', highlights, paperView.id); }}
              onSaveNote={async payload => {
                if (!activeTaskId || !paperView.id) throw new Error('请先打开任务论文');
                const note = selectionNote(payload, paperView.id, makeId());
                await updateTask(activeTaskId, task => ({ notes: [...task.notes, note] }));
              }}
              targetPageIndex={jump.pdfId === focusedPaperId && jump.taskId === activeTaskId ? jump.pageIndex : initialPaperPage} targetPageJumpToken={jump.token} focusedSourceAnchorId={jump.pdfId === focusedPaperId ? jump.anchorId : null} focusedSourceAnchorToken={jump.token} /></div>
            {translationMode !== 'original' && <div className="unified-translation"><TranslationPanel pdfId={paperView.id} fileUrl={paperView.url} pdfFileName={getPaperTitle(papers, paperView.id)} currentPage={page.pageIndex}
              pageData={currentTranslationPage?.status === 'translating' ? { ...currentTranslationPage, status: 'loading' } : currentTranslationPage}
              onRetry={() => handleRetryTranslation(translationState)} onCaptureArtifact={captureTranslation} /></div>}
          </div>
            : <div className="unified-empty"><FilePlus2 size={32} />
              <strong>{workspace.ready === false ? '正在读取任务…' : activeTask?.paperIds.length ? '选择一篇论文开始阅读' : '从一篇论文开始'}</strong>
              <p>{activeTask?.paperIds.length ? '在左侧选择论文；对话可以使用当前任务的全部材料。' : '上传 PDF 后即可阅读，再从对话中精读、补课或自测。'}</p>
              {uploading ? <p role="status">正在上传论文，请稍候…</p> : <button type="button" disabled={workspace.ready === false} onClick={() => activeTask?.paperIds.length ? openPaper(activeTask.paperIds[0]) : fileInputRef.current?.click()}>{activeTask?.paperIds.length ? '打开任务论文' : '上传论文'}</button>}
            </div>}
        {paperView.url && !activeDocument && !preview && <PaperPageNavigation pageIndex={page.pageIndex} totalPages={page.totalPages} onJump={goToPage} />}
      </section>
      {layout.reader && layout.chat && !compact && <div className="unified-resizer" role="separator" tabIndex={0} aria-orientation="vertical" aria-label="调整阅读与对话宽度" aria-valuemin={32} aria-valuemax={72} aria-valuenow={layout.readerPercent} onPointerDown={startResize} onKeyDown={event => {
        const steps = { ArrowLeft: -2, ArrowRight: 2 };
        if (!(event.key in steps) && !['Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const readerPercent = event.key === 'Home' ? 32 : event.key === 'End' ? 72 : Math.max(32, Math.min(72, layout.readerPercent + steps[event.key]));
        patchLayout({ readerPercent });
      }} />}
      <section className={`unified-chat ${!layout.chat ? 'unified-desktop-hidden' : ''}`} inert={compact && compactNavigation ? true : undefined} style={{ flexBasis: layout.reader ? `${100 - layout.readerPercent}%` : '100%' }} aria-label="任务对话">
        {activeTask && <ConversationExecution task={activeTask} records={learning.operations.records}
          busy={Boolean(learning.busyTasks[activeTaskId])} onRetry={requestId => learning.operations.retry(activeTask, requestId)}
          onSubmitSaved={requestId => learning.operations.submitSaved(activeTaskId, requestId)}
          onRefresh={() => learning.operations.refresh()} onCancel={requestId => learning.operations.cancel(activeTaskId, requestId)}
          onOpenResult={record => { setSelectedDocument(null); setRecoveryPreview(record); patchLayout({ reader: true }); }} />}
        <div className="unified-pane-head"><MessageSquare size={17} /><strong>对话</strong><span>{activeTask?.paperIds.length || 0} 篇材料</span><button type="button" className="unified-pane-hide" onClick={() => patchLayout({ chat: false, reader: true, mode: 'reader' })} aria-label="收起对话区"><PanelLeftClose size={16} /></button></div>
        {activeTask && <ConversationResearch task={activeTask} research={research} onJumpToSource={jumpToSource}
          onOpenReport={(run, result) => { setSelectedDocument(null); setRecoveryPreview({ taskId: activeTaskId,
            requestId: run.researchId, kind: 'research.report', paperIds: run.paperIds,
            result: { artifact: { text: sanitizeResearchReport(result.report) }, sources: (result.findings || []).flatMap(finding => finding.sources || []) } });
            patchLayout({ reader: true }); }} />}
        {savedLearningActivities.length > 0 && <details className="unified-learning-history"><summary>学习记录（{savedLearningActivities.length}）</summary>
          {savedLearningActivities.map((activity, index) => <div key={`${activity.activityId || activity.id}-${activity.revision}-${index}`}>
            <strong>{getPaperTitle(papers, activity.pdfId || activity.primaryPaperId)} · {activity.imported ? '导入记录' : activity.status === 'finished' ? '已结束' : activity.status === 'paused' ? '已暂停' : '已保存'}</strong>
            <p>{activity.concepts?.find(concept => concept.id === activity.currentConceptId)?.question || activity.goal || '已保存学习记录'}</p>
          </div>)}
        </details>}
        {research.starting && <p role="status">正在创建研究…</p>}
        {learning.busyTasks[activeTaskId] && <div className="unified-learning-controls" role="status">
          <span>{Object.values(learning.operations.records).some(item => item.taskId === activeTaskId && item.status === 'cancelling') ? '正在停止…' : '正在处理…'}</span>
          <button type="button" onClick={() => learning.cancel(activeTaskId)}>停止处理</button>
        </div>}
        {activeTask?.activeActivity?.activityId && activeTask.activeActivity.status !== 'finished' && <div className="unified-learning-controls" aria-label="当前学习活动">
          <span>{activeTask.activeActivity.mode === 'quiz' ? '自测' : '精读'} · {getPaperTitle(papers, activeTask.activeActivity.pdfId)}</span>
          <button type="button" disabled={learning.busyTasks[activeTaskId]} onClick={() => learning.refresh(activeTask)}>刷新活动</button>
          {activeTask.activeActivity.status === 'paused'
            ? <button type="button" disabled={learning.busyTasks[activeTaskId]} onClick={() => learning.act(activeTask, 'resume')}>继续学习</button>
            : <>
              {learning.completionSuggested ? <span>本轮概念已核验，可结束或继续追问。</span> : <select aria-label="学习输入方式" disabled={learning.busyTasks[activeTaskId]} value={learning.inputMode} onChange={(event) => learning.setInputMode(event.target.value)}><option value="answer">回答当前问题</option><option value="ask">临时追问</option></select>}
              {[['hint', '提示'], ['remediate', '补课'], ['retry', '重答'], ['skip', '跳过'], ['pause', '暂停']].map(([action, label]) => <button type="button" key={action} disabled={learning.busyTasks[activeTaskId]} onClick={() => learning.act(activeTask, action)}>{label}</button>)}
            </>}
          <button type="button" disabled={learning.busyTasks[activeTaskId]} onClick={() => learning.act(activeTask, 'finish')}>结束</button>
          {learning.busyTasks[activeTaskId] && <span role="status">正在处理…</span>}
          {!learning.completionSuggested && <p className="unified-learning-question">{activeTask.activeActivity.concepts?.find((concept) => concept.id === activeTask.activeActivity.currentConceptId)?.question}</p>}
        </div>}
        {intentChoice?.taskId === activeTaskId && <div className="unified-intent-choice" role="group" aria-label="选择分析重点">
          <span>{intentChoice.prompt}</span>
          {intentChoice.choices.map(choice => <button type="button" key={choice.skill.skillId} disabled={learning.busyTasks[activeTaskId]} onClick={() => sendMessage(intentChoice.text, choice.skill)}>{choice.label}</button>)}
          <button type="button" onClick={() => setIntentChoice(null)}>取消</button>
        </div>}
        {activeTask ? <ChatPanel key={activeTaskId} conversationId={activeTaskId}
          starterPrompts={activeTask.paperIds.length ? [
            { label: '带我读这篇', text: '/精读 帮我从研究问题与方法开始读这篇论文' },
            { label: '解释基础概念', text: '/补课 解释理解这篇论文需要的基础概念' },
            activeTask.paperIds.length > 1 ? { label: '比较论文', text: '/比较 这些论文的方法有什么共同点与差异？' } : { label: '检查我的理解', text: '/自测 帮我检查是否理解这篇论文的关键方法' },
          ] : [{ label: '解释一个概念', text: '我想了解的概念是：' }]}
          materials={activeTask.paperIds.map(id => papers.find(paper => paper.id === id) || { id })} messages={activeTask.messages} onSendMessage={sendMessage} onDeleteMessage={deleteMessage} onSaveToNote={(index) => saveMessage(index)} onCaptureArtifact={(index) => saveMessage(index, true)} onOpenArtifact={id => {
          const artifact = activeTask.artifacts.find(item => (item.id || item.artifactId) === id);
          if (artifact) { openDocument(artifact, 'artifacts'); return; }
          const owner = tasks.find(task => task.artifacts?.some(item => (item.id || item.artifactId) === id));
          if (owner) { setRequestedDocument({ taskId: owner.id, id }); selectTask(owner.id); }
          else setLocalError('成果已移出或任务列表有更新，请刷新后查看。');
        }} onJumpToSource={jumpToSource} isLoading={Boolean(learning.busyTasks[activeTaskId])} contextLabel={activeTask.paperIds.length ? `任务材料 ${activeTask.paperIds.length} 篇${focusedPaperId ? ` · 正在阅读 ${getPaperTitle(papers, focusedPaperId)}` : ''}` : '当前任务暂无论文'} enableSkills />
          : <div className="unified-empty"><p>创建任务后，即可围绕论文持续讨论。</p><button type="button" onClick={() => createTask({ title: '新任务' })}>新任务</button></div>}
      </section>
      {!layout.reader && <button type="button" className="unified-restore unified-restore-reader" onClick={() => patchLayout({ reader: true, mode: 'split' })} aria-label="展开阅读区"><PanelLeftOpen size={16} />阅读</button>}
      {!layout.chat && <button type="button" className="unified-restore unified-restore-chat" onClick={() => patchLayout({ chat: true, mode: 'split' })} aria-label="展开对话区"><MessageSquare size={16} />对话</button>}
    </main>
    {(workspace.error || learning.error || research.error || libraryError || localError) && <div className="unified-error" role="alert">{localError || workspace.error || libraryError || learning.error || research.error}</div>}
    <input ref={fileInputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => handleUpload(event.target.files?.[0])} />
  </div>;
}
