import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ viewer: null, mounts: 0, jump: vi.fn(), zoom: vi.fn(), loadError: false }));
vi.mock('@react-pdf-viewer/core', () => ({ SpecialZoomLevel: { PageWidth: 'PageWidth' }, Worker: ({ children }) => children, Viewer: props => {
  state.viewer = props;
  React.useEffect(() => {
    state.mounts += 1;
    props.plugins.forEach(plugin => plugin.install?.({ jumpToPage: state.jump, zoom: state.zoom }));
    return () => props.plugins.forEach(plugin => plugin.uninstall?.({}));
  }, []);
  return state.loadError ? props.renderError({name:'InvalidPDFException',message:'broken'}) : <div />;
} }));
vi.mock('@react-pdf-viewer/highlight', () => ({ highlightPlugin: () => ({}) }));
vi.mock('../services/highlightStore', () => ({ loadHighlights: async () => [], addHighlight: vi.fn(), deleteHighlight: vi.fn() }));
import PdfViewer from './PdfViewer';

beforeEach(() => { state.mounts = 0; state.jump.mockReset(); state.zoom.mockReset(); state.loadError = false; });
const viewport = { width: 600, height: 800 };
const textContent = text => ({ items: [{ str: text, transform: [1, 0, 0, 12, 20, 700], width: 100, height: 12 }], styles: {} });

it('zooms a loaded paper and fits its width without remounting or changing page', async () => {
  const doc = {numPages:19,getPage:async()=>({getViewport:()=>viewport,getTextContent:async()=>textContent('body')})};
  render(<PdfViewer fileUrl="fixture.pdf" pdfId="A" targetPageIndex={3} />);
  expect(screen.getByRole('button',{name:'放大原文'})).toBeDisabled();
  await act(async()=>state.viewer.onDocumentLoad({doc}));
  act(()=>state.viewer.onZoom({scale:0.8}));
  fireEvent.click(screen.getByRole('button',{name:'放大原文'}));
  expect(state.zoom).toHaveBeenLastCalledWith(1);
  act(()=>state.viewer.onZoom({scale:1}));
  fireEvent.click(screen.getByRole('button',{name:'缩小原文'}));
  expect(state.zoom).toHaveBeenLastCalledWith(0.8);
  fireEvent.click(screen.getByRole('button',{name:'适合宽度'}));
  expect(state.zoom).toHaveBeenLastCalledWith('PageWidth');
  expect(state.mounts).toBe(1);
  expect(state.viewer.initialPage).toBe(3);
});

it('shows the load error instead of leaving it hidden behind the loading state', () => {
  state.loadError = true;
  render(<PdfViewer fileUrl="broken.pdf" pdfId="A" />);
  expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('检查文件是否完整或重新上传');
  expect(screen.getByRole('button',{name:'放大原文'})).toBeDisabled();
});

it('jumps through the installed viewer without remounting the document', async () => {
  const doc = { numPages: 19, getPage: async () => ({ getViewport: () => viewport, getTextContent: async () => textContent('body') }) };
  const view = render(<PdfViewer fileUrl="fixture.pdf" pdfId="A" targetPageIndex={0} targetPageJumpToken={0} />);
  await act(async () => state.viewer.onDocumentLoad({ doc }));
  view.rerender(<PdfViewer fileUrl="fixture.pdf" pdfId="A" targetPageIndex={3} targetPageJumpToken={1} />);
  expect(state.mounts).toBe(1);
  expect(state.jump).toHaveBeenLastCalledWith(3);
});

it('ignores text extraction from an old page and from an unmounted document', async () => {
  const finished = {};
  const doc = { numPages: 2, getPage: async number => ({ getViewport: () => viewport,
    getTextContent: () => new Promise(resolve => { finished[number] = resolve; }) }) };
  const extracted = vi.fn();
  const view = render(<PdfViewer fileUrl="fixture.pdf" pdfId="A" onPageTextExtracted={extracted} />);
  await act(async () => state.viewer.onDocumentLoad({ doc }));
  await act(async () => state.viewer.onPageChange({ currentPage: 1, doc }));
  await act(async () => finished[2](textContent('latest page')));
  await act(async () => finished[1](textContent('late old page')));
  expect(extracted).toHaveBeenCalledTimes(1);
  expect(extracted.mock.calls[0][0].pageIndex).toBe(1);
  await act(async () => state.viewer.onPageChange({ currentPage: 0, doc }));
  view.unmount();
  await act(async () => finished[1](textContent('late unmounted page')));
  expect(extracted).toHaveBeenCalledTimes(1);
});
