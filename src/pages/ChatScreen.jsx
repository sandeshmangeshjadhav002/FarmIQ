/**
 * ChatScreen — FarmIQ Multilingual Voice + Text Assistant.
 *
 * Supports Marathi (मराठी) and English. The active language follows the app
 * language (see src/i18n) and can also be switched from the header.
 * STT: Web Speech API (SpeechRecognition); if it is unavailable or fails with
 *      Chrome's "network" error, audio is recorded and transcribed server-side
 *      via POST /api/voice/transcribe (Groq Whisper).
 * TTS: Web Speech API (speechSynthesis) — real, not a demo.
 * Backend: POST /api/agent/chat (LLM tool planner + ML models).
 *
 * The voice flow:
 *  1. User taps mic → startListening() → interim transcript shown live.
 *  2. User taps mic again (or speech ends) → stopListening().
 *  3. Transcript shown in editable input; user may correct it.
 *  4. sendMessage() → POST /api/agent/chat with the active language.
 *  5. Response text rendered; speak() called for the answer.
 *  6. TTS controls: stop / listen.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import Icon from "@/components/common/Icon";
import TextInput from "@/components/common/TextInput";
import ScreenShell from "@/components/layout/ScreenShell";
import { apiPostChat } from "@/lib/apiClient";
import { DEFAULT_LANGUAGE, normalizeLanguage } from "@/i18n/language";
import useLanguage from "@/i18n/useLanguage";
import useSpeech from "@/hooks/useSpeech";

// ─────────────────────────────────────────────────────────────────────────────
// Backend intent → translation key (see chat.intent.* in the locale files).
// "unknown" has no label of its own.
// ─────────────────────────────────────────────────────────────────────────────
const INTENT_TO_KEY = {
  crop_recommendation: "crop",
  crop_selection: "crop",
  fertilizer_recommendation: "fertilizer",
  fertilizer: "fertilizer",
  irrigation: "irrigation",
  yield_prediction: "yield",
  yield: "yield",
  sensor_query: "sensor",
  sensors: "sensor",
  organic_farming: "organic",
  drought_management: "drought",
  weather: "weather",
  profile: "farm",
  farm_status: "farmPlan",
  navigation_help: "help",
  knowledge: "assistant",
  unknown: null,
};

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
  const { t } = useTranslation();
  return (
    <span
      className="flex items-center gap-1 py-0.5"
      aria-label={t("chat.typing")}
    >
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4] [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4] [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#9CB3A4]" />
    </span>
  );
}

function IntentBadge({ intent }) {
  const { t } = useTranslation();
  const key = INTENT_TO_KEY[intent];
  if (!key) return null;
  return (
    <span className="mb-1 inline-block rounded-full bg-[#EAF4EC] px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-wider text-[#216B45]">
      {t(`chat.intent.${key}`)}
    </span>
  );
}

function TTSControls({ speaking, onSpeak, onStop, listenLabel, stopLabel }) {
  return (
    <div className="ml-[42px] mt-1 flex items-center gap-2">
      {speaking ? (
        <button
          onClick={onStop}
          aria-label={stopLabel}
          className="flex items-center gap-1.5 rounded-full border border-[#C8DDD0] bg-white px-3 py-1.5 text-[10px] font-bold text-[#216B45]"
        >
          <span className="h-2 w-2 rounded-sm bg-[#216B45]" />
          {stopLabel}
        </button>
      ) : (
        <button
          onClick={onSpeak}
          aria-label={listenLabel}
          className="flex items-center gap-1.5 rounded-full border border-[#C8DDD0] bg-white px-3 py-1.5 text-[10px] font-bold text-[#216B45]"
        >
          <Icon name="bot" size={13} />
          {listenLabel}
        </button>
      )}
    </div>
  );
}

/**
 * Collapsible panel showing the farm data sources used to generate an answer.
 * Renders only when the agent response includes context (sensors, weather, etc.).
 */
function FarmDataPanel({ context, freshness, conflicts, missing, lang }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!context) return null;

  const hasAnything =
    context.farm || context.sensors || context.weather ||
    (context.predictions && Object.keys(context.predictions).length > 0) ||
    context.drought || context.organic;
  if (!hasAnything) return null;

  const fmt = (isoStr) => {
    if (!isoStr) return null;
    try {
      const d = new Date(isoStr);
      return d.toLocaleString(lang === "mr" ? "mr-IN" : "en-IN", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      });
    } catch { return null; }
  };

  const SourceRow = ({ label, value, timestamp, warn, demo }) => (
    <div className="flex items-start justify-between gap-2 py-1 border-b border-[#EDF1EE] last:border-0">
      <span className="text-[10px] font-semibold text-[#52675B] flex-1">{label}</span>
      <span className={`text-[10px] font-bold text-right ${warn ? "text-[#9A5E1A]" : "text-[#1D3A2A]"}`}>
        {value ?? "—"}
        {demo && <span className="ml-1 text-[8px] font-extrabold text-[#D99A2B]">{t("chat.farmData.demo")}</span>}
      </span>
      {timestamp && (
        <span className="text-[9px] text-[#9AA79F] whitespace-nowrap">{fmt(timestamp)}</span>
      )}
    </div>
  );

  return (
    <div className="ml-[42px] mt-1.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[9px] font-bold text-[#52675B] hover:text-[#216B45]"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[#9CB3A4]" />
        {open ? t("chat.farmData.hide") : t("chat.farmData.show")}
      </button>

      {open && (
        <div className="mt-2 rounded-[16px] border border-[#DDE6DF] bg-white/70 p-3 text-[10px] backdrop-blur-md space-y-1">

          {/* Farm profile */}
          {context.farm && (
            <SourceRow
              label={t("chat.farmData.farm")}
              value={[context.farm.current_crop, context.farm.location].filter(Boolean).join(" · ") || t("chat.farmData.onFile")}
              timestamp={freshness?.get_farm_profile}
            />
          )}

          {/* Sensors */}
          {context.sensors && (
            <>
              {context.sensors.soil_moisture != null && (
                <SourceRow
                  label={t("chat.farmData.soilMoisture")}
                  value={`${context.sensors.soil_moisture}%`}
                  timestamp={context.sensors.observed_at}
                  warn={context.sensors.freshness === "stale" || context.sensors.freshness === "offline"}
                  demo={context.sensors.is_demo}
                />
              )}
              {context.sensors.temperature != null && (
                <SourceRow
                  label={t("chat.farmData.temperature")}
                  value={`${context.sensors.temperature}°C`}
                  timestamp={context.sensors.observed_at}
                  demo={context.sensors.is_demo}
                />
              )}
              {context.sensors.humidity != null && (
                <SourceRow
                  label={t("chat.farmData.humidity")}
                  value={`${context.sensors.humidity}%`}
                  timestamp={context.sensors.observed_at}
                  demo={context.sensors.is_demo}
                />
              )}
            </>
          )}

          {/* Weather */}
          {context.weather && (
            <>
              {context.weather.temperature_c != null && (
                <SourceRow
                  label={t("chat.farmData.weatherTemp")}
                  value={`${context.weather.temperature_c}°C`}
                  timestamp={context.weather.observed_at}
                />
              )}
              {context.weather.forecast_rain_7d_mm != null && (
                <SourceRow
                  label={t("chat.farmData.rain7d")}
                  value={`${context.weather.forecast_rain_7d_mm} mm`}
                  timestamp={context.weather.observed_at}
                  warn
                />
              )}
            </>
          )}

          {/* ML predictions */}
          {Object.entries(context.predictions || {}).map(([domain, pred]) => (
            <SourceRow
              key={domain}
              label={t("chat.farmData.model", { domain })}
              value={pred.label ?? pred.prediction ?? "—"}
              timestamp={pred.as_of}
            />
          ))}

          {/* Drought assessment */}
          {context.drought && (
            <SourceRow
              label={t("chat.farmData.drought")}
              value={context.drought.drought_severity ?? t("chat.farmData.onFile")}
              timestamp={freshness?.get_drought_context}
            />
          )}

          {/* Organic guidance */}
          {context.organic && (
            <SourceRow
              label={t("chat.farmData.organic")}
              value={context.organic.crop ?? t("chat.farmData.onFile")}
              timestamp={freshness?.get_organic_guidance}
            />
          )}

          {/* Missing / conflicts */}
          {missing?.length > 0 && (
            <p className="pt-1 text-[9px] text-[#9A5E1A]">
              {t("chat.farmData.notAvailable")}
              {missing.join(", ")}
            </p>
          )}
          {conflicts?.length > 0 && (
            <p className="pt-1 text-[9px] text-[#9A5E1A]">
              {t("chat.farmData.conflict")}
            </p>
          )}
        </div>
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

export default function ChatScreen({
  navigate,
  openModule,
  language,
  openLanguages,
}) {
  const { t } = useTranslation();
  const { languages, changeLanguage } = useLanguage();

  // The assistant follows the app language. ``voiceLang`` is the normalised
  // "en" | "mr" code sent to the backend and to the speech engine.
  const voiceLang = normalizeLanguage(language) ?? DEFAULT_LANGUAGE;

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
  const [uiError, setUiError] = useState(null);

  const threadRef = useRef(null);

  // Seed greeting on mount / language change
  useEffect(() => {
    setMessages([{ id: "greet", sender: "ai", text: t("chat.greeting") }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const res = await apiPostChat("/api/agent/chat", {
        message: text,
        language: voiceLang,
        history,
      });

      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                pending: false,
                // Agent endpoint returns { answer, sections, intent, ... }
                text: res.answer || res.response_text || "",
                intent: res.intent,
                language: res.language || voiceLang,
                // Agent-specific fields for the Farm data panel
                context: res.context,
                freshness: res.freshness,
                conflicts: res.conflicts,
                missing: res.missing,
              }
            : m,
        ),
      );

      // Auto-play TTS — agent always speaks (no per-message speak flag)
      const responseText = res.answer || res.response_text;
      if (responseText) {
        speak(responseText, res.language || voiceLang);
      }
    } catch (err) {
      const friendly =
        err?.status === 401
          ? t("chat.errors.sessionExpired")
          : err?.status === 503
          ? t("chat.errors.unavailable")
          : err?.message || t("chat.errors.generic");
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
    ? t("chat.status.listening")
    : sending
    ? t("chat.status.processing")
    : t("chat.status.online");
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
              {t("chat.title")}
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
          {languages.map((l) => (
            <button
              key={l.code}
              onClick={() => changeLanguage(l.code)}
              aria-label={t("chat.switchTo", { label: l.nativeLabel })}
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
                    listenLabel={t("chat.listen")}
                    stopLabel={t("chat.stop")}
                    onSpeak={() => speak(msg.text, msg.language || voiceLang)}
                    onStop={stopSpeaking}
                  />
                )}
              {/* Follow-up hint */}
              {msg.follow_up && !msg.pending && (
                <p className="ml-[42px] mt-1 text-[10px] font-semibold text-[#7A8B82]">
                  {t("chat.followUp")}
                </p>
              )}
              {/* Farm data used — collapsible context panel */}
              {!msg.pending && !msg.isError && msg.id !== "greet" && msg.context && (
                <FarmDataPanel
                  context={msg.context}
                  freshness={msg.freshness}
                  conflicts={msg.conflicts}
                  missing={msg.missing}
                  lang={msg.language || voiceLang}
                />
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
            title={sttSupported ? undefined : t("chat.micUnsupported")}
            aria-label={
              listening ? t("chat.stopRecording") : t("chat.startVoice")
            }
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
              placeholder={t("chat.inputPlaceholder")}
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
              aria-label={t("chat.clearInput")}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[#F3F3F3] text-[#7A8B82]"
            >
              <Icon name="close" size={17} />
            </button>
          )}

          {/* Send */}
          <button
            aria-label={t("chat.send")}
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
            {t("chat.listeningHint")}
          </p>
        )}

        <p className="mt-2 text-center text-[9px] text-[#98A59E]">
          {t("chat.disclaimer")}
        </p>
      </div>
    </ScreenShell>
  );
}
