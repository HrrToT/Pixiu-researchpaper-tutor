import React, { useRef, useState } from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePageTranslation } from './usePageTranslation';
import { normalizeTranslationState } from '../utils/translationState';

function setup(api, stored = null) {
  return renderHook(({ pdfId }) => {
    const [translationState, commitTranslationState] = useState(() => stored || { pdfId, pages: {} });
    const [pdfPageState, setPdfPageState] = useState({ pageIndex: 0, totalPages: 2 });
    const currentPageTextRef = useRef({});
    return { translationState, ...usePageTranslation({ apiService: api, pdfId, translationState,
      commitTranslationState, pdfPageState, setPdfPageState, currentPageTextRef, isTranslated: true }) };
  }, { initialProps: { pdfId: 'A' } });
}

describe('page translation request lifecycle', () => {
  it('deduplicates concurrent text callbacks and reuses completed pages', async () => {
    let finish;
    const api = { translatePage: vi.fn(() => new Promise(resolve => { finish = resolve; })) };
    const { result } = setup(api);
    let pending;
    act(() => {
      pending = result.current.requestPageTranslation({ pageIndex: 0, pageText: 'original' });
      result.current.handlePageTextExtracted({ pageIndex: 0, pageText: 'original' });
    });
    expect(api.translatePage).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ translatedText: '译文' }); await pending; });
    act(() => result.current.handlePageTextExtracted({ pageIndex: 0, pageText: 'original' }));
    expect(api.translatePage).toHaveBeenCalledTimes(1);
    expect(result.current.translationState.pages[0].translatedText).toBe('译文');
  });

  it('does not fall back or retry failures until an explicit retry', async () => {
    const api = { translatePage: vi.fn().mockRejectedValueOnce(new Error('timeout')).mockResolvedValue({ translatedText: '恢复译文' }) };
    const { result } = setup(api);
    const payload = { pageIndex: 0, pageText: 'original', pageLayout: { blocks: [{ id: 'body' }] } };
    await act(async () => result.current.requestPageTranslation(payload));
    expect(api.translatePage).toHaveBeenCalledTimes(1);
    expect(result.current.translationState.pages[0].status).toBe('error');
    act(() => result.current.handlePageTextExtracted(payload));
    expect(api.translatePage).toHaveBeenCalledTimes(1);
    await act(async () => result.current.handleRetryTranslation(result.current.translationState));
    expect(api.translatePage).toHaveBeenCalledTimes(2);
    expect(result.current.translationState.pages[0].translatedText).toBe('恢复译文');
  });

  it('uses persisted successful pages and marks interrupted work for explicit recovery', async () => {
    const api = { translatePage: vi.fn() };
    const stored = normalizeTranslationState({ pages: { 0: { status: 'success', translatedText: '缓存译文' }, 1: { status: 'translating' } } }, 'A');
    const { result } = setup(api, stored);
    await act(async () => {
      await result.current.requestPageTranslation({ pageIndex: 0, pageText: 'page zero' });
      await result.current.requestPageTranslation({ pageIndex: 1, pageText: 'page one' });
    });
    expect(api.translatePage).not.toHaveBeenCalled();
    expect(result.current.translationState.pages[1].status).toBe('error');
  });

  it('aborts on paper changes and ignores late responses', async () => {
    let finish;
    const api = { translatePage: vi.fn(() => new Promise(resolve => { finish = resolve; })) };
    const { result, rerender } = setup(api);
    let pending;
    act(() => { pending = result.current.requestPageTranslation({ pageIndex: 0, pageText: 'A body' }); });
    const signal = api.translatePage.mock.calls[0][5].signal;
    rerender({ pdfId: 'B' });
    expect(signal.aborted).toBe(true);
    rerender({ pdfId: 'A' });
    await act(async () => { finish({ translatedText: 'late A answer' }); await pending; });
    expect(result.current.translationState.pages[0].translatedText).not.toBe('late A answer');
  });

  it('does not send image-only or blank pages', async () => {
    const api = { translatePage: vi.fn() };
    const { result } = setup(api);
    await act(async () => result.current.requestPageTranslation({ pageIndex: 0, pageText: '  ' }));
    expect(api.translatePage).not.toHaveBeenCalled();
    expect(result.current.translationState.pages[0].status).toBe('empty');
  });
});
