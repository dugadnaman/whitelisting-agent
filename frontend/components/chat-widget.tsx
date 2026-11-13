'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import { useApp } from '@/lib/context';
import { sendAgentMessage } from '@/lib/api';
import { formatChannel } from '@/lib/format';
import type { AgentChatAction, AgentChatResponse } from '@/lib/api';
type ChatMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  actions_taken?: AgentChatAction[];
  suggested_actions?: string[];
  isLoading?: boolean;
};

const DEFAULT_SUGGESTED_PROMPTS = [
  'Check if template exists: Dear customer, your EMI is due.',
  'Brief TCN-524 (LAP GST Content)',
  'Show pending Jira briefs',
  'Show recent Jira briefs',
  'List all rejected templates for this account',
  'Poll live approval status from Meta',
];
function formatMessageContent(content: string) {
  // Simple markdown renderer for headers, bold, codeblocks, lists, and linebreaks
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];

  lines.forEach((line, idx) => {
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <pre
            key={`code-${idx}`}
            className="my-2 p-3 bg-gray-900 text-gray-100 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap selection:bg-blue-600"
          >
            <code>{codeBuffer.join('\n')}</code>
          </pre>
        );
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      return;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      return;
    }

    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={idx} className="font-medium text-gray-900 text-sm mt-2 mb-1 flex items-center gap-1.5">
          {line.replace('### ', '')}
        </h4>
      );
    } else if (line.startsWith('#### ')) {
      elements.push(
        <h5 key={idx} className="font-medium text-gray-800 text-xs mt-2 mb-0.5">
          {line.replace('#### ', '')}
        </h5>
      );
    } else if (line.startsWith('• ') || line.startsWith('- ')) {
      elements.push(
        <div key={idx} className="flex items-start gap-1.5 text-xs text-gray-700 my-0.5 pl-1">
          <span className="text-gray-400 select-none">•</span>
          <span>{renderInlineStyles(line.substring(2))}</span>
        </div>
      );
    } else if (!line.trim()) {
      elements.push(<div key={idx} className="h-2" />);
    } else {
      elements.push(
        <p key={idx} className="text-xs text-gray-800 leading-relaxed my-0.5">
          {renderInlineStyles(line)}
        </p>
      );
    }
  });

  return elements;
}

function renderInlineStyles(text: string): React.ReactNode {
  // Parse inline `code` and **bold**
  const parts: React.ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code key={match.index} className="px-1.5 py-0.5 bg-gray-100 text-gray-900 font-mono text-xs rounded border border-gray-200">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(
        <strong key={match.index} className="font-medium text-gray-900">
          {token.slice(2, -2)}
        </strong>
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

export default function ChatWidget() {
  const pathname = usePathname();
  const { account, channel, user, getAccountLabel } = useApp();
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const welcomeMessage =
    `### Template review assistant\n\n` +
    `Current destination: **${getAccountLabel(account)} (${formatChannel(channel)})**\n\n` +
    `**Available tasks**\n` +
    `• **Submit templates**: ask how to submit, or provide a template name and body\n` +
    `• **Review rejections**: inspect a template's rejection and request a correction\n` +
    `• **Inspect catalogs**: list rejected templates or pending approvals\n` +
    `• **Check statuses**: request current approval status from Meta\n` +
    `• **Review copy**: inspect variables, links and compliance before making changes`;
  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    {
      id: 'init-1',
      role: 'assistant',
      content: welcomeMessage,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      suggested_actions: DEFAULT_SUGGESTED_PROMPTS,
    },
  ]);
  useEffect(() => {
    setMessages((prev) => {
      if (prev.length !== 1 || prev[0].id !== 'init-1') return prev;
      return [{ ...prev[0], content: welcomeMessage }];
    });
  }, [welcomeMessage]);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
      inputRef.current?.focus();
    }
  }, [isOpen, messages, scrollToBottom]);

  // Keyboard shortcut: Cmd+K / Ctrl+K or custom event to toggle agent drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      } else if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };
    const handleCustomToggle = () => setIsOpen((prev) => !prev);

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('toggle-copilot', handleCustomToggle);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('toggle-copilot', handleCustomToggle);
    };
  }, [isOpen]);

  const handleSend = async (textToSend?: string) => {
    const prompt = (textToSend || input).trim();
    if (!prompt || loading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    const pendingAssistantMsg: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: 'Analyzing template catalog and executing instructions...',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      isLoading: true,
    };

    setMessages((prev) => [...prev, userMsg, pendingAssistantMsg]);
    setInput('');
    setLoading(true);

    try {
      const history = messages
        .filter((m) => !m.isLoading)
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.content }));

      const res: AgentChatResponse = await sendAgentMessage(
        prompt,
        account,
        channel,
        user || 'Operator',
        history
      );

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === pendingAssistantMsg.id
            ? {
                ...msg,
                content: res.reply,
                actions_taken: res.actions_taken,
                suggested_actions: res.suggested_actions,
                isLoading: false,
              }
            : msg
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === pendingAssistantMsg.id
            ? {
                ...msg,
                content: `**Agent connection error:** ${err instanceof Error ? err.message : String(err)}`,
                isLoading: false,
              }
            : msg
        )
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = () => {
    setMessages([
      {
        id: `init-${Date.now()}`,
        role: 'assistant',
        content: `### Chat cleared\n\nCurrent destination: **${getAccountLabel(account)} (${formatChannel(channel)})**`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        suggested_actions: DEFAULT_SUGGESTED_PROMPTS,
      },
    ]);
  };

  if (pathname === '/login' || pathname === '/signup') {
    return null;
  }
  return (
    <>
      {/* Floating Copilot Launcher Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-5 right-4 sm:right-6 z-40 workspace-button shadow-sm"
          aria-label="Open AI Copilot"
        >
          <svg aria-hidden="true" className="h-4 w-4 text-blue-700" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 4h14v10H8l-5 3V4Z" /></svg>
          <span>AI Copilot</span>
          <kbd className="hidden sm:inline-block px-1.5 py-0.5 bg-gray-50 text-xs text-gray-500 rounded font-mono border border-gray-200">
            ⌘K
          </kbd>
        </button>
      )}

      {/* Slide-over Agent Drawer */}
      {isOpen && (
        <div role="complementary" aria-label="AI Copilot" className="workspace-page fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-white shadow-xl border-l border-gray-200 flex flex-col">
          {/* Header */}
          <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between bg-gray-50/70">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-gray-900 text-white flex items-center justify-center font-medium text-xs shadow-sm">
                AI
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-900">AI Copilot</h3>
                <p className="text-xs text-gray-500 truncate max-w-[240px]">
                  {getAccountLabel(account)} • {channel.toUpperCase()}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={handleClearHistory}
                title="Clear Chat History"
                aria-label="Clear chat history"
                className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md text-xs transition"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <button
                onClick={() => setIsOpen(false)}
                title="Close Drawer (Esc)"
                aria-label="Close AI Copilot"
                className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md text-xs transition"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages Container */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
              >
                <div className="flex items-center gap-1.5 mb-1 px-1">
                  <span className="text-xs font-medium text-gray-600">
                    {msg.role === 'user' ? (user || 'Operator') : 'Agent'}
                  </span>
                  <span className="text-xs text-gray-500">· {msg.timestamp}</span>
                </div>

                <div
                  className={`max-w-[92%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-gray-900 text-white'
                      : 'bg-gray-50 border border-gray-200 text-gray-800'
                  }`}
                >
                  {msg.isLoading ? (
                    <div className="flex items-center gap-2 py-1 text-gray-500">
                      <span className="w-2 h-2 rounded-full bg-gray-400" aria-hidden="true" />
                      <span>Working on your request…</span>
                    </div>
                  ) : msg.role === 'user' ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div>
                      {/* Action Badges */}
                      {msg.actions_taken && msg.actions_taken.length > 0 && (
                        <div className="mb-2.5 flex flex-wrap gap-1.5">
                          {msg.actions_taken.map((act, idx) => (
                            <span
                              key={idx}
                              className="inline-flex items-center gap-2 px-2 py-1 bg-gray-50 text-gray-600 border border-gray-200 rounded text-xs font-mono"
                            >
                              <span>{act.tool}</span>
                              {act.target && <span className="text-blue-500">({act.target})</span>}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Formatted Content */}
                      <div>{formatMessageContent(msg.content)}</div>

                      {/* Interactive Suggested Action Chips */}
                      {msg.suggested_actions && msg.suggested_actions.length > 0 && (
                        <div className="mt-3 pt-2.5 border-t border-gray-200/80 flex flex-wrap gap-1.5">
                          <span className="w-full text-xs font-medium text-gray-600 mb-1">
                            Suggested next steps
                          </span>
                          {msg.suggested_actions.map((sug, idx) => (
                            <button
                              key={idx}
                              onClick={() => handleSend(sug)}
                              disabled={loading}
                              className="workspace-button text-left"
                            >
                              {sug}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Prompt Bar */}
          <div className="px-4 py-2 bg-gray-50 border-t border-gray-200/80 flex gap-1.5 overflow-x-auto text-nowrap scrollbar-none">
            <button
              onClick={() => handleSend('Check if template exists: Dear customer, your EMI is due.')}
              disabled={loading}
              className="workspace-button shrink-0"
            >
              Find a template
            </button>
            <button
              onClick={() => handleSend('How do I submit templates?')}
              disabled={loading}
              className="workspace-button shrink-0"
            >
              Submission help
            </button>
            <button
              onClick={() => handleSend('List rejected templates')}
              disabled={loading}
              className="workspace-button shrink-0"
            >
              Rejected templates
            </button>
            <button
              onClick={() => handleSend('Poll approval status')}
              disabled={loading}
              className="workspace-button shrink-0"
            >
              Check status
            </button>
            <button
              onClick={() => handleSend('Check why template emic_check_wa_07aug was rejected and fix it')}
              disabled={loading}
              className="workspace-button shrink-0"
            >
              Review a rejection
            </button>
          </div>

          {/* Input Box */}
          <div className="p-4 border-t border-gray-200 bg-white">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSend();
              }}
              className="flex items-end gap-2"
            >
              <div className="flex-1 relative">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Ask about a template or approval"
                  rows={2}
                  disabled={loading}
                  aria-label="Message AI Copilot"
                  className="workspace-input resize-none font-sans"
                />
                <span className="absolute bottom-1 right-2 text-xs text-gray-500 select-none">
                  ↵ Send
                </span>
              </div>
              <button
                type="submit"
                aria-label="Send message"
                disabled={!input.trim() || loading}
                className="h-10 px-3.5 bg-gray-900 hover:bg-black disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-lg text-xs font-medium flex items-center justify-center transition shadow-sm"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
