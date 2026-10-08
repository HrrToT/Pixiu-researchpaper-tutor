import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ChatPanel from './ChatPanel.tsx';

const defaultProps = {
  messages: [],
  onSendMessage: vi.fn(),
  onDeleteMessage: vi.fn(),
  onSaveToNote: vi.fn(),
  onCaptureArtifact: vi.fn(),
  onJumpToSource: vi.fn(),
  onAbortChat: vi.fn(),
  isLoading: false,
};

function renderChat(props = {}) {
  return render(<ChatPanel {...defaultProps} {...props} />);
}

describe('ChatPanel', () => {
  it('opens the existing full artifact instead of saving a second copy of the summary', () => {
    const open = vi.fn();
    const capture = vi.fn();
    renderChat({ messages: [{ role: 'ai', content: '简短结论', artifactId: 'full' }], onOpenArtifact: open, onCaptureArtifact: capture });
    fireEvent.click(screen.getByRole('button', { name: '打开完整成果' }));
    expect(open).toHaveBeenCalledWith('full');
    expect(capture).not.toHaveBeenCalled();
  });
  it('completes an @ material mention without losing the preceding question', () => {
    const send = vi.fn();
    renderChat({ enableSkills: true, onSendMessage: send, materials: [{ id: 'b', title: '论文乙' }] });
    fireEvent.change(screen.getByLabelText('输入问题'), { target: { value: '只根据 @乙' } });
    fireEvent.click(screen.getByRole('button', { name: '论文乙', exact: true }));
    expect(screen.getByLabelText('输入问题')).toHaveValue('只根据 @{论文乙} ');
    fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
    expect(send).toHaveBeenCalledWith('只根据 @{论文乙}');
  });
  it('renders input textarea', () => {
    renderChat();
    const textarea = screen.getByLabelText('输入问题');
    expect(textarea).toBeInTheDocument();
    expect(textarea).not.toBeDisabled();
  });

  it('disables input when loading', () => {
    renderChat({ isLoading: true });
    const textarea = screen.getByLabelText('输入问题');
    expect(textarea).toBeDisabled();
  });

  it('calls onSendMessage when typing and clicking send', () => {
    const onSend = vi.fn();
    renderChat({ onSendMessage: onSend });

    const textarea = screen.getByLabelText('输入问题');
    fireEvent.change(textarea, { target: { value: '这篇论文的核心贡献？' } });

    const sendButton = textarea.parentElement.querySelector('button:last-child');
    fireEvent.click(sendButton);

    expect(onSend).toHaveBeenCalledWith('这篇论文的核心贡献？');
  });

  it('sends message on Enter key', () => {
    const onSend = vi.fn();
    renderChat({ onSendMessage: onSend });

    const textarea = screen.getByLabelText('输入问题');
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(onSend).toHaveBeenCalledWith('Hello');
  });

  it('does not send on Shift+Enter', () => {
    const onSend = vi.fn();
    renderChat({ onSendMessage: onSend });

    const textarea = screen.getByLabelText('输入问题');
    fireEvent.change(textarea, { target: { value: 'multiline' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('renders user and AI messages', () => {
    const messages = [
      { id: 1, role: 'user', content: '什么是注意力机制？' },
      { id: 2, role: 'ai', content: '注意力机制是神经网络中...' },
    ];
    renderChat({ messages });

    expect(screen.getByText('什么是注意力机制？')).toBeInTheDocument();
    // AI messages are rendered inside InsightCard with markdown
    expect(screen.getByText(/注意力机制是神经网络中/)).toBeInTheDocument();
  });

  it('renders loading skeleton when isLoading', () => {
    renderChat({
      isLoading: true,
      messages: [{ id: 1, role: 'user', content: 'Hi' }],
    });
    expect(screen.getByText('生成中')).toBeInTheDocument();
    // The loading indicator shows a pulsing progress bar
  });

  it('calls onAbortChat when stop button is clicked', () => {
    const onAbort = vi.fn();
    renderChat({ isLoading: true, onAbortChat: onAbort });

    const stopButton = screen.getByTitle('停止生成');
    fireEvent.click(stopButton);
    expect(onAbort).toHaveBeenCalled();
  });

  it('disables send button when input is empty', () => {
    renderChat();
    const textarea = screen.getByLabelText('输入问题');
    const sendButton = textarea.parentElement.querySelector('button:last-child');
    expect(sendButton).toBeDisabled();
  });

  it('renders the current reading context', () => {
    renderChat({ contextLabel: '第 8 页 · Method' });
    expect(screen.getByText(/第 8 页 · Method/)).toBeInTheDocument();
  });

  it('calls onDeleteMessage on message delete', () => {
    const onDelete = vi.fn();
    const messages = [{ id: 1, role: 'ai', content: '回答内容' }];
    const originalConfirm = window.confirm;
    window.confirm = vi.fn(() => true);

    renderChat({ messages, onDeleteMessage: onDelete });

    fireEvent.click(screen.getByTitle('删除此消息'));

    expect(window.confirm).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith(0);

    window.confirm = originalConfirm;
  });
});
