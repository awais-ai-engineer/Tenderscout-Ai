"use client";

import {
  ChangeEvent,
  FormEvent,
  useState,
} from "react";

import { api } from "@/lib/api";
import type { NotificationPreference } from "@/lib/types";

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="4"
        y="6"
        width="16"
        height="12"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="m5 8 7 5 7-5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MatchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3.5 14.5 9l5.5.8-4 3.9.9 5.5L12 16.6 7.1 19.2l.9-5.5-4-3.9L9.5 9 12 3.5Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function UpdateIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M19 8V4m0 0h-4m4 0-3.2 3.2A7 7 0 1 0 19 13"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="8"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M12 8v4l3 2"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function LightningIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="m13.5 3-7 10h5L10.5 21l7-11h-5l1-7Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DigestIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="5"
        y="4"
        width="14"
        height="16"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M8.5 9h7M8.5 13h7M8.5 17h4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function NotificationForm({
  initial,
}: {
  initial: NotificationPreference;
}) {
  const [value, setValue] = useState(initial);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  function check(name: keyof NotificationPreference) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      setValue({
        ...value,
        [name]: event.target.checked,
      });
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setSaving(true);
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

      const updated = await api.updatePreferences(
        value.company_id,
        {
          notification_email,
          email_enabled,
          minimum_match_score,
          new_match_alerts,
          tender_change_alerts,
          deadline_reminders,
          delivery_mode,
        },
      );

      setValue(updated);
      setMessage("Preferences saved.");
    } catch {
      setMessage("Preferences could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="settings-preferences-form"
      onSubmit={submit}
    >
      <section className="settings-preference-section">
        <div className="settings-preference-heading">
          <span className="settings-preference-icon purple">
            <MailIcon />
          </span>

          <div>
            <h3>Email delivery</h3>

            <p>
              Choose where TenderScout should send procurement
              notifications.
            </p>
          </div>
        </div>

        <div className="settings-email-row">
          <div className="settings-email-field">
            <label htmlFor="notification-email">
              Notification email
            </label>

            <input
              id="notification-email"
              type="email"
              maxLength={320}
              placeholder="alerts@company.com"
              value={value.notification_email || ""}
              onChange={(event) =>
                setValue({
                  ...value,
                  notification_email:
                    event.target.value || null,
                })
              }
            />
          </div>

          <label className="settings-master-toggle">
            <input
              type="checkbox"
              checked={value.email_enabled}
              onChange={check("email_enabled")}
            />

            <span className="settings-switch" />

            <span>
              <strong>Email notifications</strong>

              <small>
                Allow TenderScout to deliver alerts by email.
              </small>
            </span>
          </label>
        </div>
      </section>

      <section className="settings-preference-section">
        <div className="settings-preference-heading">
          <span className="settings-preference-icon green">
            <MatchIcon />
          </span>

          <div>
            <h3>Alert types</h3>

            <p>
              Select the procurement events that should create
              notifications.
            </p>
          </div>
        </div>

        <div className="settings-alert-options">
          <label className="settings-alert-option">
            <span className="settings-alert-option-icon green">
              <MatchIcon />
            </span>

            <span className="settings-alert-option-copy">
              <strong>New company matches</strong>

              <small>
                Notify when a tender is matched against your
                company profile.
              </small>
            </span>

            <input
              type="checkbox"
              checked={value.new_match_alerts}
              onChange={check("new_match_alerts")}
            />

            <span className="settings-switch" />
          </label>

          <label className="settings-alert-option">
            <span className="settings-alert-option-icon blue">
              <UpdateIcon />
            </span>

            <span className="settings-alert-option-copy">
              <strong>Tender updates</strong>

              <small>
                Notify when a tracked procurement opportunity
                changes.
              </small>
            </span>

            <input
              type="checkbox"
              checked={value.tender_change_alerts}
              onChange={check("tender_change_alerts")}
            />

            <span className="settings-switch" />
          </label>

          <label className="settings-alert-option">
            <span className="settings-alert-option-icon amber">
              <ClockIcon />
            </span>

            <span className="settings-alert-option-copy">
              <strong>Deadline reminders</strong>

              <small>
                Surface approaching submission deadlines.
              </small>
            </span>

            <input
              type="checkbox"
              checked={value.deadline_reminders}
              onChange={check("deadline_reminders")}
            />

            <span className="settings-switch" />
          </label>
        </div>
      </section>

      <section className="settings-preference-section">
        <div className="settings-preference-heading">
          <span className="settings-preference-icon blue">
            <MatchIcon />
          </span>

          <div>
            <h3>Company-fit threshold</h3>

            <p>
              Set the minimum match score used for relevant
              company-fit notifications.
            </p>
          </div>
        </div>

        <div className="settings-threshold">
          <div className="settings-threshold-value">
            <strong>
              {value.minimum_match_score}
            </strong>

            <span>/100 minimum fit</span>
          </div>

          <input
            className="settings-threshold-range"
            type="range"
            min={0}
            max={100}
            step={1}
            value={value.minimum_match_score}
            onChange={(event) =>
              setValue({
                ...value,
                minimum_match_score: Number(
                  event.target.value,
                ),
              })
            }
            aria-label="Minimum company-fit score"
          />

          <div className="settings-threshold-scale">
            <span>0</span>
            <span>More selective</span>
            <span>100</span>
          </div>
        </div>
      </section>

      <section className="settings-preference-section">
        <div className="settings-preference-heading">
          <span className="settings-preference-icon violet">
            <LightningIcon />
          </span>

          <div>
            <h3>Delivery schedule</h3>

            <p>
              Choose whether alerts arrive immediately or in a
              daily summary.
            </p>
          </div>
        </div>

        <div className="settings-delivery-grid">
          <label
            className={`settings-delivery-card ${
              value.delivery_mode === "instant"
                ? "selected"
                : ""
            }`}
          >
            <input
              type="radio"
              name="delivery"
              value="instant"
              checked={value.delivery_mode === "instant"}
              onChange={() =>
                setValue({
                  ...value,
                  delivery_mode: "instant",
                })
              }
            />

            <span className="settings-delivery-icon">
              <LightningIcon />
            </span>

            <span>
              <strong>Instant</strong>

              <small>
                Receive qualifying alerts as they are created.
              </small>
            </span>

            <span className="settings-radio-indicator" />
          </label>

          <label
            className={`settings-delivery-card ${
              value.delivery_mode === "daily_digest"
                ? "selected"
                : ""
            }`}
          >
            <input
              type="radio"
              name="delivery"
              value="daily_digest"
              checked={
                value.delivery_mode === "daily_digest"
              }
              onChange={() =>
                setValue({
                  ...value,
                  delivery_mode: "daily_digest",
                })
              }
            />

            <span className="settings-delivery-icon">
              <DigestIcon />
            </span>

            <span>
              <strong>Daily digest</strong>

              <small>
                Group qualifying notifications into a summary.
              </small>
            </span>

            <span className="settings-radio-indicator" />
          </label>
        </div>
      </section>

      <footer className="settings-save-bar">
        <div>
          {message && (
            <span
              className={`settings-save-message ${
                message === "Preferences saved."
                  ? "success"
                  : "error"
              }`}
              role="status"
            >
              {message}
            </span>
          )}
        </div>

        <button type="submit" disabled={saving}>
          {saving
            ? "Saving..."
            : "Save preferences"}
        </button>
      </footer>
    </form>
  );
}