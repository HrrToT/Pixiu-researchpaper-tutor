import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import DocumentVersionHistory from './DocumentVersionHistory';

describe('version history controls', () => {
  it('previews without changing the document and restores only on explicit click', async () => {
    const restore = vi.fn(async () => {});
    const version = { text: 'earlier answer', savedAt: '2026-10-04' };
    render(<DocumentVersionHistory document={{ versions: [version] }} onRestore={restore} />);
    fireEvent.click(screen.getByText('历史版本（1）'));
    fireEvent.change(screen.getByLabelText('选择历史版本'), { target: { value: '0' } });
    expect(screen.getByText('earlier answer')).toBeInTheDocument();
    expect(restore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '恢复这个版本' }));
    await waitFor(() => expect(restore).toHaveBeenCalledWith(version));
  });
  it('keeps the selected version available after failed persistence', async () => {
    render(<DocumentVersionHistory document={{ versions: [{ text: '' }] }} onRestore={async () => { throw new Error('版本冲突'); }} />);
    fireEvent.click(screen.getByText('历史版本（1）'));
    fireEvent.change(screen.getByLabelText('选择历史版本'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: '恢复这个版本' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('版本冲突');
    expect(screen.getByText('（空白正文）')).toBeInTheDocument();
  });
});
