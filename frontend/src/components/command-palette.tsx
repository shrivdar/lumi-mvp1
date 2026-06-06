"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Chat } from "@/lib/types";
import {
  Search,
  Plus,
  ShieldCheck,
  MessagesSquare,
  Sun,
  Moon,
  MessageSquare,
  CornerDownLeft,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import clsx from "clsx";

interface Action {
  id: string;
  label: string;
  hint?: string;
  icon: React.ReactNode;
  keywords?: string;
  run: () => void;
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [chats, setChats] = useState<Chat[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
  }, []);

  const toggleTheme = useCallback(() => {
    const isLight = document.documentElement.getAttribute("data-theme") === "light";
    if (isLight) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("lumi-theme", "dark");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem("lumi-theme", "light");
    }
  }, []);

  // Global ⌘K / Ctrl+K shortcut + Esc to close.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        close();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Load recent chats lazily when the palette opens.
  useEffect(() => {
    if (open) {
      api.listChats().then(setChats).catch(() => setChats([]));
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const isDark = useMemo(() => {
    if (typeof document === "undefined") return true;
    return document.documentElement.getAttribute("data-theme") !== "light";
  }, [open]);

  const actions = useMemo<Action[]>(() => {
    const base: Action[] = [
      {
        id: "new-query",
        label: "New research query",
        hint: "Home",
        keywords: "create start home landing query research",
        icon: <Plus size={15} />,
        run: () => router.push("/"),
      },
      {
        id: "hitl",
        label: "Open Human Review (HITL)",
        hint: "Expert routing",
        keywords: "human in the loop hitl expert review queue confidence",
        icon: <ShieldCheck size={15} />,
        run: () => router.push("/hitl"),
      },
      {
        id: "review",
        label: "Open Review panel",
        hint: "Adversarial review",
        keywords: "adversarial review panel methodology evidence synthesis",
        icon: <MessagesSquare size={15} />,
        run: () => router.push("/review"),
      },
      {
        id: "theme",
        label: isDark ? "Switch to light theme" : "Switch to dark theme",
        hint: "Theme",
        keywords: "theme dark light mode appearance toggle",
        icon: isDark ? <Sun size={15} /> : <Moon size={15} />,
        run: toggleTheme,
      },
    ];

    const chatActions: Action[] = chats.slice(0, 8).map((c) => ({
      id: `chat-${c.id}`,
      label: c.title || "Untitled research",
      hint: c.sublab ? c.sublab.replace(/-/g, " ") : "Chat",
      keywords: `chat ${c.title} ${c.sublab}`,
      icon: <MessageSquare size={15} />,
      run: () => router.push(`/chat/${c.id}`),
    }));

    return [...base, ...chatActions];
  }, [chats, isDark, router, toggleTheme]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter(
      (a) => `${a.label} ${a.hint ?? ""} ${a.keywords ?? ""}`.toLowerCase().includes(q)
    );
  }, [actions, query]);

  // Keep the active index in range as the filtered list changes.
  useEffect(() => {
    setActive((i) => (filtered.length === 0 ? 0 : Math.min(i, filtered.length - 1)));
  }, [filtered.length]);

  const execute = useCallback(
    (action: Action | undefined) => {
      if (!action) return;
      action.run();
      // Theme toggle keeps the palette open for repeated toggling feedback; navigation closes it.
      if (action.id !== "theme") close();
    },
    [close]
  );

  function onListKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (filtered.length ? (i + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      execute(filtered[active]);
    }
  }

  // Scroll the active row into view.
  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  if (!open) return null;

  const recentStart = filtered.findIndex((a) => a.id.startsWith("chat-"));

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[18vh] animate-fade-in"
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onListKey}
        className="relative w-full max-w-xl overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-2xl animate-scale-in"
      >
        {/* Search input */}
        <div className="flex items-center gap-2.5 border-b border-[var(--border)] px-4 py-3">
          <Search size={16} className="shrink-0 text-[var(--text-muted)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="Search actions, chats…"
            className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-muted)]"
          />
          <kbd className="hidden shrink-0 rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--text-muted)] sm:inline">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-1.5">
          {filtered.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-[var(--text-muted)]">No matching commands</p>
          ) : (
            filtered.map((a, i) => {
              const showRecentHeader = recentStart !== -1 && i === recentStart;
              return (
                <div key={a.id}>
                  {showRecentHeader && (
                    <p className="px-4 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                      Recent chats
                    </p>
                  )}
                  <button
                    data-idx={i}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => execute(a)}
                    className={clsx(
                      "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors",
                      i === active ? "bg-[var(--accent-light)]" : "hover:bg-[var(--bg-hover)]"
                    )}
                  >
                    <span
                      className={clsx(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-colors",
                        i === active
                          ? "bg-[var(--accent)] text-white"
                          : "bg-[var(--bg-hover)] text-[var(--text-secondary)]"
                      )}
                    >
                      {a.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-[var(--text)]">{a.label}</span>
                    </span>
                    {a.hint && (
                      <span className="shrink-0 text-[10px] capitalize text-[var(--text-muted)]">{a.hint}</span>
                    )}
                    {i === active && (
                      <CornerDownLeft size={13} className="shrink-0 text-[var(--accent)] animate-fade-in" />
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Footer hints */}
        <div className="flex items-center gap-3 border-t border-[var(--border)] px-4 py-2 text-[10px] text-[var(--text-muted)]">
          <span className="flex items-center gap-1">
            <ArrowUp size={11} />
            <ArrowDown size={11} />
            Navigate
          </span>
          <span className="flex items-center gap-1">
            <CornerDownLeft size={11} />
            Select
          </span>
          <span className="ml-auto flex items-center gap-1">
            <kbd className="rounded border border-[var(--border)] px-1 py-0.5">⌘K</kbd>
            Command palette
          </span>
        </div>
      </div>
    </div>
  );
}
