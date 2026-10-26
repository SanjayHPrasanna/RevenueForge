import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, MessageCircle, Mic, MicOff, RotateCcw, Send, Sparkles, X } from "lucide-react";
import { ApiError, api } from "../lib/api";

type SpeechResult = { 0: { transcript: string }; isFinal: boolean };
type SpeechRecognitionEvent = Event & { resultIndex: number; results: ArrayLike<SpeechResult> };
type SpeechRecognitionInstance = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance;
type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

type ChatMessage = {
  role: "assistant" | "user";
  text: string;
  retry?: boolean;
};

/** Maahi's face, cropped from the welcome picture into a small round avatar. */
function MaahiAvatar({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <span aria-hidden className={`relative inline-block shrink-0 rounded-full bg-brand-50 bg-no-repeat ring-2 ring-white ${className}`}
      style={{ backgroundImage: "url(/brand/maahi-assistant.png)", backgroundSize: "420% auto", backgroundPosition: "66% 38%" }} />
  );
}

function MaahiWelcome({ listening, onSpeak, title, sub }: { listening: boolean; onSpeak: () => void; title: string; sub: string }) {
  return (
    <div className="shrink-0 px-3.5 pt-3">
      <div className="relative isolate aspect-[2.15] overflow-hidden rounded-2xl bg-brand-50 ring-1 ring-black/5">
        <img
          src="/brand/maahi-assistant.png"
          alt="Maahi, your RevenueForge assistant, ready to help with deals, clients, capabilities, and requirements."
          className="maahi-breathe absolute inset-0 z-10 h-full w-full object-cover object-[68%_30%]"
        />
        <div aria-hidden className="absolute inset-x-0 bottom-0 z-10 h-1/2 bg-gradient-to-t from-midnight-950/45 to-transparent" />
        <button
          type="button"
          onClick={onSpeak}
          aria-label={listening ? "Stop voice input" : "Speak with Maahi"}
          aria-pressed={listening}
          className="absolute bottom-2.5 left-2.5 z-20 flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full bg-white/90 px-3 text-[11.5px] font-semibold text-brand-950 shadow-lg backdrop-blur transition-all duration-200 hover:bg-white active:scale-95 focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-brand-500"
        >
          {listening ? <MicOff className="h-3.5 w-3.5 text-ember-600" aria-hidden /> : <Mic className="h-3.5 w-3.5" aria-hidden />}
          {listening ? "Stop listening" : "Speak with Maahi"}
          {listening && <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-ember-500 pulse-ember" aria-hidden />}
        </button>
      </div>
      <div className="px-0.5 pb-2.5 pt-3">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] leading-tight text-ink">
          {listening ? "I’m listening..." : title}
        </h2>
        <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
          {listening ? "Say your question and I’ll help you find an answer." : sub}
        </p>
      </div>
    </div>
  );
}

type Mode = "public" | "workspace";
const COPY: Record<Mode, { endpoint: string; title: (company?: string) => string; sub: string; intro: string; suggestions: string[]; note: string }> = {
  public: {
    endpoint: "/assistant/chat",
    title: () => "Ask Maahi about RevenueForge",
    sub: "I can help you find deals, clients, capabilities, requirements, and more.",
    intro: "Hi, I’m Maahi. Tell me what you’re working on and I’ll help you explore how RevenueForge fits.",
    suggestions: ["How does RevenueForge turn an RFP into a proposal?", "Can I use my own company data?", "What do I need to get started?"],
    note: "This chat may be processed by the configured AI provider. Please don’t share confidential information.",
  },
  workspace: {
    endpoint: "/assistant/workspace",
    title: (company) => `Ask Maahi about ${company || "your workspace"}`,
    sub: "I know your deals, capabilities, people, case studies and rates, and answer only from your company’s data.",
    intro: "Hi, I’m Maahi. Ask me about your deals or anything in your knowledge library.",
    suggestions: ["Which deals are due next, and how ready are they?", "What are the biggest gaps across our deals?", "Who on the team knows Kafka and is available?", "Which case studies fit a healthcare integration bid?"],
    note: "Answers use only your company’s workspace. Check key figures in the deal itself.",
  },
};

/** Light formatting for answers: **bold**, and lines starting with "-", "*" or "1." as a list. Text only, no HTML. */
function RichText({ text }: { text: string }) {
  const inline = (line: string) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong> : part,
    );
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const raw of text.split("\n")) {
    const m = raw.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    const list = !!m;
    const line = m ? m[1] : raw;
    const last = blocks[blocks.length - 1];
    if (last && last.list === list && (list || line.trim())) last.lines.push(line);
    else blocks.push({ list, lines: [line] });
  }
  return (
    <>
      {blocks.map((b, i) =>
        b.list ? (
          <ul key={i} className="my-1 space-y-0.5 pl-4 list-disc marker:text-brand-400">
            {b.lines.map((l, j) => <li key={j}>{inline(l)}</li>)}
          </ul>
        ) : (
          <p key={i} className="whitespace-pre-wrap [&:not(:first-child)]:mt-1.5">{inline(b.lines.join("\n").trim())}</p>
        ),
      )}
    </>
  );
}

export default function LandingAssistant({ mode = "public", company }: { mode?: Mode; company?: string }) {
  const copy = COPY[mode];
  const SUGGESTIONS = copy.suggestions;
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", text: copy.intro },
  ]);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [retryQuestion, setRetryQuestion] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const speechRef = useRef<SpeechRecognitionInstance | null>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open) {
      if (window.matchMedia("(min-width: 640px)").matches) inputRef.current?.focus();
      wasOpen.current = true;
    } else if (wasOpen.current) {
      launcherRef.current?.focus();
      wasOpen.current = false;
    }
  }, [open]);

  useEffect(() => {
    if (messages.length > 1 || loading) {
      messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, loading]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (!open) {
      speechRef.current?.stop();
      speechRef.current = null;
      setListening(false);
    }
  }, [open]);

  async function requestAnswer(question: string, history: ChatMessage[]) {
    setLoading(true);
    setRetryQuestion("");
    try {
      const conversation = history
        .slice(-8)
        .map(({ role, text }) => ({ role, content: text }));
      const result = await api.post<{ answer: string }>(copy.endpoint, {
        messages: [...conversation, { role: "user", content: question }],
      });
      setMessages((current) => [...current, { role: "assistant", text: result.answer }]);
    } catch (error) {
      const message = error instanceof ApiError
        ? error.message
        : "I couldn’t connect just now. Please try again in a moment.";
      setMessages((current) => [...current, { role: "assistant", text: message, retry: true }]);
      setRetryQuestion(question);
    } finally {
      setLoading(false);
    }
  }

  function sendMessage(text: string) {
    const question = text.trim();
    if (!question || loading) return;
    const history = messages.filter((message) => !message.retry);
    setMessages((current) => [...current, { role: "user", text: question }]);
    setInput("");
    setShowSuggestions(false);
    void requestAnswer(question, history);
  }

  function retry() {
    if (!retryQuestion || loading) return;
    const history = messages.filter((message) => !message.retry);
    setMessages(history);
    void requestAnswer(retryQuestion, history.slice(0, -1));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    sendMessage(input);
  }

  function toggleVoice() {
    if (listening) {
      speechRef.current?.stop();
      return;
    }
    const speechWindow = window as SpeechRecognitionWindow;
    const SpeechRecognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceError("Voice input isn’t available in this browser. You can type your question instead.");
      return;
    }

    setVoiceError("");
    const recognition = new SpeechRecognition();
    speechRef.current = recognition;
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .filter((result) => result.isFinal)
        .map((result) => result[0].transcript)
        .join(" ");
      if (transcript) setInput((current) => `${current} ${transcript}`.trim());
    };
    recognition.onerror = () => {
      setVoiceError("I couldn’t hear that clearly. Please try again or type your question.");
    };
    recognition.onend = () => {
      setListening(false);
      speechRef.current = null;
    };
    try {
      recognition.start();
      setListening(true);
    } catch {
      setVoiceError("Voice input couldn’t start. Please type your question instead.");
      speechRef.current = null;
    }
  }

  return (
    <>
      {open && (
        <section
          id="landing-assistant-panel"
          aria-label="Maahi, RevenueForge assistant"
          aria-modal="false"
          className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden bg-white anim-scale-in origin-bottom-right sm:inset-auto sm:bottom-5 sm:right-5 sm:h-[min(580px,calc(100dvh-2.5rem))] sm:w-[340px] sm:rounded-[22px] sm:border sm:border-line/70 sm:shadow-float"
          role="dialog"
        >
          <header className="flex shrink-0 items-center gap-2.5 border-b border-line-soft bg-white/90 px-3.5 py-2.5 backdrop-blur">
            <span className="relative">
              <MaahiAvatar className="h-8 w-8" />
              <span aria-hidden className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-ok ring-2 ring-white" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-semibold leading-tight text-ink">Maahi</div>
              <div className="mt-0.5 text-[11px] text-ink-muted">RevenueForge AI assistant</div>
            </div>
            <button
              type="button"
              aria-label="Close assistant"
              onClick={() => setOpen(false)}
              className="grid h-8 w-8 place-items-center rounded-full text-ink-muted transition-colors hover:bg-line-soft hover:text-ink"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </header>

          <div ref={messagesRef} className="scroll-thin min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain bg-white" aria-live="polite">
            <MaahiWelcome listening={listening} onSpeak={toggleVoice} title={copy.title(company)} sub={copy.sub} />
            <div className="space-y-3 px-3.5 pb-3.5">
              {messages.length === 1 && (
                <div className="flex items-start gap-2 rounded-2xl bg-paper px-3 py-2.5 text-[12px] leading-relaxed text-ink-soft">
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden />
                  <p>{copy.intro}</p>
                </div>
              )}
              {messages.map((message, index) => index === 0 && message.role === "assistant" ? null : (
                <div key={`${index}-${message.role}`} className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
                  <div
                    className={
                      message.role === "user"
                        ? "max-w-[85%] rounded-[18px] rounded-br-md bg-gradient-to-b from-brand-600 to-brand-700 px-3 py-2 text-[13px] leading-relaxed text-white shadow-[0_4px_12px_-6px_rgba(8,43,61,.5)] anim-fade-in"
                        : "max-w-[90%] rounded-[18px] rounded-bl-md bg-paper px-3 py-2 text-[13px] leading-relaxed text-ink anim-fade-in"
                    }
                  >
                    {message.role === "assistant" ? <RichText text={message.text} /> : <p className="whitespace-pre-wrap">{message.text}</p>}
                    {message.retry && (
                      <button type="button" onClick={retry} className="mt-1.5 inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-brand-700 hover:text-brand-900">
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                        Try again
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="flex justify-start" role="status" aria-label="Maahi is thinking">
                  <div className="flex items-center gap-1.5 rounded-[18px] rounded-bl-md bg-paper px-3.5 py-2.5">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.2s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.1s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500" />
                  </div>
                </div>
              )}

              {showSuggestions && (
                <div className="space-y-1.5 pt-0.5">
                  <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Try asking</div>
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => sendMessage(suggestion)}
                      disabled={loading}
                      className="block max-w-full rounded-full border border-line bg-white px-3 py-1.5 text-left text-[12px] text-ink-soft transition-all duration-200 hover:border-brand-200 hover:bg-brand-50 hover:text-brand-800"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="shrink-0 bg-white px-3 pb-2.5 pt-2">
            {voiceError && <p role="status" className="mb-2 text-[11px] leading-snug text-fit-gap-ink">{voiceError}</p>}
            <form onSubmit={onSubmit} className="flex items-center gap-1 rounded-full border border-line bg-paper pl-4 pr-1 py-1 transition-all focus-within:border-brand-400 focus-within:bg-white focus-within:ring-4 focus-within:ring-brand-500/10">
              <label className="sr-only" htmlFor="landing-assistant-input">Ask Maahi a question</label>
              <input
                ref={inputRef}
                id="landing-assistant-input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask Maahi a question"
                maxLength={500}
                disabled={loading}
                className="h-8 min-w-0 flex-1 border-0 bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none focus:ring-0"
              />
              <button
                type="button"
                onClick={toggleVoice}
                aria-label={listening ? "Stop voice input" : "Start voice input"}
                className={listening ? "grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700" : "grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-soft hover:bg-line-soft"}
              >
                {listening ? <MicOff className="h-4 w-4" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
              </button>
              <button
                type="submit"
                disabled={!input.trim() || loading}
                aria-label="Send message"
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-700 text-white transition-all hover:bg-brand-800 active:scale-95 disabled:cursor-not-allowed disabled:bg-line"
              >
                {loading ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/50 border-t-white" /> : <ArrowRight className="h-4 w-4" aria-hidden />}
              </button>
            </form>
            <p className="mt-1.5 text-center text-[9.5px] leading-snug text-ink-faint">{copy.note}</p>
          </div>
        </section>
      )}

      {!open && mode === "workspace" && (
        <button
          ref={launcherRef}
          type="button"
          aria-expanded={open}
          aria-controls="landing-assistant-panel"
          aria-label="Ask Maahi about your workspace"
          title="Ask Maahi"
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-40 grid h-12 w-12 place-items-center rounded-full bg-gradient-to-b from-brand-800 to-brand-950 p-[3px] shadow-[0_12px_30px_-8px_rgba(3,15,23,.55)] ring-1 ring-white/10 transition-all duration-300 ease-apple hover:-translate-y-0.5 hover:scale-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-200"
        >
          <MaahiAvatar className="h-full w-full ring-white/30" />
          <span aria-hidden className="absolute -bottom-0 -right-0 h-3 w-3 rounded-full bg-ok ring-2 ring-white" />
        </button>
      )}

      {!open && mode === "public" && (
        <button
          ref={launcherRef}
          type="button"
          aria-expanded={open}
          aria-controls="landing-assistant-panel"
          onClick={() => setOpen(true)}
          className="group fixed bottom-5 right-5 z-50 flex h-12 items-center gap-2 rounded-full bg-gradient-to-b from-brand-800 to-brand-950 pl-1.5 pr-4 text-white shadow-[0_12px_30px_-8px_rgba(3,15,23,.55)] ring-1 ring-white/10 transition-all duration-300 ease-apple hover:-translate-y-0.5 hover:shadow-[0_16px_36px_-8px_rgba(3,15,23,.6)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-200"
        >
          <span className="relative">
            <MaahiAvatar className="h-9 w-9 ring-white/30" />
            <span aria-hidden className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-ok ring-2 ring-brand-900" />
          </span>
          <MessageCircle className="sr-only" aria-hidden />
          <span className="text-[13.5px] font-semibold">Ask Maahi</span>
        </button>
      )}
    </>
  );
}
