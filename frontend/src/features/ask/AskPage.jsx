import { useCallback, useEffect, useRef, useState } from "react";
import {
  askBotanika,
  fetchVoiceStatus,
  interruptVoice,
  listenBotanika,
  speakBotanika,
} from "../../platform/api.js";

const ABSTENTION = "I could not find enough reliable offline information to answer that.";

export function AskPage({ ready, capabilities, localOperator = false, onNavigate }) {
  const knowledgeAvailable = Boolean(
    capabilities?.knowledge?.available ?? ready?.capabilities?.knowledge?.available,
  );
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [voice, setVoice] = useState(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState(null);
  const inputRef = useRef(null);

  const refreshVoice = useCallback(async () => {
    try {
      setVoice(await fetchVoiceStatus());
      setVoiceError(null);
    } catch (caught) {
      setVoiceError(caught.message);
    }
  }, []);

  useEffect(() => {
    refreshVoice();
    const interval = setInterval(refreshVoice, 15000);
    return () => clearInterval(interval);
  }, [refreshVoice]);

  const appendAnswer = useCallback((answer, playback = null) => {
    setMessages((current) => [
      ...current,
      {
        role: "guide",
        text: answer?.answer || ABSTENTION,
        citations: answer?.citations || [],
        abstained: Boolean(answer?.abstained),
        playback,
      },
    ]);
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    const value = question.trim();
    if (!value || busy || !knowledgeAvailable) return;
    setQuestion("");
    setMessages((current) => [...current, { role: "user", text: value }]);
    setBusy(true);
    try {
      const response = await askBotanika(value);
      appendAnswer(response, response.playback);
    } catch (caught) {
      setMessages((current) => [...current, { role: "error", text: caught.message }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const listen = async () => {
    if (voiceBusy || !localOperator) return;
    setVoiceBusy(true);
    setVoiceError(null);
    try {
      const response = await listenBotanika();
      if (response.transcript) {
        setMessages((current) => [...current, { role: "user", text: response.transcript, spoken: true }]);
      }
      const destination = navigationDestination(response.transcript);
      if (destination && onNavigate) {
        onNavigate(destination);
        setVoiceError(`Opened ${destination}.`);
        await refreshVoice();
        return;
      }
      if (response.answer) appendAnswer(response.answer, response.playback);
      if (response.detail && !response.transcript) setVoiceError(response.detail);
      await refreshVoice();
    } catch (caught) {
      setVoiceError(caught.message);
      await refreshVoice();
    } finally {
      setVoiceBusy(false);
    }
  };

  const speakAnswer = async (index, text) => {
    if (!localOperator || voiceBusy) return;
    setVoiceBusy(true);
    setVoiceError(null);
    try {
      const playback = await speakBotanika(text);
      setMessages((current) => current.map((message, messageIndex) => (
        messageIndex === index ? { ...message, playback } : message
      )));
    } catch (caught) {
      setVoiceError(caught.message);
    } finally {
      setVoiceBusy(false);
      await refreshVoice();
    }
  };

  const stopSpeaking = async () => {
    try {
      await interruptVoice();
      await refreshVoice();
    } catch (caught) {
      setVoiceError(caught.message);
    }
  };

  const voiceReady = Boolean(localOperator && voice?.available);
  const voiceLabel = !localOperator
    ? "Pi-local voice"
    : voice?.state === "speaking"
      ? "Speaking"
      : voiceReady
        ? "Ready"
        : "Unavailable";

  return (
    <div className="chat-shell">
      <section className="chat-conversation" aria-label="Botanika conversation">
        <div className="chat-heading">
          <div>
            <div className="eyebrow">Offline botanical guide</div>
            <h2>Ask Botanika</h2>
          </div>
          <button type="button" className="btn quiet" onClick={() => setMessages([])} disabled={!messages.length}>
            Clear
          </button>
        </div>
        <div className="chat-messages" aria-live="polite">
          {!messages.length && (
            <div className="chat-empty">
              <strong>Ask from the local catalog</strong>
              <p>Try “Where is the banyan native?” or “How does jackfruit grow?”</p>
            </div>
          )}
          {messages.map((message, index) => (
            <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
              <div className="chat-role">{message.role === "user" ? (message.spoken ? "You · spoken" : "You") : "Botanika"}</div>
              <p>{message.text}</p>
              {message.abstained && <span className="badge">Evidence insufficient</span>}
              {message.role === "guide" && localOperator && !message.abstained && (
                <div className="chat-message-actions">
                  <button type="button" className="btn quiet" onClick={() => speakAnswer(index, message.text)} disabled={voiceBusy || !voiceReady}>
                    {message.playback?.status === "played" ? "Speak again" : "Speak answer"}
                  </button>
                  {voice?.state === "speaking" && <button type="button" className="btn quiet" onClick={stopSpeaking}>Stop</button>}
                </div>
              )}
              {message.playback?.status === "unavailable" && <div className="chat-playback-note">Answer shown; local playback unavailable.</div>}
              {message.citations && message.citations.length > 0 && (
                <div className="citation-list" aria-label="Answer citations">
                  {message.citations.map((citation) => (
                    <a href={citation.source?.url || "#"} target="_blank" rel="noreferrer" key={citation.chunk_id}>
                      Source: {citation.source?.title || citation.source?.source_id || citation.chunk_id}
                      {citation.source?.license ? ` · ${citation.source.license}` : ""}
                    </a>
                  ))}
                </div>
              )}
            </article>
          ))}
          {busy && <div className="chat-message guide"><div className="chat-role">Botanika</div><p>Searching local evidence…</p></div>}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <input
            ref={inputRef}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={knowledgeAvailable ? "Ask about a catalog plant…" : "Knowledge unavailable"}
            disabled={!knowledgeAvailable || busy}
            aria-label="Question for Botanika"
          />
          <button type="submit" className="btn green" disabled={!knowledgeAvailable || busy || !question.trim()}>
            Send
          </button>
        </form>
      </section>

      <aside className="chat-evidence" aria-label="Evidence and voice status">
        <div className="side-header">Evidence &amp; voice</div>
        <div className="side-body">
          <div className="metric-row"><dt>Guide</dt><dd>{knowledgeAvailable ? "Ready" : "Unavailable"}</dd></div>
          <p className="chat-note">Answers are assembled from reviewed local facts. Missing evidence produces an explicit abstention.</p>
          <div className="chat-voice-state">
            <div className="eyebrow">Voice</div>
            <strong>{voiceLabel}</strong>
            <p>{voice?.detail || "Checking the Pi microphone, local STT, Piper voice, and speaker…"}</p>
          </div>
          {localOperator ? (
            <>
              <button type="button" className="btn quiet" onClick={listen} disabled={voiceBusy || !voiceReady}>
                {voiceBusy ? "Listening…" : "Ask by voice"}
              </button>
              {voice?.state === "speaking" && <button type="button" className="btn quiet" onClick={stopSpeaking}>Stop playback</button>}
            </>
          ) : (
            <span className="badge">Typed chat works on paired browsers</span>
          )}
          {voiceError && <p className="chat-error">{voiceError}</p>}
        </div>
      </aside>
    </div>
  );
}

function navigationDestination(transcript) {
  const value = String(transcript || "").toLowerCase();
  if (/\b(go|open|show|take me)\b.*\b(home|start)\b/.test(value)) return "home";
  if (/\b(go|open|show|take me)\b.*\b(scan|camera)\b/.test(value)) return "scan";
  if (/\b(go|open|show|take me)\b.*\b(library|discoveries)\b/.test(value)) return "library";
  if (/\b(go|open|show|take me)\b.*\b(weed|weeds)\b/.test(value)) return "weeds";
  return null;
}
