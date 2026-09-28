"use client";
import { useState } from "react";
import { api } from "@/lib/api";
export function SaveButton({
  companyId,
  tenderId,
  initial = false,
}: {
  companyId: number;
  tenderId: number;
  initial?: boolean;
}) {
  const [saved, setSaved] = useState(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function toggle() {
    setBusy(true);
    setError("");
    try {
      if (saved) await api.unsaveTender(companyId, tenderId);
      else await api.saveTender(companyId, tenderId);
      setSaved(!saved);
    } catch {
      setError("Could not update saved state.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <span>
      <button
        className="button secondary"
        type="button"
        disabled={busy}
        onClick={toggle}
      >
        {saved ? "Saved" : "Save"}
      </button>
      {error && <small role="alert">{error}</small>}
    </span>
  );
}
