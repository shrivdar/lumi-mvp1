"use client";

import { useEffect, useState, useRef, useCallback, use } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Chat, Message, AgentTrace, HitlRequest, IntegrationCall, ClarifyQuestion } from "@/lib/types";
import { ChatList } from "@/components/chat/chat-list";
import { ChatMessage } from "@/components/chat/message";
import { ClarifyCard } from "@/components/chat/clarify-card";
import { AgentActivityGroup } from "@/components/chat/agent-activity-group";
import { HitlCard } from "@/components/chat/hitl-card";
import { IntegrationCard } from "@/components/chat/integration-card";
import { AgentsPanel } from "@/components/panels/agents-panel";
import { PlanPanel } from "@/components/panels/plan-panel";
import { ToolsPanel } from "@/components/panels/tools-panel";
import { ReviewPanel } from "@/components/panels/review-panel";
import type { ReviewData } from "@/components/panels/review-panel";
import { ConfidencePanel } from "@/components/panels/confidence-panel";
import { ThemeToggle } from "@/components/theme-toggle";
import { Send, PanelRightOpen, PanelRightClose, FlaskConical, User, ChevronRight, Gauge } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import clsx from "clsx";


type LiveEvent =
  | { kind: "trace"; trace: AgentTrace }
  | { kind: "hitl_flag"; hitl: HitlRequest }
  | { kind: "hitl_resolved"; hitl: HitlRequest }
  | { kind: "integration"; call: IntegrationCall };

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: chatId } = use(params);
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode") || "mock";
  const [chat, setChat] = useState<Chat | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [rightOpen, setRightOpen] = useState(true);
  const [pipelineOpen, setPipelineOpen] = useState(true);
  const [confidenceOpen, setConfidenceOpen] = useState(true);
  const [agentsOpen, setAgentsOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(true);
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[] | null>(null);
  const [pendingQuery, setPendingQuery] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewData | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getChat(chatId).then(setChat).catch(() => {
      window.location.href = "/";
    });
    api.listChats().then(setChats);
  }, [chatId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chat?.messages, streamText, liveEvents, clarifyQuestions]);

  useEffect(() => {
    if (chat && chat.messages.length === 1 && chat.messages[0].role === "user") {
      const query = chat.messages[0].content;
      // Fetch clarifying questions before starting the pipeline
      api.clarify(chatId, query, mode).then((res) => {
        if (res.questions.length > 0) {
          setTimeout(() => {
            setPendingQuery(query);
            setClarifyQuestions(res.questions);
          }, 1200);
        } else {
          runStream(query);
        }
      }).catch(() => {
        // If clarify fails, just run the stream directly
        runStream(query);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat?.id]);

  const runStream = useCallback(async (content: string) => {
    setStreaming(true);
    setStreamText("");
    setLiveEvents([]);

    try {
    for await (const event of api.sendMessage(chatId, content, mode)) {
      switch (event.type) {
        case "trace_start":
          setLiveEvents((prev) => [...prev, { kind: "trace", trace: event.trace }]);
          break;
        case "tool_call":
          setLiveEvents((prev) =>
            prev.map((e) =>
              e.kind === "trace" && e.trace.agent_id === event.agent_id
                ? { kind: "trace", trace: { ...e.trace, tools_called: [...e.trace.tools_called, event.tool] } }
                : e
            )
          );
          break;
        case "trace_complete":
          setLiveEvents((prev) =>
            prev.map((e) =>
              e.kind === "trace" && e.trace.agent_id === event.trace.agent_id
                ? { kind: "trace", trace: event.trace }
                : e
            )
          );
          break;
        case "hitl_flag": {
          setLiveEvents((prev) => [...prev, { kind: "hitl_flag", hitl: event.hitl }]);
          // Auto-open review panel in sidebar
          setActiveReview({
            finding: event.hitl.finding,
            agent: event.hitl.agent_id,
            confidence: event.hitl.confidence_score ?? 0,
            reason: event.hitl.reason,
            findingId: event.hitl.finding_id || "review_001",
            chatId,
          });
          setRightOpen(true);
          break;
        }
        case "hitl_resolved":
          setLiveEvents((prev) =>
            prev.map((e) =>
              e.kind === "hitl_flag" && e.hitl.finding_id === event.hitl.finding_id
                ? { kind: "hitl_resolved", hitl: event.hitl }
                : e
            )
          );
          break;
        case "integration":
          setLiveEvents((prev) => [...prev, { kind: "integration", call: event.call }]);
          break;
        case "text_delta":
          setStreamText((prev) => prev + event.delta);
          break;
        case "done": {
          const updated = await api.getChat(chatId);
          setChat(updated);
          setStreamText("");
          setStreaming(false);
          api.listChats().then(setChats);
          break;
        }
      }
    }
    } catch (err) {
      console.error("[SSE] Stream error:", err);
      setStreaming(false);
    }
  }, [chatId, mode]);

  function handleClarifySubmit(answers: Record<string, string>) {
    if (!pendingQuery) return;
    const answerLines = Object.entries(answers)
      .filter(([, v]) => v.trim())
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n");
    const enrichedQuery = answerLines
      ? `${pendingQuery}\n\nAdditional context:\n${answerLines}`
      : pendingQuery;
    setClarifyQuestions(null);
    setPendingQuery(null);
    runStream(enrichedQuery);
  }

  function handleClarifySkip() {
    if (!pendingQuery) return;
    setClarifyQuestions(null);
    const query = pendingQuery;
    setPendingQuery(null);
    runStream(query);
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    const text = input.trim();
    setInput("");

    const userMsg: Message = {
      id: crypto.randomUUID().slice(0, 8),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
      agent_traces: [],
      hitl_events: [],
      integration_events: [],
      expert_review_messages: [],
      sublab: null,
    };
    setChat((prev) => prev ? { ...prev, messages: [...prev.messages, userMsg] } : prev);

    // Show clarifying questions for follow-up messages too
    try {
      const res = await api.clarify(chatId, text, mode);
      if (res.questions.length > 0) {
        await new Promise((r) => setTimeout(r, 1200));
        setPendingQuery(text);
        setClarifyQuestions(res.questions);
        return;
      }
    } catch {
      // If clarify fails, proceed directly
    }
    await runStream(text);
  }

  // Separate live events by kind for rendering
  const liveTracesFromEvents = liveEvents
    .filter((e): e is Extract<LiveEvent, { kind: "trace" }> => e.kind === "trace")
    .map((e) => e.trace);
  const liveHitlEvents = liveEvents.filter(
    (e): e is Extract<LiveEvent, { kind: "hitl_flag" | "hitl_resolved" }> =>
      e.kind === "hitl_flag" || e.kind === "hitl_resolved"
  );
  const liveIntegrationEvents = liveEvents.filter(
    (e): e is Extract<LiveEvent, { kind: "integration" }> => e.kind === "integration"
  );

  // Confidence panel data: prefer live events while streaming, else the latest
  // assistant message's persisted traces + HITL events.
  const latestAssistant = [...(chat?.messages ?? [])]
    .reverse()
    .find((m) => m.role === "assistant");
  const confidenceTraces: AgentTrace[] =
    liveTracesFromEvents.length > 0 ? liveTracesFromEvents : latestAssistant?.agent_traces ?? [];
  const confidenceHitl: HitlRequest[] =
    liveHitlEvents.length > 0 ? liveHitlEvents.map((e) => e.hitl) : latestAssistant?.hitl_events ?? [];

  if (!chat) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-[var(--text-muted)]">
          <span className="flex gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--accent)] typing-dot" />
            <span className="h-2 w-2 rounded-full bg-[var(--accent)] typing-dot" />
            <span className="h-2 w-2 rounded-full bg-[var(--accent)] typing-dot" />
          </span>
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left sidebar */}
      <aside className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-card)] flex flex-col">
        <div className="p-4 border-b border-[var(--border)]">
          <a href="/" className="text-sm font-semibold text-[var(--text)] tracking-tight hover:opacity-80 transition-opacity">
            Lumi
          </a>
        </div>
        <ChatList chats={chats} activeChatId={chatId} />
        {/* User & Settings */}
        <div className="shrink-0 border-t border-[var(--border)] p-3 space-y-0.5">
          <ThemeToggle />
          <div className="flex items-center gap-2.5 rounded-lg px-3 py-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--accent)] text-white">
              <User size={12} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-[var(--text)]">John Doe</p>
              <p className="text-[10px] text-[var(--text-muted)]">Computational Biology</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Center — Chat */}
      <main className="flex-1 flex flex-col min-w-0 bg-[var(--bg)]">
        <header className="shrink-0 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-card)] px-6 py-3">
          <div className="animate-fade-in">
            <h2 className="text-sm font-medium truncate text-[var(--text)]">{chat.title}</h2>
            <p className="text-xs text-[var(--text-muted)] capitalize">{chat.sublab.replace(/-/g, " ")}</p>
          </div>
          <button
            onClick={() => setRightOpen(!rightOpen)}
            className="rounded-lg p-1.5 text-[var(--text-muted)] transition-all hover:bg-[var(--bg-hover)] hover:text-[var(--text)] active:scale-90"
          >
            {rightOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          </button>
        </header>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {chat.messages.map((msg, i) => (
            <ChatMessage key={msg.id} message={msg} index={i} />
          ))}

          {/* Clarifying questions */}
          {clarifyQuestions && (
            <ClarifyCard
              questions={clarifyQuestions}
              onSubmit={handleClarifySubmit}
              onSkip={handleClarifySkip}
            />
          )}

          {/* Live streaming — assistant message layout */}
          {streaming && (
            <div className="msg-assistant animate-fade-in">
              <div className="msg-assistant-avatar">
                <FlaskConical size={14} />
              </div>

              <div className={clsx("msg-assistant-content space-y-3", streamText && "streaming-indicator")}>
                {/* Thinking indicator */}
                {liveEvents.length === 0 && !streamText && (
                  <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                    <span className="flex gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                    </span>
                    Thinking...
                  </div>
                )}

                {/* Agent traces — grouped by division */}
                {liveTracesFromEvents.length > 0 && (
                  <AgentActivityGroup traces={liveTracesFromEvents} isLive />
                )}

                {/* HITL events */}
                {liveHitlEvents.length > 0 && (
                  <div className="space-y-2">
                    {liveHitlEvents.map((e, i) => (
                      <HitlCard
                        key={`h-${i}`}
                        hitl={e.hitl}
                        onReview={e.hitl.status === "pending" ? () => {
                          setActiveReview({
                            finding: e.hitl.finding,
                            agent: e.hitl.agent_id,
                            confidence: e.hitl.confidence_score ?? 0,
                            reason: e.hitl.reason,
                            findingId: e.hitl.finding_id || "review_001",
                            chatId,
                          });
                          setRightOpen(true);
                        } : undefined}
                      />
                    ))}
                  </div>
                )}

                {/* Integration events */}
                {liveIntegrationEvents.length > 0 && (
                  <div className="space-y-2">
                    {liveIntegrationEvents.map((e, i) => (
                      <IntegrationCard key={`i-${i}`} call={e.call} />
                    ))}
                  </div>
                )}

                {/* Streaming markdown */}
                {streamText && (
                  <div className="chat-markdown text-sm">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamText}</ReactMarkdown>
                  </div>
                )}

                {/* Typing indicator while streaming text */}
                {streamText && (
                  <div className="flex items-center gap-2">
                    <span className="flex gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] typing-dot" />
                    </span>
                    <span className="text-xs text-[var(--text-muted)]">Synthesizing report...</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="shrink-0 border-t border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="relative max-w-3xl mx-auto">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Follow up..."
              rows={2}
              disabled={streaming}
              className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3 pr-12 text-sm outline-none transition-all duration-200 focus:border-[var(--border-focus)] focus:ring-2 focus:ring-[var(--border-focus)] focus:ring-opacity-20 placeholder:text-[var(--text-muted)] disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || streaming}
              className="absolute right-3 bottom-3 flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white transition-all disabled:opacity-30 hover:bg-[var(--accent-dark)] hover:scale-105 active:scale-95"
            >
              <Send size={15} />
            </button>
          </div>
        </div>
      </main>

      {/* Right panel — stacked sections */}
      <aside
        className={clsx(
          "shrink-0 border-l border-[var(--border)] bg-[var(--bg-card)] flex flex-col transition-all duration-300 ease-out overflow-hidden",
          rightOpen ? "w-80 opacity-100" : "w-0 opacity-0 border-l-0"
        )}
      >
        <div className="w-80 flex flex-col h-full">
          {activeReview ? (
            <ReviewPanel review={activeReview} onClose={() => setActiveReview(null)} />
          ) : (
            <div className="flex-1 overflow-y-auto">
              {/* Pipeline */}
              <div className="border-b border-[var(--border)]">
                <button
                  onClick={() => setPipelineOpen(!pipelineOpen)}
                  className="flex w-full items-center gap-1.5 p-4 pb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                >
                  <ChevronRight size={12} className={clsx("transition-transform duration-200", pipelineOpen && "rotate-90")} />
                  Pipeline
                </button>
                <div className={clsx("grid transition-[grid-template-rows] duration-200 ease-out", pipelineOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden">
                    <div className="px-4 pb-4 pt-1">
                      <PlanPanel liveTraces={liveTracesFromEvents} streaming={streaming} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Confidence */}
              <div className="border-b border-[var(--border)]">
                <button
                  onClick={() => setConfidenceOpen(!confidenceOpen)}
                  className="flex w-full items-center gap-1.5 p-4 pb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                >
                  <ChevronRight size={12} className={clsx("transition-transform duration-200", confidenceOpen && "rotate-90")} />
                  <Gauge size={12} className="-ml-0.5" />
                  Confidence
                </button>
                <div className={clsx("grid transition-[grid-template-rows] duration-200 ease-out", confidenceOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden">
                    <div className="px-4 pb-4 pt-1">
                      <ConfidencePanel traces={confidenceTraces} hitlEvents={confidenceHitl} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Agents */}
              <div className="border-b border-[var(--border)]">
                <button
                  onClick={() => setAgentsOpen(!agentsOpen)}
                  className="flex w-full items-center gap-1.5 p-4 pb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                >
                  <ChevronRight size={12} className={clsx("transition-transform duration-200", agentsOpen && "rotate-90")} />
                  Agents
                </button>
                <div className={clsx("grid transition-[grid-template-rows] duration-200 ease-out", agentsOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden">
                    <div className="px-4 pb-4 pt-1">
                      <AgentsPanel sublab={chat.sublab} liveTraces={liveTracesFromEvents} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Tools */}
              <div>
                <button
                  onClick={() => setToolsOpen(!toolsOpen)}
                  className="flex w-full items-center gap-1.5 p-4 pb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                >
                  <ChevronRight size={12} className={clsx("transition-transform duration-200", toolsOpen && "rotate-90")} />
                  Tools
                </button>
                <div className={clsx("grid transition-[grid-template-rows] duration-200 ease-out", toolsOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden">
                    <div className="px-4 pb-4 pt-1">
                      <ToolsPanel />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
