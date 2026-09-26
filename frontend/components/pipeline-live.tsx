"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { RunDetail } from "@/lib/types";
import { api } from "@/lib/api";
import { date, label, source } from "@/lib/format";
import { Badge, Empty, Panel } from "./ui";
export function PipelineLive({
  initial,
  afterStageId,
}: {
  initial: RunDetail;
  afterStageId?: number;
}) {
  const [run, setRun] = useState(initial);
  const [error, setError] = useState("");
  const active = run.status === "queued" || run.status === "running";
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.run(initial.id, afterStageId);
        if (!cancelled) {
          setRun(next);
          setError("");
          if (next.status === "queued" || next.status === "running")
            timer = setTimeout(poll, 5000);
        }
      } catch {
        if (!cancelled) {
          setError(
            "Status refresh is unavailable. The run may still be processing.",
          );
          timer = setTimeout(poll, 5000);
        }
      }
    }
    timer = setTimeout(poll, 5000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, initial.id, afterStageId]);
  return (
    <>
      <div className="summary-line">
        <Badge value={run.status} />
        <span>
          {source(run.source)} · {label(run.trigger)}
        </span>
        <span className="muted" aria-live="polite">
          {active ? "Refreshing every 5 seconds" : "Run finalized"}
        </span>
      </div>
      <Panel title="Run overview">
        <dl className="details-grid">
          {[
            ["Created", date(run.created_at, true)],
            ["Started", date(run.started_at, true)],
            ["Finished", date(run.finished_at, true)],
          ].map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {run.failure_reason && (
          <p className="notice error">{run.failure_reason}</p>
        )}
      </Panel>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <Panel title="Processing stages">
        {run.stages.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Stage / entity</th>
                  <th>Status</th>
                  <th>Attempt</th>
                  <th>Metrics</th>
                  <th>Failure reason</th>
                </tr>
              </thead>
              <tbody>
                {run.stages.map((stage) => (
                  <tr key={stage.id}>
                    <td>
                      <strong>{label(stage.stage)}</strong>
                      <small className="subtext">
                        {label(stage.entity_type)}{" "}
                        {stage.entity_id ? `#${stage.entity_id}` : ""}
                      </small>
                    </td>
                    <td>
                      <Badge value={stage.status} />
                    </td>
                    <td>{stage.attempt}</td>
                    <td>
                      {Object.entries(stage.metrics).map(([key, value]) => (
                        <div key={key}>
                          {label(key)}: {String(value)}
                        </div>
                      ))}
                    </td>
                    <td>{stage.failure_reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No stages in this page.</Empty>
        )}
      </Panel>
      {run.next_after_stage_id && (
        <div className="pagination">
          <Link
            className="button secondary"
            href={`/pipeline/${run.id}?after_stage_id=${run.next_after_stage_id}`}
          >
            Next stage page →
          </Link>
        </div>
      )}
    </>
  );
}
