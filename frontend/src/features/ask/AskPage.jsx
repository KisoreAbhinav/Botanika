import { useRef, useState } from "react";
import { askBotanika } from "../../platform/api.js";

const ABSTENTION = "I could not find enough reliable offline information to answer that.";

export function AskPage({ ready }) {
  const knowledgeAvailable = Boolean(
    ready && ready.capabilities && ready.capabilities.knowledge && ready.capabilities.knowledge.available,
  );
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const submit = async (event) => {
    event.preventDefault();
    const value = question.trim();
    if (!value || busy || !knowledgeAvailable) return;
    setQuestion("");
    setMessages((current) => [...current, { role: "user", text: value }]);
    setBusy(true);
    try {
      const response = await askBotanika(value);
      setMessages((current) => [
        ...current,
        {
          role: "guide",
          text: response.answer || ABSTENTION,
          citations: response.citations || [],
          abstained: response.abstained,
        },
      ]);
    } catch (caught) {
      setMessages((current) => [...current, { role: "error", text: caught.message }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

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
              <div className="chat-role">{message.role === "user" ? "You" : "Botanika"}</div>
              <p>{message.text}</p>
              {message.abstained && <span className="badge">Evidence insufficient</span>}
              {message.citations && message.citations.length > 0 && (
                <div className="citation-list">
                  {message.citations.map((citation) => (
                    <a href={citation.source?.url} target="_blank" rel="noreferrer" key={citation.chunk_id}>
                      Source: {citation.source?.title || citation.source?.source_id}
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
            <strong>Text ready</strong>
            <p>Pi microphone and speaker coordination is scheduled for the voice phase. Typed questions remain available offline.</p>
          </div>
          <button type="button" className="btn quiet" disabled title="Voice is not enabled in Phase 6">
            Microphone unavailable
          </button>
        </div>
      </aside>
    </div>
  );
}
