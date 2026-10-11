import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CollapsedSources from './CollapsedSources';
import { documentSources } from '../utils/documentSources';

describe('saved source provenance', () => {
  it('retains the selected text paper identity and deduplicates references', () => {
    const source = { sourceId: 's', pdfId: 'A', pageIndex: 2, text: 'evidence' };
    expect(documentSources({ rag_sources: [source, source] })).toEqual([source]);
    expect(documentSources({ sourceAnchorId: 'anchor', sourcePdfId: 'B', sourcePageIndex: 0, sourceText: 'quote' })[0])
      .toMatchObject({ pdfId: 'B', pageIndex: 0, text: 'quote' });
  });
  it('keeps material details collapsed and jumps with the original paper identity', () => {
    const jump = vi.fn();
    const { container } = render(<CollapsedSources value={{ sources: [{ sourceId: 's', pdfId: 'B', pageIndex: 2, text: 'evidence' }] }} onJumpToSource={jump} />);
    expect(container.querySelector('details')).not.toHaveAttribute('open');
    fireEvent.click(screen.getByText('证据片段（1）'));
    fireEvent.click(screen.getByRole('button', { name: /跳回原文/ }));
    expect(jump).toHaveBeenCalledWith(expect.objectContaining({ pdfId: 'B', pageIndex: 2 }));
  });
});
