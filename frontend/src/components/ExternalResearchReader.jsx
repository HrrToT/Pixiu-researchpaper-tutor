import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Worker, Viewer, SpecialZoomLevel } from '@react-pdf-viewer/core';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import '@react-pdf-viewer/core/lib/styles/index.css';
import PaperPageNavigation from './PaperPageNavigation';
import { taskResearchApi } from '../services/taskResearchApi';

/** Preview saved source bytes; task membership changes only through the add action. */
export default function ExternalResearchReader({ source, onAddSource, onOpenPaper, onClose, taskPaperIds = [], theme = 'light' }) {
  const { taskId, runId, sourceId } = source;
  const [file, setFile] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState({ pageIndex: 0, totalPages: 0 });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState('');
  const [addedPaper, setAddedPaper] = useState(null);
  const navigation = useRef(null);
  const container = useRef(null);
  useEffect(() => { container.current?.focus(); }, []);
  const plugins = useMemo(() => [{ install: functions => { navigation.current = functions; } }], []);
  const identity = JSON.stringify([taskId, runId, sourceId]);
  const current = file?.identity === identity ? file : null;
  const hashPaperId = /^[a-f0-9]{64}$/u.test(source.contentHash || '') ? `${source.contentHash}.pdf` : null;
  const paperId = addedPaper?.identity === identity ? addedPaper.paperId
    : taskPaperIds.includes(hashPaperId) ? hashPaperId : null;

  useEffect(() => {
    const abort = new AbortController();
    let url;
    setFile({ identity, status: 'loading' });
    setPage({ pageIndex: 0, totalPages: 0 });
    (async () => {
      const blob = await taskResearchApi.sourceFile(taskId, runId, sourceId, abort.signal);
      if (abort.signal.aborted) return;
      if (!(blob instanceof Blob) || !blob.size || blob.type !== 'application/pdf') throw new Error('未取得可阅读的论文全文');
      url = URL.createObjectURL(blob);
      setFile({ identity, status: 'ready', url });
    })().catch(error => {
      if (!abort.signal.aborted) setFile({ identity, status: 'error', message: error.response
        ? '论文全文暂时无法打开，请重新打开或查看来源页面。' : error.message || '论文全文暂时无法打开' });
    });
    return () => { abort.abort(); if (url) URL.revokeObjectURL(url); };
  }, [identity, taskId, runId, sourceId, attempt]);

  const add = async () => {
    setAdding(true); setAddError('');
    try {
      const result = await onAddSource(taskId, runId, sourceId);
      if (!result?.paperId) throw new Error('尚未确认材料已加入，请重试');
      setAddedPaper({ identity, paperId: result.paperId });
    } catch (error) { setAddError(error.message || '材料未能加入任务，请重试'); }
    finally { setAdding(false); }
  };
  const sourcePage = Number.isInteger(source.pageIndex) && source.pageIndex >= 0 ? source.pageIndex : 0;
  return <section ref={container} tabIndex={-1} className="unified-external-reader" aria-label="外部论文原文" onKeyDown={event => {
    if (event.key === 'Escape') { event.stopPropagation(); onClose?.(); }
  }}>
    <div className="external-reader-toolbar">
      <div className="external-reader-title"><strong title={source.title}>{source.title || '外部论文'}</strong>
        {(source.arxivId || source.versionId) && <small className="theme-text-muted">{source.arxivId ? `arXiv:${source.arxivId}` : source.versionId}</small>}
      </div>
      {paperId ? <button type="button" onClick={() => onOpenPaper(paperId, page.totalPages ? page.pageIndex : sourcePage)}>打开任务论文</button>
        : onAddSource && <button type="button" disabled={adding} onClick={add}>{adding ? '加入中…' : '加入任务材料'}</button>}
      <button type="button" disabled={current?.status !== 'ready'} onClick={() => navigation.current?.zoom(SpecialZoomLevel.PageWidth)}>适合宽度</button>
      <button type="button" disabled={current?.status !== 'ready'} onClick={() => navigation.current?.zoom(1)}>100%</button>
    </div>
    {addError && <p role="alert" className="unified-inline-error">{addError}</p>}
    <div className="external-pdf-content">
      {current?.status === 'error' ? <div className="unified-empty" role="alert"><p>{current.message}</p>
        <button type="button" onClick={() => setAttempt(value => value + 1)}>重新打开</button>
        {/^https:\/\/arxiv\.org\/abs\//u.test(source.url || '') && <a href={source.url} target="_blank" rel="noopener noreferrer">查看来源页面</a>}
      </div> : current?.status !== 'ready' ? <p role="status" className="unified-empty">正在打开原文…</p>
        : <Worker workerUrl={pdfWorkerUrl}><Viewer fileUrl={current.url} plugins={plugins} initialPage={sourcePage} theme={theme}
          defaultScale={SpecialZoomLevel.PageWidth}
          renderError={() => <div role="alert" className="unified-empty"><p>PDF 暂时无法显示。</p>
            <button type="button" onClick={() => setAttempt(value => value + 1)}>重新打开</button>
            {/^https:\/\/arxiv\.org\/abs\//u.test(source.url || '') && <a href={source.url} target="_blank" rel="noopener noreferrer">查看来源页面</a>}
          </div>}
          onDocumentLoad={event => {
            const pageIndex = Math.min(sourcePage, Math.max(0, event.doc.numPages - 1));
            setPage({ pageIndex, totalPages: event.doc.numPages });
            void navigation.current?.jumpToPage(pageIndex);
          }}
          onPageChange={event => setPage({ pageIndex: event.currentPage, totalPages: event.doc.numPages })} /></Worker>}
    </div>
    {current?.status === 'ready' && <PaperPageNavigation {...page} onJump={index => navigation.current?.jumpToPage(index)} />}
  </section>;
}
