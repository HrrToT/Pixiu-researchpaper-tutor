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
  it('keeps cached translations paired with their original layout after parser changes', () => {
    const api = { translatePage: vi.fn() };
    const oldLayout = {viewport:{width:600,height:800},blocks:[{id:'old-caption',
      text:'An original figure caption.',bbox:{left:0.1,top:0.3,width:0.8,height:0.1}}]};
    const stored = normalizeTranslationState({pages:{0:{status:'success',pageLayout:oldLayout,
      translatedBlocks:[{id:'old-caption',translatedText:'原图说明译文'}]}}},'A');
    const { result } = setup(api, stored);
    act(() => result.current.handlePageTextExtracted({pageIndex:0,pageText:'new extraction',
      pageLayout:{...oldLayout,blocks:[{...oldLayout.blocks[0],id:'new-body'}]}}));
    expect(result.current.translationState.pages[0].pageLayout.blocks[0].id).toBe('old-caption');
    expect(result.current.translationState.pages[0].sourceText).toBe('new extraction');
    expect(api.translatePage).not.toHaveBeenCalled();
  });

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
    const payload = { pageIndex: 0, pageText: 'original', pageLayout: { blocks: [{ id: 'body',
      text: 'This paragraph explains the rendering method.', bbox: {left:0.1, top:0.4, width:0.6, height:0.1} }] } };
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

  it('preserves partial output and its warning across reload without generating again', async () => {
    const api = { translatePage: vi.fn().mockResolvedValue({status: 'partial', translatedText: '已有译文',
      missingBlockIds: ['missing'], warning: '还有1段未完成'}) };
    const { result } = setup(api);
    await act(async () => result.current.requestPageTranslation({pageIndex: 0, pageText: 'source'}));
    const restored = normalizeTranslationState(result.current.translationState, 'A');
    expect(restored.pages[0]).toMatchObject({status: 'partial', translatedText: '已有译文', missingBlockIds: ['missing'], warning: '还有1段未完成'});
    const second = setup(api, restored);
    await act(async () => second.result.current.requestPageTranslation({pageIndex: 0, pageText: 'source'}));
    expect(api.translatePage).toHaveBeenCalledTimes(1);
  });

  it('does not use a plain-text fallback for pages containing only preserved formulas', async () => {
    const api = { translatePage: vi.fn() };
    const { result } = setup(api);
    await act(async () => result.current.requestPageTranslation({pageIndex:0,pageText:'C = x + y, (2)',
      pageLayout:{blocks:[{id:'formula',text:'C = x + y, (2)',bbox:{left:0.3,top:0.6,width:0.3,height:0.02}}]}}));
    expect(api.translatePage).not.toHaveBeenCalled();
    expect(result.current.translationState.pages[0].status).toBe('empty');
    expect(result.current.translationState.pages[0].pageLayout.blocks).toHaveLength(1);
  });

  it('excludes standalone formulas from the model request while keeping original layout for viewing', async () => {
    const api = { translatePage: vi.fn().mockResolvedValue({translatedText:'译文'}) };
    const { result } = setup(api);
    const pageLayout = {viewport:{width:600,height:800},blocks:[
      {id:'body',text:'The paragraph explains the rendering method.',bbox:{left:0.1,top:0.4,width:0.6,height:0.1}},
      {id:'formula',text:'C = x + y, (2)',bbox:{left:0.3,top:0.6,width:0.3,height:0.02}},
    ]};
    await act(async () => result.current.requestPageTranslation({pageIndex:0,pageText:'source',pageLayout}));
    expect(api.translatePage.mock.calls[0][4].blocks.map(block=>block.id)).toEqual(['body']);
    expect(result.current.translationState.pages[0].pageLayout.blocks).toHaveLength(2);
  });
});
