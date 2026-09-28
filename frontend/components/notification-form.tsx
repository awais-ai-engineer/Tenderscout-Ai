"use client";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import type { NotificationPreference } from "@/lib/types";
export function NotificationForm({
  initial,
}: {
  initial: NotificationPreference;
}) {
  const [value, setValue] = useState(initial);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      const {
        notification_email,
        email_enabled,
        minimum_match_score,
        new_match_alerts,
        tender_change_alerts,
        deadline_reminders,
        delivery_mode,
      } = value;
      setValue(
        await api.updatePreferences(value.company_id, {
          notification_email,
          email_enabled,
          minimum_match_score,
          new_match_alerts,
          tender_change_alerts,
          deadline_reminders,
          delivery_mode,
        }),
      );
      setMessage("Preferences saved.");
    } catch {
      setMessage("Preferences could not be saved.");
    }
  }
  const check =
    (name: keyof NotificationPreference) =>
    (event: React.ChangeEvent<HTMLInputElement>) =>
      setValue({ ...value, [name]: event.target.checked });
  return (
    <form className="panel-body" onSubmit={submit}>
      <div className="field">
        <label htmlFor="email">Notification email</label>
        <input
          id="email"
          type="email"
          maxLength={320}
          value={value.notification_email || ""}
          onChange={(e) =>
            setValue({ ...value, notification_email: e.target.value || null })
          }
        />
      </div>
      <label>
        <input
          type="checkbox"
          checked={value.email_enabled}
          onChange={check("email_enabled")}
        />{" "}
        Email notifications
      </label>
      <fieldset>
        <legend>Notify me about</legend>
        <label>
          <input
            type="checkbox"
            checked={value.new_match_alerts}
            onChange={check("new_match_alerts")}
          />{" "}
          New company matches
        </label>
        <label>
          <input
            type="checkbox"
            checked={value.tender_change_alerts}
            onChange={check("tender_change_alerts")}
          />{" "}
          Tender updates
        </label>
        <label>
          <input
            type="checkbox"
            checked={value.deadline_reminders}
            onChange={check("deadline_reminders")}
          />{" "}
          Deadline reminders
        </label>
      </fieldset>
      <div className="field">
        <label htmlFor="threshold">Minimum company-fit score</label>
        <input
          id="threshold"
          type="number"
          min={0}
          max={100}
          value={value.minimum_match_score}
          onChange={(e) =>
            setValue({ ...value, minimum_match_score: Number(e.target.value) })
          }
        />
      </div>
      <fieldset>
        <legend>Delivery</legend>
        {(["instant", "daily_digest"] as const).map((mode) => (
          <label key={mode}>
            <input
              type="radio"
              name="delivery"
              checked={value.delivery_mode === mode}
              onChange={() => setValue({ ...value, delivery_mode: mode })}
            />
            {mode === "instant" ? "Instant" : "Daily digest"}
          </label>
        ))}
      </fieldset>
      <button type="submit">Save preferences</button>{" "}
      {message && <span role="status">{message}</span>}
    </form>
  );
}
