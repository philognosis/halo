import { useState, useRef, useEffect, useCallback } from 'react'
import { postChat } from '../api/client'
import type { ChatMessage, ChatIntent } from '../types'
import AdaptiveResponse from '../components/AdaptiveResponse'

let msgCounter = 0
function makeId() { return `msg-${++msgCounter}` }

const INTENT_STYLE: Record<ChatIntent, string> = {
  SEARCH:     'bg-blue-100 text-blue-800',
  SHORTLIST:  'bg-indigo-100 text-indigo-800',
  COMPARE:    'bg-purple-100 text-purple-800',
  TEAM_SHAPE: 'bg-teal-100 text-teal-800',
  STATUS:     'bg-orange-100 text-orange-800',
  GREETING:   'bg-gray-100 text-gray-600',
  UNKNOWN:    'bg-gray-100 text-gray-600',
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
        {content}
      </div>
    </div>
  )
}

function AssistantBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-full w-full">
        {msg.intent && (
          <span className={`mb-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${INTENT_STYLE[msg.intent]}`}>
            {msg.intent}
          </span>
        )}
        <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
          {msg.intent && msg.intent !== 'GREETING' && msg.intent !== 'UNKNOWN' && msg.data != null ? (
            <AdaptiveResponse
              intent={msg.intent}
              response={msg.content}
              data={msg.data}
            />
          ) : (
            <p className="text-sm text-gray-700 leading-relaxed">{msg.content}</p>
          )}
        </div>
        <p className="mt-1 px-1 text-xs text-gray-400">
          {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex gap-1 items-center h-4">
          {[0, 150, 300].map(delay => (
            <span
              key={delay}
              className="h-2 w-2 rounded-full bg-gray-400 animate-bounce"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: makeId(),
      role: 'assistant',
      content: 'Hi! I can help you search for candidates, compare people, shape teams, or check assignment status. What would you like to do?',
      intent: 'GREETING',
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [lastResult, setLastResult] = useState<ChatMessage | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || sending) return

    const userMsg: ChatMessage = {
      id: makeId(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setSending(true)

    try {
      const res = await postChat({ message: text })
      const assistantMsg: ChatMessage = {
        id: makeId(),
        role: 'assistant',
        content: res.response,
        intent: res.intent,
        data: res.data,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMsg])
      setLastResult(assistantMsg)
    } catch (e) {
      const errMsg: ChatMessage = {
        id: makeId(),
        role: 'assistant',
        content: `Error: ${e instanceof Error ? e.message : 'Something went wrong'}`,
        intent: 'UNKNOWN',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setSending(false)
      // Restore focus
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [input, sending])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-full gap-6 overflow-hidden -m-6">
      {/* Chat panel */}
      <div className="flex flex-1 flex-col min-w-0 border-r border-gray-200 bg-gray-50">
        {/* Message history */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.map(msg =>
            msg.role === 'user'
              ? <UserBubble key={msg.id} content={msg.content} />
              : <AssistantBubble key={msg.id} msg={msg} />
          )}
          {sending && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-gray-200 bg-white px-4 py-3">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about candidates, compare people, shape a team… (Enter to send)"
              className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || sending}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Send message"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <p className="mt-1.5 text-xs text-gray-400">Shift+Enter for new line · Enter to send</p>
        </div>
      </div>

      {/* Adaptive result panel */}
      <div className="hidden w-80 xl:w-96 flex-shrink-0 overflow-y-auto lg:flex flex-col bg-white">
        <div className="border-b border-gray-200 px-5 py-4">
          <h2 className="font-semibold text-gray-900">Result Panel</h2>
          <p className="text-xs text-gray-500 mt-0.5">Latest agent response</p>
        </div>
        <div className="flex-1 p-5">
          {lastResult ? (
            <AdaptiveResponse
              intent={lastResult.intent ?? 'UNKNOWN'}
              response={lastResult.content}
              data={lastResult.data}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center py-12">
              <div className="h-12 w-12 rounded-full bg-gray-100 flex items-center justify-center mb-3">
                <svg className="h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
              <p className="text-sm text-gray-500">Send a message to see adaptive results here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
