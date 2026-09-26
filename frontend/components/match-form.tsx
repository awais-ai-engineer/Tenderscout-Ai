"use client";
import { useState, type FormEvent } from "react";
import type { CompanySummary, Match, Page } from "@/lib/types";
import { api } from "@/lib/api";
import { MatchView } from "./match-view";
import { Panel } from "./ui";
export function MatchForm({
  analysisId,
  initial,
}: {
  analysisId: number;
  initial: Page<CompanySummary>;
}) {
  const [companies, setCompanies] = useState(initial);
  const [company, setCompany] = useState("");
  const [match, setMatch] = useState<Match>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function more() {
    setPending(true);
    try {
      const page = await api.companies(companies.next_cursor!);
      setCompanies({
        items: [...companies.items, ...page.items],
        next_cursor: page.next_cursor,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load companies.",
      );
    } finally {
      setPending(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    setMatch(undefined);
    try {
      setMatch(await api.createMatch(Number(company), analysisId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Matching failed.");
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <Panel title="Compare a company profile">
        <form className="panel-body" onSubmit={submit}>
          <div className="field selector">
            <label htmlFor="company">Company-provided profile</label>
            <select
              id="company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
            >
              <option value="">Choose a company</option>
              {companies.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="inline-actions">
            <button disabled={pending || !company}>
              {pending ? "Working…" : "Run deterministic match"}
            </button>
            {companies.next_cursor && (
              <button
                className="secondary"
                type="button"
                onClick={more}
                disabled={pending}
              >
                Load more companies
              </button>
            )}
          </div>
          <p className="helper">
            This compares existing profile facts to analysis #{analysisId}. It
            does not make a bid decision.
          </p>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
        </form>
      </Panel>
      {match && <MatchView match={match} />}
    </>
  );
}
