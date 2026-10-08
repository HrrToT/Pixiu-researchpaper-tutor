import React, { useEffect, useRef, useState } from 'react';
import { Bookmark, ChevronDown, ChevronUp, FileText, Link2, Plus, Send, Trash2, X } from 'lucide-react';

import MarkdownContent from './MarkdownContent';
import { getMessageMarkdownClassName } from './MessageMarkdownRenderer';
import SourceList from './SourceCitation.jsx';
import CollapsedSources from './CollapsedSources';
import { normalizeSentenceReferences } from './evidenceCitationModel.ts';
import { getSkillSuggestions } from '../utils/conversationSkills';
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
  onDeleteMessage?: (index: number) => void;
  onSaveToNote?: (index: number) => void;
  onCaptureArtifact?: (index: number) => void;
  onOpenArtifact?: (id: string) => void;
  onJumpToSource?: (source: ChatJumpSource) => void;
  onAbortChat?: () => void;
  isLoading?: boolean;
  contextLabel?: string;
  enableSkills?: boolean;
  materials?: MentionMaterial[];
  conversationId?: string;
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
        来源 {references.length}
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
  onDeleteMessage,
  onSaveToNote,
  onCaptureArtifact,
  onOpenArtifact,
  onJumpToSource,
  onAbortChat,
  isLoading = false,
  contextLabel = '',
  enableSkills = false,
  materials = [],
  conversationId,
  starterPrompts = [],
}) => {
  const [inputValue, setInputValue, draftError, clearInput] = useConversationDraft(conversationId);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [sendError, setSendError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const skillSuggestions = enableSkills ? getSkillSuggestions(inputValue) : [];
  const pendingMention = enableSkills ? pendingMaterialMention(inputValue) : null;
  const materialSuggestions = pendingMention ? materials.filter(material =>
    [material.title, material.filename, material.id].some(label => label?.toLocaleLowerCase().includes(pendingMention.query))) : [];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSend = async (): Promise<void> => {
    if (!inputValue.trim() || isLoading || submittingRef.current) return;
    const submittedText = inputValue;
    submittingRef.current = true;
    setSubmitting(true); setSendError('');
    try {
      const action = onSendMessage(submittedText.trim());
      const accepted = typeof (action as Promise<void | boolean>)?.then === 'function' ? await action : action;
      if (accepted === false) return;
      clearInput(submittedText);
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
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

  const renderMessageActions = (message: ChatMessage, index: number): React.ReactNode => (
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
      <button type="button" onClick={() => onSaveToNote?.(index)} className="reader-chat-action" title="收藏到学术笔记" aria-label="收藏到学术笔记">
        <Bookmark size={13} />
      </button>
      {message.role === 'ai' && message.artifactId && onOpenArtifact ? (
        <button type="button" onClick={() => onOpenArtifact(message.artifactId!)} className="reader-chat-action" title="打开完整成果" aria-label="打开完整成果">
          <FileText size={13} /> 打开成果
        </button>
      ) : message.role === 'ai' && (
        <button type="button" onClick={() => onCaptureArtifact?.(index)} className="reader-chat-action" title="保存为成果" aria-label="保存为成果">
          <Plus size={13} />
        </button>
      )}
      {message.sourceAnchorId && (
        <button type="button" onClick={() => onJumpToSource?.(message)} className="reader-chat-action" title="回到原文位置" aria-label="回到原文位置">
          <Link2 size={13} />
        </button>
      )}
    </div>
  );

  return (
    <div className="reader-chat-shell">
      <div className="reader-chat-scroll">
        {contextLabel && <div className="reader-chat-context">▣ {contextLabel}</div>}

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
              <div key={message.id ?? index} className="reader-chat-user-line group">
                <div className="reader-chat-user-bubble">
                  <MarkdownContent className={getMessageMarkdownClassName(message.role, 'chat')}>{message.content}</MarkdownContent>
                  {renderMessageActions(message, index)}
                </div>
              </div>
            );
          }

          return (
            <article key={message.id ?? index} className={`reader-chat-answer group ${isSystem ? 'reader-chat-answer-system' : ''}`}>
              <div className="reader-chat-answer-head">
                <img src="/貔貅紫白.png" alt="" width="27" height="27" />
                <span>{isSystem ? '系统提示' : '阅读助手'}</span>
                {renderMessageActions(message, index)}
              </div>
              <MarkdownContent className={getMessageMarkdownClassName(message.role, 'chat')}>{displayedContent}</MarkdownContent>
              <EvidenceReferences references={references} onJumpToSource={onJumpToSource} />
              {sourceFooter}
              {!references.length && !message.sourceAnchorId && <CollapsedSources value={message} onJumpToSource={onJumpToSource} />}
            </article>
          );
        })}

        {isLoading && (
          <div className="reader-chat-answer reader-chat-loading">
            <div className="reader-chat-answer-head">
              <img src="/貔貅紫白.png" alt="" width="27" height="27" />
              <span>阅读助手</span>
              {onAbortChat && <button type="button" onClick={onAbortChat} className="theme-danger-button ml-auto rounded-full p-1.5" title="停止生成" aria-label="停止生成">
                <X size={13} />
              </button>}
            </div>
            <div className="reader-chat-loading-bar"><span /></div>
            <span className="sr-only">生成中</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {pendingMention && (
        <div className="theme-panel theme-border mx-4 max-h-48 overflow-auto rounded-lg border p-1" role="group" aria-label="选择任务材料">
          {materialSuggestions.map(material => <button key={material.id} type="button"
            className="theme-text-primary block w-full rounded px-3 py-2 text-left text-sm hover:bg-[var(--panel-muted)]"
            onClick={() => { setInputValue(completeMaterialMention(inputValue, material, materials)); textareaRef.current?.focus(); }}>
            {material.title || material.filename || material.id}
          </button>)}
          {!materialSuggestions.length && <span className="theme-text-secondary block px-3 py-2 text-sm">没有匹配的任务论文</span>}
        </div>
      )}
      {skillSuggestions.length > 0 && (
        <div className="theme-panel theme-border mx-4 rounded-lg border p-1" role="group" aria-label="功能命令">
          {skillSuggestions.map((skill) => (
            <button key={skill.id} type="button" className="theme-text-primary flex w-full items-center gap-3 rounded px-3 py-2 text-left text-sm hover:bg-[var(--panel-muted)]"
              onClick={() => { setInputValue(`/${skill.command} `); textareaRef.current?.focus(); }}>
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
          disabled={isLoading || submitting}
          aria-label="输入问题"
          placeholder={isLoading ? '正在回答...' : enableSkills ? '输入问题，/ 选功能，@ 选材料' : '输入问题'}
        />
        <button type="button" onClick={handleSend} disabled={!inputValue.trim() || isLoading || submitting} className="reader-chat-send" aria-label="发送消息">
          <Send size={18} />
        </button>
      </div>
      {(draftError || sendError) && <p className="reader-chat-draft-error" role="alert">{draftError || sendError}</p>}
    </div>
  );
};

export default ChatPanel;
