/**
 * useSpeech — native STT + TTS for FarmIQ (Capacitor Android/iOS + web fallback).
 *
 * On Android/iOS (Capacitor native):
 *   STT: @capacitor-community/speech-recognition  → Android SpeechRecognizer API
 *   TTS: @capacitor-community/text-to-speech      → Android TextToSpeech API
 *
 * On desktop browser (development / web preview):
 *   STT: window.SpeechRecognition (Chrome / Edge); if it is unavailable or
 *        fails (e.g. Chrome's "network" error because its cloud recognizer is
 *        unreachable), audio is recorded with MediaRecorder and transcribed
 *        server-side via POST /api/voice/transcribe (Groq Whisper).
 *   TTS: window.speechSynthesis.
 *
 * Server-side TTS fallback (both platforms):
 *   Windows desktops and stock Android devices frequently have no Marathi
 *   (mr-IN) or Hindi (hi-IN) voice, and local engines then read Devanagari
 *   text as silence. When no installed voice can pronounce the answer, it is
 *   synthesised by POST /api/voice/speak and played as an audio element.
 *
 * Language codes:
 *   "mr" → "mr-IN"  (Marathi)
 *   "en" → "en-IN"  (English, India)
 *
 * Usage:
 *   const { transcript, setTranscript, listening, sttError, sttSupported,
 *           startListening, stopListening,
 *           speaking, ttsError, ttsSupported,
 *           speak, stopSpeaking, repeatLast,
 *           isNative } = useSpeech(langCode)
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { apiPostBlob, apiUpload } from "@/lib/apiClient";

const LANG_MAP = { mr: "mr-IN", en: "en-IN" };

// Is this running inside a Capacitor native app?
const IS_NATIVE =
  typeof window !== "undefined" && !!window.Capacitor?.isNativePlatform?.();

// ─────────────────────────────────────────────────────────────────────────────
// Capability detection
// ─────────────────────────────────────────────────────────────────────────────
const hasWebTTS = typeof window !== "undefined" && "speechSynthesis" in window;

function getWebSttClass() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

const HAS_WEB_STT = !!getWebSttClass();

// Can we record raw audio and send it to the server for transcription?
const HAS_MEDIA_RECORDER =
  typeof window !== "undefined" &&
  typeof window.MediaRecorder !== "undefined" &&
  !!navigator.mediaDevices?.getUserMedia;

// Preferred container/codecs for the upload. Whisper accepts webm/opus, ogg
// and mp4; pick the first one this browser can actually produce.
const RECORDER_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
  "audio/mp4",
];

const RECORDING_MAX_MS = 20000;

// ─────────────────────────────────────────────────────────────────────────────
// Capacitor plugin loaders (lazy — only used on native)
// ─────────────────────────────────────────────────────────────────────────────
let _sttPlugin = null;
let _ttsPlugin = null;

async function getSttPlugin() {
  if (_sttPlugin) return _sttPlugin;
  const mod = await import("@capacitor-community/speech-recognition");
  _sttPlugin = mod.SpeechRecognition;
  return _sttPlugin;
}

async function getTtsPlugin() {
  if (_ttsPlugin) return _ttsPlugin;
  const mod = await import("@capacitor-community/text-to-speech");
  _ttsPlugin = mod.TextToSpeech;
  return _ttsPlugin;
}

// ─────────────────────────────────────────────────────────────────────────────
// Text preparation for TTS
// ─────────────────────────────────────────────────────────────────────────────

/** Strip Markdown / bullets so the voice does not read "**" or "•" aloud. */
function sanitizeForSpeech(text) {
  return String(text ?? "")
    .replace(/\*\*(.*?)\*\*/g, "$1") // **bold** → bold
    .replace(/[*_`#>]/g, "") // stray markdown punctuation
    .replace(/^[\s•\-–]+/gm, "") // leading bullets / dashes
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Split text into sentence-sized chunks. Chrome silently stops speaking a
 * single utterance after ~15 s; short chunks avoid the truncation bug and
 * let speechSynthesis queue them back-to-back.
 */
function chunkForSpeech(text, max = 180) {
  const parts = text.match(/[^.!?।]+[.!?।]*/g) || [text];
  const chunks = [];
  let cur = "";
  for (const part of parts) {
    const next = `${cur} ${part}`.trim();
    if (next.length > max && cur) {
      chunks.push(cur);
      cur = part.trim();
    } else {
      cur = next;
    }
  }
  if (cur) chunks.push(cur);
  return chunks.length ? chunks : [text];
}

// ─────────────────────────────────────────────────────────────────────────────
// Voice list loading.
// Chrome returns an empty array from getVoices() until the async
// "voiceschanged" event fires — a very common cause of silent TTS. Cache the
// list and wait for it once.
// ─────────────────────────────────────────────────────────────────────────────

// Fallback chains. Most Windows/Android devices ship an Indian-English voice
// and often a Hindi voice, but frequently none for Marathi. Hindi reads
// Devanagari, so it is a usable fallback for Marathi text.
const VOICE_CHAIN = {
  mr: ["mr", "hi", "en-in", "en"],
  en: ["en-in", "en"],
};

let _voices = [];
let _voicesPromise = null;

function loadVoices() {
  if (!hasWebTTS) return Promise.resolve([]);
  const now = window.speechSynthesis.getVoices();
  if (now && now.length) {
    _voices = now;
    return Promise.resolve(now);
  }
  if (_voicesPromise) return _voicesPromise;

  _voicesPromise = new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      _voices = window.speechSynthesis.getVoices() || [];
      window.speechSynthesis.onvoiceschanged = null;
      _voicesPromise = null;
      resolve(_voices);
    };
    window.speechSynthesis.onvoiceschanged = finish;
    // Some engines never fire voiceschanged — poll briefly, then give up.
    let tries = 0;
    const timer = setInterval(() => {
      if ((window.speechSynthesis.getVoices() || []).length || ++tries > 20) {
        clearInterval(timer);
        finish();
      }
    }, 150);
  });
  return _voicesPromise;
}

function pickVoice(chain) {
  for (const prefix of chain) {
    const hit = _voices.find((v) =>
      (v.lang || "").toLowerCase().startsWith(prefix),
    );
    if (hit) return hit;
  }
  return null;
}

// Devanagari codepoints (Marathi, Hindi, Nepali, Sanskrit). Text containing
// them can only be read aloud by a Devanagari-capable voice.
const DEVANAGARI_RE = /[\u0900-\u097F]/;

/**
 * Can this voice actually pronounce `text`? Windows desktops and stock
 * Android devices usually ship only English voices, and asking those to read
 * Devanagari produces silence instead of an error — so the check is explicit.
 */
function voiceCanRead(voice, text) {
  if (!DEVANAGARI_RE.test(text)) return true;
  return !!voice && /^(mr|hi|ne|sa)/i.test(voice.lang || "");
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────
export default function useSpeech(langCode = "mr") {
  const bcp47 = LANG_MAP[langCode] || "mr-IN";

  const [transcript, setTranscript] = useState("");
  const [listening, setListening] = useState(false);
  const [sttError, setSttError] = useState(null);
  const [speaking, setSpeaking] = useState(false);
  const [ttsError, setTtsError] = useState(null);

  const webRecRef = useRef(null); // Web Speech recognition instance
  const webStopRef = useRef(null); // safety timer id
  const mediaRef = useRef(null); // { recorder, stream, chunks, timer }
  const lastRef = useRef({ text: "", lang: langCode }); // for repeatLast()
  const serverAudioRef = useRef(null); // { audio, finish } while server TTS plays
  const serverAbortRef = useRef(false); // true once the user presses Stop

  const sttSupported = IS_NATIVE || HAS_WEB_STT || HAS_MEDIA_RECORDER;
  const ttsSupported = IS_NATIVE || hasWebTTS;

  // Warm the voice cache as soon as the hook mounts (web only).
  useEffect(() => {
    if (!IS_NATIVE && hasWebTTS) loadVoices();
  }, []);

  // Reset transient errors when the language changes.
  useEffect(() => {
    setSttError(null);
    setTtsError(null);
  }, [langCode]);

  const _clearWebTimer = () => {
    if (webStopRef.current) {
      clearTimeout(webStopRef.current);
      webStopRef.current = null;
    }
  };

  // Tear down an in-flight MediaRecorder without uploading anything.
  const _releaseMedia = (stopRecorder) => {
    const ctx = mediaRef.current;
    if (!ctx) return;
    if (ctx.timer) clearTimeout(ctx.timer);
    if (stopRecorder) {
      try {
        ctx.recorder.onstop = null;
      } catch {
        /* detached */
      }
      try {
        if (ctx.recorder.state !== "inactive") ctx.recorder.stop();
      } catch {
        /* not started */
      }
    }
    try {
      ctx.stream.getTracks().forEach((t) => t.stop());
    } catch {
      /* tracks gone */
    }
    mediaRef.current = null;
  };

  // ── TTS: server-side audio playback ──────────────────────────────────────
  // Used when no installed voice can pronounce the answer (typically Marathi).
  // The text is synthesised by POST /api/voice/speak and played here.

  /** Play one audio blob. Resolves when it ends, rejects on error or abort. */
  const _playServerAudio = (blob) =>
    new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      let settled = false;
      const finish = (err) => {
        if (settled) return;
        settled = true;
        if (serverAudioRef.current?.finish === finish) {
          serverAudioRef.current = null;
        }
        URL.revokeObjectURL(url);
        if (err) reject(err);
        else resolve();
      };
      audio.onended = () => finish(null);
      audio.onerror = () =>
        finish(new Error("The browser could not play the audio."));
      serverAudioRef.current = { audio, finish };
      audio.play().catch(finish);
    });

  /** Stop any server audio and settle the promise awaiting it. */
  const _abortServerAudio = () => {
    serverAudioRef.current?.finish(new Error("aborted"));
  };

  /**
   * Synthesise `text` on the server and play it. Returns true when audio was
   * played (or the user stopped it), false when the server could not help —
   * in which case `ttsError` explains why.
   */
  const _serverSpeak = useCallback(async (text, langKey) => {
    serverAbortRef.current = false;
    setSpeaking(true);
    try {
      // The endpoint caps text at 2000 characters; chat answers are far
      // shorter, but long ones are spoken as consecutive parts.
      for (const part of chunkForSpeech(text, 1800)) {
        if (serverAbortRef.current) break;
        const blob = await apiPostBlob("/api/voice/speak", {
          text: part,
          language: langKey,
        });
        if (!blob.size) throw new Error("The server returned no audio.");
        await _playServerAudio(blob);
      }
    } catch (err) {
      setSpeaking(false);
      if (serverAbortRef.current) {
        serverAbortRef.current = false;
        return true; // the user pressed Stop — not a failure
      }
      setTtsError(
        err?.message || "Could not play the spoken answer. Please try again.",
      );
      return false;
    }
    serverAbortRef.current = false;
    setSpeaking(false);
    return true;
  }, []);

  // ── STT: server-side transcription of recorded audio (Groq Whisper) ──────
  const _uploadForTranscription = useCallback(
    async (blob) => {
      try {
        const form = new FormData();
        const type = blob.type || "audio/webm";
        const ext = type.includes("ogg")
          ? "ogg"
          : type.includes("mp4")
          ? "mp4"
          : "webm";
        form.append("file", blob, `speech.${ext}`);
        form.append("language", langCode);

        const data = await apiUpload("/api/voice/transcribe", form);
        const text = (data?.text || "").trim();
        if (text) setTranscript(text);
        else setSttError("No speech detected. Please try again.");
      } catch (err) {
        if (err?.status === 503) {
          setSttError(
            "Voice transcription is not configured on the server. Please type your message.",
          );
        } else {
          setSttError(
            err?.message ||
              "Could not transcribe your speech. Please try again or type your message.",
          );
        }
      }
    },
    [langCode],
  );

  /**
   * Record the microphone with MediaRecorder and transcribe the clip on the
   * server. Used when the browser has no built-in speech recognizer (Firefox,
   * Safari) or when it fails with Chrome's "network" error.
   */
  const _recordAndTranscribe = useCallback(async () => {
    if (!HAS_MEDIA_RECORDER) {
      setSttError(
        "Speech recognition is not available in this browser. Use Chrome or Edge, or type your message.",
      );
      return;
    }

    setSttError(null);
    if (mediaRef.current) _releaseMedia(true); // never leak a previous stream
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType =
        RECORDER_MIME_TYPES.find((m) =>
          window.MediaRecorder.isTypeSupported?.(m),
        ) || "";
      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      const chunks = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size) chunks.push(e.data);
      };
      recorder.onstop = async () => {
        if (mediaRef.current?.timer) clearTimeout(mediaRef.current.timer);
        mediaRef.current = null;
        setListening(false);
        try {
          stream.getTracks().forEach((t) => t.stop());
        } catch {
          /* tracks gone */
        }

        const blob = new Blob(chunks, {
          type: chunks[0]?.type || mimeType || "audio/webm",
        });
        if (!blob.size) {
          setSttError("No audio captured. Please try again.");
          return;
        }
        await _uploadForTranscription(blob);
      };

      mediaRef.current = { recorder, stream, chunks, timer: null };
      setListening(true);
      recorder.start();
      mediaRef.current.timer = setTimeout(() => {
        try {
          if (recorder.state !== "inactive") recorder.stop();
        } catch {
          /* stopped */
        }
      }, RECORDING_MAX_MS);
    } catch (err) {
      const name = err?.name || "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setSttError(
          "Microphone access denied. Allow microphone permission in your browser.",
        );
      } else if (name === "NotFoundError") {
        setSttError("No microphone found on this device.");
      } else {
        setSttError(`Could not access the microphone: ${err?.message || err}`);
      }
      _releaseMedia(true);
      setListening(false);
    }
  }, [_uploadForTranscription]);

  // ── STT: native listeners (registered once, removed on unmount) ──────────
  useEffect(() => {
    if (!IS_NATIVE) return;
    let handles = [];
    (async () => {
      try {
        const STT = await getSttPlugin();
        const partial = await STT.addListener(
          "partialResults",
          ({ matches }) => {
            const t = matches?.[0];
            if (t) setTranscript(t);
          },
        );
        const state = await STT.addListener("listeningState", ({ status }) => {
          if (status === "stopped") setListening(false);
        });
        handles = [partial, state];
      } catch {
        // plugin unavailable — errors surface when startListening() is called
      }
    })();
    return () => {
      handles.forEach((h) => h?.remove?.());
    };
  }, []);

  // ── STT: start ────────────────────────────────────────────────────────────
  const startListening = useCallback(async () => {
    setSttError(null);
    setTranscript("");

    if (IS_NATIVE) {
      // ── Native Android path ──────────────────────────────────────────
      try {
        const STT = await getSttPlugin();

        const perm = await STT.requestPermission();
        const granted =
          perm?.speechRecognition === "granted" ||
          perm?.speechRecognition === "prompt-with-rationale" ||
          perm === "granted" ||
          perm?.granted === true;

        if (!granted) {
          setSttError(
            "Microphone permission denied. Please allow it in Settings → Apps → FarmIQ → Permissions.",
          );
          return;
        }

        setListening(true);
        // start() resolves with the final matches once recognition finishes.
        const res = await STT.start({
          language: bcp47,
          maxResults: 1,
          prompt: langCode === "mr" ? "बोला…" : "Speak now…",
          partialResults: true,
          popup: false,
        });
        const final = res?.matches?.[0];
        if (final) setTranscript(final);
      } catch (err) {
        const msg = (err?.message || String(err)).toLowerCase();
        if (msg.includes("permission")) {
          setSttError("Microphone permission required for voice input.");
        } else if (msg.includes("language")) {
          setSttError(
            `Marathi (mr-IN) speech recognition not available on this device. ` +
              "Install a Marathi language pack in Android Settings → General Management → Language.",
          );
        } else if (!msg.includes("no match") && !msg.includes("cancel")) {
          setSttError(`Speech recognition failed: ${err?.message || err}`);
        }
      } finally {
        setListening(false);
      }
      return;
    }

    // ── Web Speech API (browser) ───────────────────────────────────────
    const SpeechRecognitionClass = getWebSttClass();
    if (!SpeechRecognitionClass) {
      // No built-in recognizer (Firefox / Safari): record and let the server
      // transcribe the clip instead.
      await _recordAndTranscribe();
      return;
    }

    let fellBack = false;
    const rec = new SpeechRecognitionClass();
    rec.lang = bcp47;
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onstart = () => setListening(true);
    rec.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++)
        text += e.results[i][0].transcript;
      setTranscript(text.trim());
    };
    rec.onerror = (e) => {
      const code = e.error;
      setListening(false);
      if (code === "not-allowed" || code === "service-not-allowed") {
        setSttError(
          "Microphone access denied. Allow microphone permission in your browser.",
        );
      } else if (code === "language-not-supported") {
        setSttError(`Language ${bcp47} is not supported by this browser.`);
      } else if (code === "no-speech") {
        setSttError("No speech detected. Please try again.");
      } else if (code === "network") {
        // Chrome proxies Web Speech audio to Google; when that endpoint is
        // unreachable it reports "network". Fall back to recording locally and
        // transcribing server-side instead of giving up.
        fellBack = true;
        webRecRef.current = null;
        _recordAndTranscribe();
      } else if (code !== "aborted") {
        setSttError(`Recognition error: ${code}`);
      }
    };
    rec.onend = () => {
      _clearWebTimer();
      // When we handed off to the recorder, keep the "listening" state it set.
      if (!fellBack) setListening(false);
      webRecRef.current = null;
    };

    webRecRef.current = rec;
    try {
      rec.start();
      // Safety net: never stay "listening" forever if onend does not fire.
      _clearWebTimer();
      webStopRef.current = setTimeout(() => {
        try {
          rec.stop();
        } catch {
          /* already stopped */
        }
      }, 20000);
    } catch (err) {
      webRecRef.current = null;
      setSttError(`Could not start microphone: ${err.message}`);
    }
  }, [bcp47, langCode, _recordAndTranscribe]);

  // ── STT: stop ─────────────────────────────────────────────────────────────
  const stopListening = useCallback(async () => {
    _clearWebTimer();
    if (IS_NATIVE) {
      try {
        const STT = await getSttPlugin();
        const res = await STT.stop();
        const final = res?.matches?.[0];
        if (final) setTranscript(final);
      } catch {
        // stop() rejects when not listening — safe to ignore
      }
    } else if (mediaRef.current) {
      try {
        if (mediaRef.current.recorder.state !== "inactive")
          mediaRef.current.recorder.stop();
      } catch {
        /* already stopped — onstop still uploads */
      }
    } else if (webRecRef.current) {
      try {
        webRecRef.current.stop();
      } catch {
        /* not started */
      }
    }
    setListening(false);
  }, []);

  // ── TTS: speak ────────────────────────────────────────────────────────────
  const speak = useCallback(
    async (text, overrideLang) => {
      const clean = sanitizeForSpeech(text);
      if (!clean) return;

      const langKey = LANG_MAP[overrideLang] ? overrideLang : langCode;
      const lang = LANG_MAP[langKey] || bcp47;
      setTtsError(null);
      lastRef.current = { text, lang: langKey };

      if (!ttsSupported) {
        setTtsError("Text-to-speech is not available on this device.");
        return;
      }

      if (IS_NATIVE) {
        // ── Native Android TTS ─────────────────────────────────────────
        // A device may have Hindi but no Marathi voice, and Hindi reads
        // Devanagari fine, so try each locale before giving up.
        const chain =
          langKey === "mr" ? ["mr-IN", "hi-IN"] : ["en-IN", "en-US"];

        let played = false;
        let lastError = null;
        try {
          const TTS = await getTtsPlugin();

          // Ask the engine which locales are installed: speak() with a missing
          // locale either throws or stays silent, so filter the chain first.
          let installed = null;
          try {
            const res = await TTS.getSupportedLanguages();
            installed = (res?.languages || []).map((l) => l.toLowerCase());
          } catch {
            installed = null; // method unavailable — just attempt the chain
          }
          const candidates =
            installed && installed.length
              ? chain.filter((c) => installed.includes(c.toLowerCase()))
              : chain;

          if (candidates.length) {
            await TTS.stop();
            setSpeaking(true);
            for (const candidate of candidates) {
              try {
                await TTS.speak({
                  text: clean,
                  lang: candidate,
                  rate: 0.95,
                  pitch: 1.0,
                  volume: 1.0,
                });
                played = true;
                break;
              } catch (err) {
                lastError = err;
              }
            }
          }
        } catch (err) {
          lastError = err;
        }
        setSpeaking(false);

        if (!played) {
          // No usable voice on the device — let the server synthesise it.
          const handled = await _serverSpeak(clean, langKey);
          if (!handled) {
            const msg = (
              lastError?.message || String(lastError || "")
            ).toLowerCase();
            setTtsError(
              msg.includes("language") ||
                msg.includes("locale") ||
                msg.includes("voice")
                ? "No voice installed for this language. Android Settings → General Management → Text-to-speech → Install voice data."
                : `Speech playback failed: ${lastError?.message || lastError}`,
            );
          }
        }
        return;
      }

      // ── Web Speech API TTS ───────────────────────────────────────────
      if (!_voices.length) await loadVoices();
      const voice = pickVoice(VOICE_CHAIN[langKey] || VOICE_CHAIN.en);

      // No installed voice can pronounce this text — the usual case for
      // Marathi on Windows, where the only voices are English. Synthesise it
      // on the server rather than letting speechSynthesis stay silent.
      if (!voiceCanRead(voice, clean)) {
        await _serverSpeak(clean, langKey);
        return;
      }

      const synth = window.speechSynthesis;
      synth.cancel();
      if (synth.paused) synth.resume();

      if (!_voices.length) {
        setTtsError("No text-to-speech voices are installed on this system.");
        return;
      }

      const chunks = chunkForSpeech(clean);
      let finished = 0;

      setSpeaking(true);
      chunks.forEach((chunk) => {
        const utt = new SpeechSynthesisUtterance(chunk);
        utt.lang = lang;
        if (voice) utt.voice = voice;
        utt.rate = 0.95;
        utt.pitch = 1.0;
        utt.volume = 1.0;
        utt.onend = () => {
          finished += 1;
          if (finished >= chunks.length) setSpeaking(false);
        };
        utt.onerror = (e) => {
          finished += 1;
          const code = e?.error;
          if (code && code !== "interrupted" && code !== "canceled") {
            setTtsError(`Speech playback failed: ${code}`);
          }
          if (finished >= chunks.length) setSpeaking(false);
        };
        synth.speak(utt);
      });

      // Browsers that require a user gesture may silently drop the request.
      setTimeout(() => {
        if (!synth.speaking && !synth.pending) setSpeaking(false);
      }, 1500);
    },
    [langCode, bcp47, ttsSupported, _serverSpeak],
  );

  // ── TTS: stop ─────────────────────────────────────────────────────────────
  const stopSpeaking = useCallback(async () => {
    serverAbortRef.current = true;
    _abortServerAudio();
    if (IS_NATIVE) {
      try {
        const TTS = await getTtsPlugin();
        await TTS.stop();
      } catch {
        /* nothing speaking */
      }
    } else if (hasWebTTS) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
  }, []);

  const repeatLast = useCallback(() => {
    const { text, lang } = lastRef.current;
    if (text) speak(text, lang);
  }, [speak]);

  // Stop audio / recognition when the component unmounts.
  useEffect(
    () => () => {
      _clearWebTimer();
      _releaseMedia(true);
      try {
        webRecRef.current?.abort?.();
      } catch {
        /* ignore */
      }
      serverAbortRef.current = true;
      _abortServerAudio();
      if (hasWebTTS) window.speechSynthesis.cancel();
    },
    [],
  );

  return {
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
    repeatLast,
    isNative: IS_NATIVE,
  };
}
