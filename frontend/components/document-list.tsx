"use client";
import { useState } from "react";
import type { TenderDocument } from "@/lib/types";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { Badge, ErrorState, Panel } from "./ui";
export function DocumentCard({ document }: { document: TenderDocument }) {
  const [versions, setVersions] = useState(document.versions);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  async function more() {
    if (!versions.next_cursor) return;
    setPending(true);
    setError(undefined);
    try {
      const next = await api.versions(document.id, versions.next_cursor);
      setVersions({
        items: [...versions.items, ...next.items],
        next_cursor: next.next_cursor,
      });
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }
  return (
    <Panel title={document.title || `Document #${document.id}`}>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Downloaded (UTC)</th>
              <th>Format / size</th>
              <th>Extraction</th>
              <th>Analysis</th>
              <th>Index</th>
            </tr>
          </thead>
          <tbody>
            {versions.items.map((version) => (
              <tr key={version.id}>
                <td>
                  #{version.id}
                  <small className="subtext">
                    {version.content_hash.slice(0, 12)}
                  </small>
                </td>
                <td>{date(version.downloaded_at, true)}</td>
                <td>
                  {version.media_type || "Not provided"}
                  <small className="subtext">
                    {(version.byte_size / 1024).toFixed(1)} KB
                  </small>
                </td>
                <td>
                  <Badge value={version.extraction_status} />
                </td>
                <td>{version.has_analysis ? "Available" : "Not available"}</td>
                <td>{version.is_indexed ? "Ready" : "Not ready"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!versions.items.length && (
        <p className="panel-body muted">No downloaded versions.</p>
      )}
      {error !== undefined && <ErrorState error={error} />}
      {versions.next_cursor && (
        <div className="panel-body">
          <button className="secondary" disabled={pending} onClick={more}>
            {pending ? "Loading…" : "Load older versions"}
          </button>
        </div>
      )}
    </Panel>
  );
}
