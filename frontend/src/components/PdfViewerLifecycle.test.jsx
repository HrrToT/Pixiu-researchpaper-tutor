import React from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ viewer: null, mounts: 0, jump: vi.fn() }));
vi.mock('@react-pdf-viewer/core', () => ({ SpecialZoomLevel: { PageWidth: 'PageWidth' }, Worker: ({ children }) => children, Viewer: props => {
  state.viewer = props;
  React.useEffect(() => {
    state.mounts += 1;
    props.plugins.forEach(plugin => plugin.install?.({ jumpToPage: state.jump }));
    return () => props.plugins.forEach(plugin => plugin.uninstall?.({}));
  }, []);
  return <div />;
} }));
vi.mock('@react-pdf-viewer/highlight', () => ({ highlightPlugin: () => ({}) }));
vi.mock('../services/highlightStore', () => ({ loadHighlights: async () => [], addHighlight: vi.fn(), deleteHighlight: vi.fn() }));
import PdfViewer from './PdfViewer';

beforeEach(() => { state.mounts = 0; state.jump.mockReset(); });
const viewport = { width: 600, height: 800 };
const textContent = text => ({ items: [{ str: text, transform: [1, 0, 0, 12, 20, 700], width: 100, height: 12 }], styles: {} });

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
