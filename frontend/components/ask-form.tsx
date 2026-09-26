"use client";
import { useState, type FormEvent } from "react";
import type { Answer } from "@/lib/types";
import { api } from "@/lib/api";
import { Panel } from "./ui";
export function AskForm({ versionId }: { versionId: number }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    setAnswer(undefined);
    try {
      setAnswer(await api.ask(versionId, question));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to answer.");
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <Panel title="Ask this document">
        <form className="panel-body" onSubmit={submit}>
          <div className="field">
            <label htmlFor="question">Your question</label>
            <textarea
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={2000}
              required
              placeholder="What are the submission requirements?"
            />
          </div>
          <p className="helper">
            Answers use indexed text from version #{versionId}. This can take up
            to two minutes.
          </p>
          <button disabled={pending || !question.trim()}>
            {pending ? "Checking source evidence…" : "Ask Tender"}
          </button>
          <div aria-live="polite">
            {pending && (
              <p className="helper">
                Retrieving passages and preparing a grounded response…
              </p>
            )}
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
          </div>
        </form>
      </Panel>
      {answer && (
        <Panel
          title={
            answer.status === "insufficient"
              ? "Not established by the source"
              : "Answer"
          }
        >
          <div className="panel-body">
            <p className="prose">
              {answer.answer ||
                "The answer is not established by the indexed tender text."}
            </p>
            {answer.citations.map((citation, index) => (
              <article className="fact-card" key={`${citation.chunk_id}-${index}`}>
                <strong>
                  Document version #{citation.document_version_id} · Chunk{" "}
                  {citation.chunk_index}
                </strong>
                <blockquote>{citation.quote}</blockquote>
              </article>
            ))}
            <p className="helper">
              Citations preserve source quotations. They do not prove every
              interpretation is correct; review the source.
            </p>
          </div>
        </Panel>
      )}
    </>
  );
}
