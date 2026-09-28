"use client";
import { useState } from "react";
import { api } from "@/lib/api";
export function ReadAlertButton({
  companyId,
  alertId,
}: {
  companyId: number;
  alertId: number;
}) {
  const [read, setRead] = useState(false);
  const [error, setError] = useState(false);
  return (
    <span>
      <button
        className="button secondary"
        disabled={read}
        onClick={async () => {
          setError(false);
          try {
            await api.readAlert(companyId, alertId);
            setRead(true);
          } catch {
            setError(true);
          }
        }}
      >
        {read ? "Read" : "Mark read"}
      </button>
      {error && <small role="alert">Could not mark this alert as read.</small>}
    </span>
  );
}
