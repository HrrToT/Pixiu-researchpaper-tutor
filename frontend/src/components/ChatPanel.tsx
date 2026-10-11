import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, FileText, Link2, Plus, Send, Trash2, X } from 'lucide-react';

import './ChatPanelInteraction.css';

import MarkdownContent from './MarkdownContent';
import { getMessageMarkdownClassName } from './MessageMarkdownRenderer';
import SourceList from './SourceCitation.jsx';
import CollapsedSources from './CollapsedSources';
import { normalizeSentenceReferences } from './evidenceCitationModel.ts';
import { getSkillSuggestions, parseSkillCommand, resolveConversationSkill } from '../utils/conversationSkills';
import { artifactChatPreview } from '../utils/artifactChatPreview';
import useConversationDraft from '../hooks/useConversationDraft';
import { completeMaterialMention, pendingMaterialMention, type MentionMaterial } from '../utils/materialMentions';

interface ChatJumpSource {
  sourceId?: string;
  sourceAnchorId?: string;
  sourceText?: string;
  sourcePageIndex?: number;
  sourcePdfId?: string;
  text?: string;
  pageIndex?: number;
  sectionId?: string;
  preview?: string;
}

interface ChatMessage {
  artifactId?: string;
  synthetic?: boolean;
  id?: string | number;
  role: 'user' | 'ai';
  isSystem?: boolean;
  content: string;
  sourceAnchorId?: string;
  sourceText?: string;
  sourcePageIndex?: number;
  sourcePdfId?: string;
  sentenceSourceMap?: unknown;
  rag_sources?: unknown;
}

interface EvidenceRef {
  id: string;
  sentence: string;
  sources: ChatJumpSource[];
}

interface ChatPanelProps {
  messages?: ChatMessage[];
  onSendMessage: (text: string) => void | boolean | Promise<void | boolean>;
  onDraftChange?: (text: string) => void;
  onDeleteMessage?: (index: number) => void;
  onSaveToNote?: (index: number) => void | Promise<unknown>;
  onCaptureArtifact?: (index: number) => void | Promise<unknown>;
  onOpenArtifact?: (id: string) => void;
  onJumpToSource?: (source: ChatJumpSource) => void;
  onAbortChat?: () => void;
  isLoading?: boolean;
  showLoadingIndicator?: boolean;
  contextLabel?: string;
  enableSkills?: boolean;
  materials?: MentionMaterial[];
  conversationId?: string;
  renderMessageAfter?: (message: ChatMessage, index: number) => React.ReactNode;
  historyContent?: React.ReactNode;
  composerContext?: React.ReactNode;
  currentActivity?: React.ReactNode;
  focusMessage?: { id?: string | number; index?: number; token: number };
  starterPrompts?: Array<{ label: string; text: string }>;
}

interface EvidenceReferencesProps {
  references?: EvidenceRef[];
  onJumpToSource?: (source: ChatJumpSource) => void;
}

const EvidenceReferences: React.FC<EvidenceReferencesProps> = ({ references = [], onJumpToSource }) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(false);

  if (!references.length) return null;

  return (
    <div className="reader-chat-citations">
      <button
        type="button"
        onClick={() => setIsExpanded((current: boolean) => !current)}
        className="reader-chat-citation"
      >
        <FileText size={12} />
        引用依据 {references.length} 处
        {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {isExpanded && (
        <div className="mt-3 space-y-2">
          {references.map((reference: EvidenceRef) => (
            <div key={reference.id} className="theme-card-soft rounded-lg p-3 text-xs leading-5 theme-text-secondary">
              <div className="theme-text-primary mb-1 font-semibold">{reference.sentence}</div>
              <div className="mb-2 theme-text-muted">{reference.sources.map((source: ChatJumpSource) => source.preview).join('；')}</div>
              <SourceList sources={reference.sources} onJumpToSource={onJumpToSource} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ChatPanel: React.FC<ChatPanelProps> = ({
  messages = [],
  onSendMessage,
  onDraftChange,
  onDeleteMessage,
  onSaveToNote,
  onCaptureArtifact,
  onOpenArtifact,
  onJumpToSource,
  onAbortChat,
  isLoading = false,
  showLoadingIndicator = true,
  contextLabel = '',
  enableSkills = false,
  materials = [],
  conversationId,
  starterPrompts = [],
  renderMessageAfter, historyContent, composerContext, currentActivity, focusMessage,
}) => {
  const [inputValue, setInputValue, draftError, clearInput] = useConversationDraft(conversationId);
  useEffect(() => { onDraftChange?.(inputValue); }, [inputValue, onDraftChange]);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [sendError, setSendError] = useState('');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const previousMessages = useRef(messages);
  const previousTask = useRef(conversationId);
  const messageElements = useRef(new Map<number, HTMLElement>());
  const [hasNewResults, setHasNewResults] = useState(false);
  const [search, setSearch] = useState('');
  const [saveStates, setSaveStates] = useState<Record<string, 'saving' | 'saved' | 'error'>>({});
  const savePending = useRef(new Set<string>());
  const latestDraft = useRef(inputValue);
  latestDraft.current = inputValue;
  const saveKey = (message: ChatMessage, index: number) => JSON.stringify([conversationId, message.id ?? index, message.content]);
  const messageId = (message: ChatMessage, index: number) => String(message.id ?? `index-${index}`);
  const scrollKey = `pixiu-conversation-scroll:${JSON.stringify(conversationId || 'legacy')}`;
  const jumpToMessage = (index: number) => {
    messageElements.current.get(index)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  const scrollToLatest = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    atBottomRef.current = true;
    setHasNewResults(false);
  };
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [showFunctions, setShowFunctions] = useState(false);
  const skillSuggestions = enableSkills ? getSkillSuggestions(showFunctions ? '/' : inputValue) : [];
  const pendingMention = enableSkills ? pendingMaterialMention(inputValue) : null;
  const materialSuggestions = pendingMention ? materials.filter(material =>
    [material.title, material.filename, material.id].some(label => label?.toLocaleLowerCase().includes(pendingMention.query))) : [];

  const explicitSkill = enableSkills ? parseSkillCommand(inputValue) : null;
  const recognizedSkill = enableSkills ? resolveConversationSkill(inputValue) : null;
  const selectedMentions = enableSkills ? Array.from(new Set(Array.from(String(inputValue).matchAll(/@\{([^}]+)\}/gu), match => match[1]))) : [];
  const searchResults = search.trim() ? messages.map((message, index) => ({ message, index }))
    .filter(({ message }) => message.content.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) : [];

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    let stored: string | null = null;
    try { stored = sessionStorage.getItem(scrollKey); } catch { /* storage may be unavailable */ }
    scroller.scrollTop = stored === null ? scroller.scrollHeight : Number(stored) || 0;
    atBottomRef.current = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
    setHasNewResults(false);
    setSearch('');
    setShowFunctions(false);
    return () => {
      try { sessionStorage.setItem(scrollKey, String(scroller.scrollTop)); } catch { /* preserve in-page navigation */ }
    };
  }, [scrollKey]);

  useEffect(() => {
    if (previousTask.current !== conversationId) {
      previousTask.current = conversationId;
      previousMessages.current = messages;
      return;
    }
    const changed = messages.length !== previousMessages.current.length || messages.some((message, index) =>
      message.content !== previousMessages.current[index]?.content || message.artifactId !== previousMessages.current[index]?.artifactId);
    previousMessages.current = messages;
    if (!changed) return;
    if (atBottomRef.current) scrollToLatest();
    else setHasNewResults(true);
  }, [messages, conversationId]);

  // Slots can receive completed results without changing the message array.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || typeof MutationObserver === 'undefined') return;
    let previousText = scroller.textContent;
    const observer = new MutationObserver(() => {
      const text = scroller.textContent;
      if (text === previousText) return;
      previousText = text;
      if (atBottomRef.current) scrollToLatest();
      else setHasNewResults(true);
    });
    observer.observe(scroller, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [scrollKey]);

  const appliedFocus = useRef('');
  useEffect(() => {
    if (!focusMessage) return;
    const requestKey = JSON.stringify([conversationId, focusMessage.token]);
    if (appliedFocus.current === requestKey) return;
    const index = focusMessage.id !== undefined ? messages.findIndex(message => String(message.id) === String(focusMessage.id)) : focusMessage.index;
    if (index !== undefined && index >= 0) { appliedFocus.current = requestKey; jumpToMessage(index); }
  }, [focusMessage, messages, conversationId]);

  const saveMessage = async (message: ChatMessage, index: number) => {
    const key = saveKey(message, index);
    if (savePending.current.has(key) || saveStates[key] === 'saved') return;
    const save = message.role === 'ai' ? onCaptureArtifact : onSaveToNote || onCaptureArtifact;
    if (!save) return;
    savePending.current.add(key);
    setSaveStates(current => ({ ...current, [key]: 'saving' }));
    try {
      const saved = await save(index);
      if (saved === false) throw new Error('保存未完成');
      setSaveStates(current => ({ ...current, [key]: 'saved' }));
    } catch {
      setSaveStates(current => ({ ...current, [key]: 'error' }));
    } finally { savePending.current.delete(key); }
  };

  const handleSend = async (): Promise<void> => {
    if (!inputValue.trim() || isLoading || submittingRef.current) return;
    const submittedText = inputValue;
    submittingRef.current = true;
    setSubmitting(true); setSendError('');
    try {
      const action = onSendMessage(submittedText.trim());
      const accepted = typeof (action as Promise<void | boolean>)?.then === 'function' ? await action : action;
      if (accepted === false) return;
      if (latestDraft.current === submittedText) clearInput(submittedText);
      if (latestDraft.current === submittedText && textareaRef.current) textareaRef.current.style.height = 'auto';
    } catch (error) {
      setSendError((error as Error).message || '发送失败，输入已保留。');
    } finally { submittingRef.current = false; setSubmitting(false); }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>): void => {
    setInputValue(event.target.value);
    const textarea = event.target;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  };

  const renderMessageActions = (message: ChatMessage, index: number): React.ReactNode => message.synthetic ? null : (
    <div className="reader-chat-message-actions">
      <button
        type="button"
        onClick={() => {
          if (window.confirm('确定删除这条对话记录吗？')) onDeleteMessage?.(index);
        }}
        className="theme-danger-button rounded-full p-1.5"
        title="删除此消息"
        aria-label="删除此消息"
      >
        <Trash2 size={13} />
      </button>
      {message.artifactId ? (
        <button type="button" onClick={() => onOpenArtifact?.(message.artifactId!)} disabled={!onOpenArtifact} className="reader-chat-action" title="打开完整成果" aria-label="打开完整成果">
          <FileText size={13} /> 打开成果
        </button>
      ) : (message.role === 'ai' ? onCaptureArtifact : onSaveToNote || onCaptureArtifact) && (
        <button type="button" onClick={() => saveMessage(message, index)} className="reader-chat-action"
          disabled={['saving', 'saved'].includes(saveStates[saveKey(message, index)])}
          title="保存" aria-label={saveStates[saveKey(message, index)] === 'saving' ? '保存中' : saveStates[saveKey(message, index)] === 'saved' ? '已保存' : '保存'}>
          <Plus size={13} /> {saveStates[saveKey(message, index)] === 'saving' ? '保存中' : saveStates[saveKey(message, index)] === 'saved' ? '已保存' : '保存'}
        </button>
      )}
      {saveStates[saveKey(message, index)] === 'error' && <span role="alert">保存失败，请重试</span>}
      {message.sourceAnchorId && (
        <button type="button" onClick={() => onJumpToSource?.(message)} className="reader-chat-action" title="回到原文位置" aria-label="回到原文位置">
          <Link2 size={13} />
        </button>
      )}
    </div>
  );

  return (
    <div className="reader-chat-shell">
      <div className="chat-history-search">
        <input aria-label="搜索对话" placeholder="搜索对话" value={search} onChange={event => setSearch(event.target.value)} />
        {search && <button type="button" onClick={() => setSearch('')} aria-label="清除对话搜索"><X size={13} /></button>}
        {search.trim() && <div className="chat-search-results" role="group" aria-label="对话搜索结果">
          <span>{searchResults.length} 条匹配</span>
          {searchResults.map(({ message, index }) => <button key={messageId(message, index)} type="button" onClick={() => jumpToMessage(index)}>
            第 {index + 1} 条 · {message.content.slice(0, 70)}
          </button>)}
        </div>}
      </div>
      <div className="reader-chat-scroll" ref={scrollRef} onScroll={event => {
        const node = event.currentTarget;
        atBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
        if (atBottomRef.current) setHasNewResults(false);
        try { sessionStorage.setItem(scrollKey, String(node.scrollTop)); } catch { /* optional persistence */ }
      }}>

        {!messages.length && !isLoading && starterPrompts.length > 0 && <div className="reader-chat-start" aria-label="对话起点">
          <strong>从一个问题开始</strong>
          <p>{materials.length ? '告诉我哪里读不懂，或选择一个起点。' : '先上传论文，或告诉我你想了解的概念。'}</p>
          <div>{starterPrompts.map(prompt => <button key={prompt.label} type="button" disabled={submitting}
            onClick={() => { setInputValue(prompt.text); textareaRef.current?.focus(); }}>{prompt.label}</button>)}</div>
        </div>}

        {messages.map((message: ChatMessage, index: number) => {
          const isUser = message.role === 'user';
          const isSystem = Boolean(message.isSystem);
          const displayedContent = message.artifactId && !isUser ? artifactChatPreview(message.content) : message.content;
          const references = normalizeSentenceReferences(message.sentenceSourceMap, message.rag_sources, { target: 'message' }) as EvidenceRef[];
          const sourceFooter = message.sourceAnchorId ? (
            <div className="reader-chat-citations">
              <SourceList
                sources={[{
                  sourceId: message.sourceAnchorId,
                  text: message.sourceText || message.content,
                  pageIndex: message.sourcePageIndex,
                  sectionId: message.sourceAnchorId,
                  pdfId: message.sourcePdfId,
                }]}
                onJumpToSource={onJumpToSource}
              />
            </div>
          ) : null;

          if (isUser) {
            return (
              <div key={message.id ?? index} id={`chat-message-${encodeURIComponent(messageId(message, index))}`} data-message-id={messageId(message, index)} data-message-index={index}
                ref={node => { if (node) messageElements.current.set(index, node); else messageElements.current.delete(index); }} className="chat-message-anchor">
              <div className="reader-chat-user-line group">
                <div className="reader-chat-user-bubble">
                  <MarkdownContent className={getMessageMarkdownClassName(message.role, 'chat')}>{message.content}</MarkdownContent>
                  {renderMessageActions(message, index)}
                </div>
              </div>
              {renderMessageAfter?.(message, index)}
              </div>
            );
          }

          return (
            <article key={message.id ?? index} id={`chat-message-${encodeURIComponent(messageId(message, index))}`} data-message-id={messageId(message, index)} data-message-index={index}
              ref={node => { if (node) messageElements.current.set(index, node); else messageElements.current.delete(index); }} className={`reader-chat-answer group ${isSystem ? 'reader-chat-answer-system' : ''}`}>
              <div className="reader-chat-answer-head">
                <img src="/貔貅紫白.png" alt="" width="27" height="27" />
                <span>{isSystem ? '系统提示' : '阅读助手'}</span>
                {renderMessageActions(message, index)}
              </div>
              <MarkdownContent className={getMessageMarkdownClassName(message.role, 'chat')}>{displayedContent}</MarkdownContent>
              <EvidenceReferences references={references} onJumpToSource={onJumpToSource} />
              {sourceFooter}
              {!references.length && !message.sourceAnchorId && <CollapsedSources value={message} onJumpToSource={onJumpToSource} />}
              {renderMessageAfter?.(message, index)}
            </article>
          );
        })}

        {isLoading && showLoadingIndicator && (
          <div className="reader-chat-answer reader-chat-loading">
            <div className="reader-chat-answer-head">
              <img src="/貔貅紫白.png" alt="" width="27" height="27" />
              <span>阅读助手</span>

            </div>
            <div className="reader-chat-loading-bar"><span /></div>
            <span className="sr-only" role="status">生成中</span>
          </div>
        )}

        {historyContent}
        <div ref={messagesEndRef} />
      </div>

      {hasNewResults && <button type="button" className="chat-new-results" onClick={scrollToLatest}>有新结果 · 查看最新</button>}
      {currentActivity && <div className="chat-current-activity">{currentActivity}</div>}
      {(composerContext !== undefined ? composerContext : contextLabel) && <div className="reader-chat-context chat-composer-context">{composerContext !== undefined ? composerContext : `▣ ${contextLabel}`}</div>}
      {enableSkills && <div className="chat-composer-tools">
        <button type="button" aria-expanded={showFunctions} onClick={() => { setShowFunctions(value => !value); textareaRef.current?.focus(); }}>功能</button>
        <button type="button" onClick={() => { setInputValue(`${inputValue}${inputValue && !/\s$/u.test(inputValue) ? ' ' : ''}@`); textareaRef.current?.focus(); }}>@ 材料</button>
        {recognizedSkill && <span className="chat-draft-chip">{recognizedSkill.command}
          {explicitSkill && <button type="button" aria-label={`取消${explicitSkill.command}功能`} onClick={() => setInputValue(inputValue.replace(/^\s*\/[^\s]+\s*/u, ''))}><X size={12} /></button>}
        </span>}
        {selectedMentions.map(label => <span key={label} className="chat-draft-chip" title={label}>@{label}
          <button type="button" aria-label={`移除材料 ${label}`} onClick={() => setInputValue(inputValue.split(`@{${label}}`).join('').replace(/ {2,}/gu, ' '))}><X size={12} /></button>
        </span>)}
      </div>}
      {pendingMention && (
        <div className="chat-composer-menu theme-panel theme-border mx-4 max-h-48 overflow-auto rounded-lg border p-1" role="group" aria-label="选择任务材料">
          {materialSuggestions.map(material => <button key={material.id} type="button"
            className="theme-text-primary block w-full rounded px-3 py-2 text-left text-sm hover:bg-[var(--panel-muted)]"
            onClick={() => { setInputValue(completeMaterialMention(inputValue, material, materials)); textareaRef.current?.focus(); }}>
            {material.title || material.filename || material.id}
          </button>)}
          {!materialSuggestions.length && <span className="theme-text-secondary block px-3 py-2 text-sm">没有匹配的任务论文</span>}
        </div>
      )}
      {skillSuggestions.length > 0 && (
        <div className="chat-composer-menu theme-panel theme-border mx-4 rounded-lg border p-1" role="group" aria-label="功能命令">
          {skillSuggestions.map((skill) => (
            <button key={skill.id} type="button" className="theme-text-primary flex w-full items-center gap-3 rounded px-3 py-2 text-left text-sm hover:bg-[var(--panel-muted)]"
              onClick={() => { setInputValue(`/${skill.command} ${inputValue.replace(/^\s*\/[^\s]*\s*/u, '')}`); setShowFunctions(false); textareaRef.current?.focus(); }}>
              <span>/{skill.command}</span><span className="theme-text-secondary text-xs">{skill.description}</span>
            </button>
          ))}
        </div>
      )}
      <div className="reader-chat-composer">
        <textarea
          ref={textareaRef}
          rows={1}
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          aria-label="输入问题"
          placeholder={enableSkills ? '输入问题，/ 选功能，@ 选材料' : '输入问题'}
        />
        {isLoading && onAbortChat && <button type="button" onClick={onAbortChat} className="chat-composer-stop" title="停止生成" aria-label="停止生成"><X size={16} />停止</button>}
        <button type="button" onClick={handleSend} disabled={!inputValue.trim() || isLoading || submitting} className="reader-chat-send" aria-label="发送消息">
          <Send size={18} />
        </button>
      </div>
      {(draftError || sendError) && <p className="reader-chat-draft-error" role="alert">{draftError || sendError}</p>}
    </div>
  );
};

export default ChatPanel;
