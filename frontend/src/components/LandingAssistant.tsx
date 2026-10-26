import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Bot, MessageCircle, Mic, MicOff, RotateCcw, Send, Sparkles, X } from "lucide-react";
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

function MaahiWelcome({ listening, onSpeak }: { listening: boolean; onSpeak: () => void }) {
  return (
    <div className="shrink-0 px-4 pt-3">
      <div className="relative isolate aspect-[1.48] overflow-hidden rounded-xl border border-line bg-[#E8F5F2]">
        <img
          src="/brand/maahi-assistant.png"
          alt="Maahi, your RevenueForge assistant, ready to help with deals, clients, capabilities, and requirements."
          className="absolute inset-0 z-10 h-full w-full object-cover"
        />
        <button
          type="button"
          onClick={onSpeak}
          aria-label={listening ? "Stop voice input" : "Speak with Maahi"}
          aria-pressed={listening}
          className="absolute bottom-3 left-1/2 z-20 flex min-h-9 -translate-x-1/2 items-center gap-2 whitespace-nowrap rounded-full bg-brand-950 px-4 text-[12px] font-semibold text-white shadow-lg transition-colors hover:bg-brand-800 focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-brand-500"
        >
          {listening ? <MicOff className="h-4 w-4" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
          {listening ? "Stop listening" : "Speak with Maahi"}
        </button>
      </div>
      <div className="px-1 pb-3 pt-4">
        <h2 className="font-display text-[20px] font-medium leading-tight text-brand-950">
          {listening ? "I’m listening..." : "Ask Maahi about RevenueForge"}
        </h2>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
          {listening ? "Say your question and I’ll help you find an answer." : "I can help you find deals, clients, capabilities, requirements, and more."}
        </p>
      </div>
    </div>
  );
}

const SUGGESTIONS = [
  "How does RevenueForge turn an RFP into a proposal?",
  "Can I use my own company data?",
  "What do I need to get started?",
];

export default function LandingAssistant() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", text: "Hi, I’m Maahi, RevenueForge’s AI assistant. Ask me anything about how RevenueForge can help with your bids." },
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
      const result = await api.post<{ answer: string }>("/assistant/chat", {
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
          className="fixed inset-0 z-50 flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden border-l border-line bg-white shadow-[-14px_0_42px_rgba(8,43,61,.12)] sm:left-auto sm:w-[min(400px,100vw)]"
          role="dialog"
        >
          <header className="flex shrink-0 items-center gap-3 border-b border-line-soft bg-white px-4 py-3.5">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-brand-50 text-brand-700">
              <Bot className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-semibold leading-tight text-ink">Maahi</div>
              <div className="mt-1 text-[11.5px] text-ink-muted">RevenueForge AI assistant</div>
            </div>
            <button
              type="button"
              aria-label="Close assistant"
              onClick={() => setOpen(false)}
              className="grid h-9 w-9 place-items-center rounded-lg text-ink-muted hover:bg-line-soft hover:text-ink"
            >
              <X className="h-5 w-5" aria-hidden />
            </button>
          </header>

          <div ref={messagesRef} className="scroll-thin min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain bg-white" aria-live="polite">
            <MaahiWelcome listening={listening} onSpeak={toggleVoice} />
            <div className="space-y-4 px-4 pb-4">
              {messages.length === 1 && (
                <div className="mb-2 flex items-start gap-2.5 rounded-xl bg-brand-50/70 p-3 text-[12.5px] leading-relaxed text-ink-soft">
                  <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden />
                  <p>Hi, I’m Maahi. Tell me what you’re working on and I’ll help you explore how RevenueForge fits.</p>
                </div>
              )}
              {messages.map((message, index) => index === 0 && message.role === "assistant" ? null : (
                <div key={`${index}-${message.role}`} className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
                  <div
                    className={
                      message.role === "user"
                        ? "max-w-[88%] rounded-2xl rounded-br-md bg-brand-700 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-white"
                        : "max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-white px-3.5 py-2.5 text-[13.5px] leading-relaxed text-ink shadow-card"
                    }
                  >
                    <p className="whitespace-pre-wrap">{message.text}</p>
                    {message.retry && (
                      <button type="button" onClick={retry} className="mt-2.5 inline-flex items-center gap-1.5 font-semibold text-brand-700 hover:text-brand-900">
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                        Try again
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="flex justify-start" role="status" aria-label="Maahi is thinking">
                  <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-line bg-white px-4 py-3 shadow-card">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.2s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.1s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500" />
                  </div>
                </div>
              )}

              {showSuggestions && (
                <div className="space-y-2 pt-1">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                    <Sparkles className="h-3.5 w-3.5 text-ember-500" aria-hidden />
                    Suggested questions
                  </div>
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => sendMessage(suggestion)}
                      disabled={loading}
                      className="block max-w-full rounded-full border border-brand-200 bg-white px-3 py-1.5 text-left text-[12.5px] text-brand-800 transition-colors hover:border-brand-400 hover:bg-brand-50"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="shrink-0 border-t border-line-soft bg-white px-4 pb-3 pt-2.5">
            {voiceError && <p role="status" className="mb-2 text-[11px] leading-snug text-fit-gap-ink">{voiceError}</p>}
            <form onSubmit={onSubmit} className="flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-1.5 focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-100">
              <label className="sr-only" htmlFor="landing-assistant-input">Ask Maahi a question</label>
              <input
                ref={inputRef}
                id="landing-assistant-input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask Maahi a question"
                maxLength={500}
                disabled={loading}
                className="h-9 min-w-0 flex-1 border-0 bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none focus:ring-0"
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
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-700 text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:bg-line"
              >
                {loading ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/50 border-t-white" /> : <ArrowRight className="h-4 w-4" aria-hidden />}
              </button>
            </form>
            <p className="mt-2 text-center text-[10px] leading-relaxed text-ink-faint">This chat may be processed by the configured AI provider. Please don’t share confidential information.</p>
          </div>
        </section>
      )}

      {!open && (
        <button
          ref={launcherRef}
          type="button"
          aria-expanded={open}
          aria-controls="landing-assistant-panel"
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-50 flex h-14 items-center gap-2.5 rounded-full bg-brand-800 px-5 text-white shadow-[0_8px_24px_rgba(8,43,61,.28)] transition-colors hover:bg-brand-950 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-200"
        >
          <MessageCircle className="h-5 w-5" aria-hidden />
          <span className="text-[14px] font-semibold">Ask Maahi</span>
        </button>
      )}
    </>
  );
}
