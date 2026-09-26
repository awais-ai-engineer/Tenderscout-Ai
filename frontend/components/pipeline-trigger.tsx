"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Source } from "@/lib/types";
export function PipelineTrigger() {
  const [source, setSource] = useState<Source>("contracts-finder");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const run = await api.trigger(source);
      router.push(`/pipeline/${run.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to queue the run.");
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <form className="filters" onSubmit={submit}>
        <div className="field">
          <label htmlFor="pipeline-source">Source to process</label>
          <select
            id="pipeline-source"
            value={source}
            onChange={(e) => setSource(e.target.value as Source)}
          >
            <option value="contracts-finder">Contracts Finder</option>
            <option value="find-a-tender">Find a Tender</option>
          </select>
        </div>
        <button disabled={pending}>
          {pending ? "Queuing…" : "Run source pipeline"}
        </button>
        <p className="helper">An existing active run is reused.</p>
      </form>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
