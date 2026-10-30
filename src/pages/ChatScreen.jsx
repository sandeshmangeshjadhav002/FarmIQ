/**
 * ChatScreen — FarmIQ Multilingual Voice + Text Assistant.
 *
 * Supports Marathi (primary) and English.
 * STT: Web Speech API (SpeechRecognition); if it is unavailable or fails with
 *      Chrome's "network" error, audio is recorded and transcribed server-side
 *      via POST /api/voice/transcribe (Groq Whisper).
 * TTS: Web Speech API (speechSynthesis) — real, not a demo.
 * Backend: POST /api/voice/chat (deterministic intent routing + ML models).
 *
 * The voice flow:
 *  1. User taps mic → startListening() → interim transcript shown live.
 *  2. User taps mic again (or speech ends) → stopListening().
 *  3. Transcript shown in editable input; user may correct it.
 *  4. sendMessage() → POST /api/voice/chat.
 *  5. Response text rendered; speak() called if response.speak === true.
 *  6. TTS controls: stop / repeat.
 */
import { useEffect, useRef, useState } from "react";

import Icon from "@/components/common/Icon";
import TextInput from "@/components/common/TextInput";
import ScreenShell from "@/components/layout/ScreenShell";
import { apiPost } from "@/lib/apiClient";
import {
  VOICE_LANGUAGES,
  DEFAULT_VOICE_LANG,
  toLangCode,
} from "@/lib/languageUtils";
import useSpeech from "@/hooks/useSpeech";

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function ChatBubble({ children, sender, isError }) {
  const isAi = sender === "ai";
  return (
    <div className={`flex gap-2.5 ${isAi ? "items-start" : "justify-end"}`}>
      {isAi && (
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#216B45] text-white">
          <Icon name="leaf" size={17} />
        </span>
      )}
      <div
        className={`max-w-[276px] rounded-[18px] px-4 py-3 text-[13px] leading-[1.55] backdrop-blur-md ${
          isAi
            ? `rounded-tl-md border border-white/30 bg-white/40 shadow-[0_3px_12px_rgba(31,57,44,.04)] ${
                isError ? "text-[#9B3B3B]" : "text-[#334A3D]"
              }`
            : "rounded-tr-md bg-[#216B45] text-white"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span
      className="flex items-center gap-1 py-0.5"
      aria-label="Assistant is typing"
    >
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4] [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4] [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4]" />
    </span>
  );
}

function IntentBadge({ intent }) {
  const INTENT_LABELS = {
    crop_recommendation: "Crop",
    fertilizer_recommendation: "Fertilizer",
    irrigation: "Irrigation",
    yield_prediction: "Yield",
    sensor_query: "Sensor",
    navigation_help: "Help",
    knowledge: "Assistant",
    unknown: null,
  };
  const label = INTENT_LABELS[intent];
  if (!label) return null;
  return (
    <span className="mb-1 inline-block rounded-full bg-[#EAF4EC] px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-wider text-[#216B45]">
      {label}
    </span>
  );
}

function TTSControls({ speaking, onSpeak, onStop, label }) {
  return (
    <div className="ml-[42px] mt-1 flex items-center gap-2">
      {speaking ? (
        <button
          onClick={onStop}
          aria-label="Stop speaking"
          className="flex items-center gap-1.5 rounded-full border border-[#C8DDD0] bg-white px-3 py-1.5 text-[10px] font-bold text-[#216B45]"
        >
          <span className="h-2 w-2 rounded-sm bg-[#216B45]" />
          {label.stop}
        </button>
      ) : (
        <button
          onClick={onSpeak}
          aria-label="Listen to answer"
          className="flex items-center gap-1.5 rounded-full border border-[#C8DDD0] bg-white px-3 py-1.5 text-[10px] font-bold text-[#216B45]"
        >
          <Icon name="bot" size={13} />
          {label.listen}
        </button>
      )}
    </div>
  );
}

function ErrorBanner({ message, onDismiss }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="mx-5 mb-2 flex items-start gap-2 rounded-2xl bg-[#FCE9E5] px-4 py-3 text-[11px] font-semibold text-[#9D4C3E]"
    >
      <Icon name="shield" size={15} className="mt-0.5 shrink-0" />
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} className="ml-2 shrink-0 font-extrabold">
          ✕
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main screen
// ─────────────────────────────────────────────────────────────────────────────

const GREETINGS = {
  mr: "नमस्कार! मी FarmIQ सहाय्यक आहे. पीक शिफारस, खत, सिंचन, उत्पादन अंदाज किंवा सेन्सर माहितीबद्दल विचारा.",
  en: "Hello! I am your FarmIQ assistant. Ask me about crop recommendation, fertilizer, irrigation, yield prediction, or sensor data.",
};

export default function ChatScreen({
  navigate,
  openModule,
  language,
  openLanguages,
}) {
  // Voice language — default Marathi; sync with app's display language
  const [voiceLang, setVoiceLang] = useState(
    () => toLangCode(language) || DEFAULT_VOICE_LANG,
  );

  // Keep voiceLang in sync when the app-level language changes
  useEffect(() => {
    const code = toLangCode(language);
    if (code) setVoiceLang(code);
  }, [language]);

  const {
    transcript,
    setTranscript,
    listening,
    sttError,
    sttSupported,
    startListening,
    stopListening,
    speaking,
    ttsError,
    ttsSupported,
    speak,
    stopSpeaking,
  } = useSpeech(voiceLang);

  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [voiceCtx, setVoiceCtx] = useState(null); // multi-turn slot context
  const [uiError, setUiError] = useState(null);

  const threadRef = useRef(null);

  // Seed greeting on mount / language change
  useEffect(() => {
    setMessages([
      { id: "greet", sender: "ai", text: GREETINGS[voiceLang] || GREETINGS.en },
    ]);
    setVoiceCtx(null);
  }, [voiceLang]);

  // Auto-scroll to bottom
  useEffect(() => {
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // When transcript changes (from STT), copy it to the text input
  useEffect(() => {
    if (transcript) setMessage(transcript);
  }, [transcript]);

  // ── send ────────────────────────────────────────────────────────────────
  const sendMessage = async () => {
    const text = (message || transcript).trim();
    if (!text || sending) return;

    // Stop mic if still listening
    if (listening) stopListening();
    // Stop TTS if playing
    if (speaking) stopSpeaking();

    setMessage("");
    setTranscript("");
    setUiError(null);

    const pendingId = `ai-${Date.now()}`;

    // Recent turns (oldest → newest) so the assistant can resolve a follow-up
    // such as "which medicine should I use for it?" against the previous
    // subject. Errors and the seeded greeting are not real conversation.
    const history = messages
      .filter((m) => !m.pending && !m.isError && m.id !== "greet" && m.text)
      .slice(-6)
      .map((m) => ({
        role: m.sender === "farmer" ? "farmer" : "assistant",
        text: m.text,
      }));

    setMessages((prev) => [
      ...prev,
      { id: `me-${Date.now()}`, sender: "farmer", text },
      { id: pendingId, sender: "ai", pending: true, text: "" },
    ]);
    setSending(true);

    try {
      const res = await apiPost("/api/voice/chat", {
        message: text,
        language: voiceLang,
        context: voiceCtx,
        history,
      });

      // Persist slot context for multi-turn collection
      const newCtx = res.follow_up
        ? { ...(voiceCtx || {}), ...(res.context || {}) }
        : null;
      setVoiceCtx(newCtx);

      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                pending: false,
                text: res.response_text,
                intent: res.intent,
                // The backend answers in the language of the question, which
                // may differ from the app's display language.
                language: res.language || voiceLang,
                follow_up: res.follow_up,
                prediction: res.prediction,
              }
            : m,
        ),
      );

      // Auto-play TTS when the response says to speak
      if (res.speak && res.response_text) {
        speak(res.response_text, res.language || voiceLang);
      }
    } catch (err) {
      const friendly =
        err?.status === 401
          ? "Your session expired. Please sign in again."
          : err?.status === 503
          ? "Assistant is not available right now. Please try again."
          : err?.message || "Something went wrong. Please try again.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? { ...m, pending: false, text: friendly, isError: true }
            : m,
        ),
      );
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleMicClick = () => {
    if (listening) stopListening();
    else startListening();
  };

  const canSend = (message.trim() || transcript.trim()).length > 0 && !sending;

  // ── header status ────────────────────────────────────────────────────────
  const statusLabel = listening
    ? voiceLang === "mr"
      ? "ऐकत आहे…"
      : "Listening…"
    : sending
    ? voiceLang === "mr"
      ? "प्रक्रिया करत आहे…"
      : "Processing…"
    : voiceLang === "mr"
    ? "ऑनलाइन आणि तयार"
    : "Online and ready";
  const statusColor = listening ? "#F5A623" : sending ? "#B0BEB5" : "#4BAA6E";

  return (
    <ScreenShell active="advisor" navigate={navigate}>
      {/* ── Header ── */}
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-white/20 bg-white/40 px-5 py-4 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[#216B45] text-white">
            <Icon name="bot" size={21} />
          </span>
          <div>
            <h1 className="text-[16px] font-extrabold text-[#193A2A]">
              FarmIQ Assistant
            </h1>
            <p className="flex items-center gap-1.5 text-[10px] font-semibold text-[#678073]">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: statusColor }}
              />
              {statusLabel}
            </p>
          </div>
        </div>

        {/* Language selector — Marathi / English only */}
        <div className="flex items-center gap-1 rounded-full border border-white/30 bg-white/40 p-1 backdrop-blur-md">
          {VOICE_LANGUAGES.map((l) => (
            <button
              key={l.code}
              onClick={() => setVoiceLang(l.code)}
              aria-label={`Switch to ${l.label}`}
              className={`rounded-full px-3 py-1.5 text-[10px] font-extrabold transition ${
                voiceLang === l.code
                  ? "bg-[#216B45] text-white shadow-sm"
                  : "text-[#52665B] hover:bg-[#F0F6F1]"
              }`}
            >
              {l.nativeLabel}
            </button>
          ))}
        </div>
      </header>

      {/* ── Warnings ── */}
      {ttsError && <ErrorBanner message={ttsError} />}

      {/* ── Message thread ── */}
      <div
        ref={threadRef}
        className="flex-1 space-y-4 overflow-y-auto px-5 py-6"
      >
        {messages.map((msg) =>
          msg.sender === "farmer" ? (
            <ChatBubble key={msg.id} sender="farmer">
              {msg.text}
            </ChatBubble>
          ) : (
            <div key={msg.id}>
              <ChatBubble sender="ai" isError={msg.isError}>
                {msg.pending ? (
                  <TypingDots />
                ) : (
                  <div>
                    {msg.intent && <IntentBadge intent={msg.intent} />}
                    <p className="whitespace-pre-line">{msg.text}</p>
                  </div>
                )}
              </ChatBubble>
              {/* Speak / stop controls for each completed assistant answer */}
              {ttsSupported &&
                !msg.pending &&
                !msg.isError &&
                msg.id !== "greet" && (
                  <TTSControls
                    speaking={speaking}
                    label={
                      voiceLang === "mr"
                        ? { listen: "ऐका", stop: "थांबा" }
                        : { listen: "Listen", stop: "Stop" }
                    }
                    onSpeak={() => speak(msg.text, msg.language || voiceLang)}
                    onStop={stopSpeaking}
                  />
                )}
              {/* Follow-up hint */}
              {msg.follow_up && !msg.pending && (
                <p className="ml-[42px] mt-1 text-[10px] font-semibold text-[#7A8B82]">
                  {voiceLang === "mr"
                    ? "अधिक माहिती द्या…"
                    : "Please provide the missing information…"}
                </p>
              )}
            </div>
          ),
        )}

        {/* Transcript preview (live STT) */}
        {listening && transcript && (
          <div className="flex justify-end">
            <div className="max-w-[276px] rounded-[18px] rounded-tr-md border border-dashed border-[#B5CFC0] bg-[#F4FAF6] px-4 py-3 text-[13px] text-[#334A3D] opacity-70">
              {transcript}
            </div>
          </div>
        )}
      </div>

      {/* ── Error banner above input ── */}
      {(uiError || sttError) && !listening && (
        <ErrorBanner
          message={uiError || sttError}
          onDismiss={() => {
            setUiError(null);
          }}
        />
      )}

      {/* ── Input bar ── */}
      <div className="sticky bottom-0 border-t border-white/20 bg-white/40 p-3 backdrop-blur-xl">
        <div className="flex items-end gap-2">
          {/* Microphone */}
          <button
            onClick={handleMicClick}
            disabled={!sttSupported}
            title={
              sttSupported
                ? undefined
                : "Speech recognition is not supported in this browser"
            }
            aria-label={listening ? "Stop recording" : "Start voice input"}
            aria-pressed={listening}
            className={`grid h-11 w-11 shrink-0 place-items-center rounded-full transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 ${
              listening
                ? "animate-pulse bg-[#C0392B] text-white"
                : "bg-[#E9F3EC] text-[#216B45]"
            }`}
          >
            <Icon name="mic" size={20} />
          </button>

          {/* Text input */}
          <div className="min-w-0 flex-1">
            <TextInput
              icon="sparkles"
              onChange={(v) => {
                setMessage(v);
                setTranscript(v);
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                voiceLang === "mr"
                  ? "FarmIQ ला विचारा किंवा माइक दाबा…"
                  : "Ask FarmIQ or tap the mic…"
              }
              value={message}
            />
          </div>

          {/* Cancel / clear */}
          {(message || transcript) && !sending && (
            <button
              onClick={() => {
                setMessage("");
                setTranscript("");
                stopListening();
              }}
              aria-label="Clear input"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[#F3F3F3] text-[#7A8B82]"
            >
              <Icon name="close" size={17} />
            </button>
          )}

          {/* Send */}
          <button
            aria-label="Send"
            disabled={!canSend}
            onClick={sendMessage}
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[#216B45] text-white shadow-md active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name="send" size={19} />
          </button>
        </div>

        {/* Listening indicator */}
        {listening && (
          <p
            className="mt-2 text-center text-[10px] font-bold text-[#C0392B]"
            role="status"
          >
            {voiceLang === "mr"
              ? "🎙 ऐकत आहे… थांबण्यासाठी माइक दाबा"
              : "🎙 Listening… tap the microphone to stop"}
          </p>
        )}

        <p className="mt-2 text-center text-[9px] text-[#98A59E]">
          {voiceLang === "mr"
            ? "FarmIQ चुका करू शकतो. महत्त्वाचे निर्णय तज्ञांशी तपासा."
            : "FarmIQ can make mistakes. Verify important farming decisions with an expert."}
        </p>
      </div>
    </ScreenShell>
  );
}
