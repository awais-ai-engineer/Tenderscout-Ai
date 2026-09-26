"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { label } from "@/lib/format";
import type { CompanyProfile, Completeness } from "@/lib/types";

type Row = Record<string, string>;
type RowKind = "capabilities" | "certifications" | "experience";
const rowFields: Record<RowKind, string[]> = {
  capabilities: ["name", "description"],
  certifications: ["name", "issuer", "identifier", "valid_from", "valid_until"],
  experience: [
    "title",
    "client",
    "description",
    "country",
    "contract_value",
    "currency",
    "started_at",
    "completed_at",
  ],
};
const baseFields = [
  "name",
  "description",
  "country",
  "website",
  "employee_count",
  "annual_revenue",
  "currency",
  "years_in_business",
];
const flags: (keyof Completeness)[] = [
  "capabilities_complete",
  "certifications_complete",
  "experience_complete",
  "financials_complete",
];
const nullable = (value: string | undefined) => value?.trim() || null;
export function CompanyForm() {
  const router = useRouter();
  const [values, setValues] = useState<Row>({});
  const [complete, setComplete] = useState<Completeness>({
    capabilities_complete: false,
    certifications_complete: false,
    experience_complete: false,
    financials_complete: false,
  });
  const [rows, setRows] = useState<Record<RowKind, Row[]>>({
    capabilities: [],
    certifications: [],
    experience: [],
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  function changeRow(
    kind: RowKind,
    index: number,
    field: string,
    value: string,
  ) {
    setRows((current) => ({
      ...current,
      [kind]: current[kind].map((row, i) =>
        i === index ? { ...row, [field]: value } : row,
      ),
    }));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    const profile: CompanyProfile = {
      name: values.name || "",
      description: nullable(values.description),
      country: nullable(values.country),
      website: nullable(values.website),
      employee_count: nullable(values.employee_count)
        ? Number(values.employee_count)
        : null,
      annual_revenue: nullable(values.annual_revenue),
      currency: nullable(values.currency)?.toUpperCase() || null,
      years_in_business: nullable(values.years_in_business)
        ? Number(values.years_in_business)
        : null,
      ...complete,
      capabilities: rows.capabilities.map((row) => ({
        name: row.name || "",
        description: nullable(row.description),
      })),
      certifications: rows.certifications.map((row) => ({
        name: row.name || "",
        issuer: nullable(row.issuer),
        identifier: nullable(row.identifier),
        valid_from: nullable(row.valid_from),
        valid_until: nullable(row.valid_until),
      })),
      experience: rows.experience.map((row) => ({
        title: nullable(row.title),
        client: nullable(row.client),
        description: nullable(row.description),
        country: nullable(row.country),
        contract_value: nullable(row.contract_value),
        currency: nullable(row.currency)?.toUpperCase() || null,
        started_at: nullable(row.started_at),
        completed_at: nullable(row.completed_at),
      })),
    };
    try {
      const company = await api.createCompany(profile);
      router.push(`/companies/${company.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save profile.");
    } finally {
      setPending(false);
    }
  }
  function input(
    field: string,
    value: string,
    onChange: (value: string) => void,
    id: string,
    required = false,
  ) {
    const dateField = field.endsWith("_at") || field.startsWith("valid_");
    const numeric = [
      "employee_count",
      "annual_revenue",
      "years_in_business",
      "contract_value",
    ].includes(field);
    return (
      <div
        className={`field ${field === "description" ? "full" : ""}`}
        key={id}
      >
        <label htmlFor={id}>
          {label(field)}
          {required ? " *" : ""}
        </label>
        {field === "description" ? (
          <textarea
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            maxLength={10000}
          />
        ) : (
          <input
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            type={
              dateField
                ? "date"
                : numeric
                  ? "number"
                  : field === "website"
                    ? "url"
                    : "text"
            }
            min={numeric ? 0 : undefined}
            max={
              ["employee_count", "years_in_business"].includes(field)
                ? 2147483647
                : undefined
            }
            step={
              ["annual_revenue", "contract_value"].includes(field)
                ? "0.01"
                : numeric
                  ? "1"
                  : undefined
            }
            maxLength={
              field === "website" ? 2048 : field === "currency" ? 3 : 255
            }
            pattern={field === "currency" ? "[A-Za-z]{3}" : undefined}
            required={required}
          />
        )}
      </div>
    );
  }
  return (
    <form className="panel" onSubmit={submit}>
      <section className="form-section">
        <h2>Company facts</h2>
        <div className="form-grid">
          {baseFields.map((field) =>
            input(
              field,
              values[field] || "",
              (value) =>
                setValues((current) => ({ ...current, [field]: value })),
              `company-${field}`,
              field === "name",
            ),
          )}
        </div>
        <p className="helper">
          Currency uses a three-letter code, such as GBP. Leave unknown facts
          blank.
        </p>
      </section>
      <section className="form-section">
        <h2>Completeness declarations</h2>
        <p className="helper">
          Check only where the supplied list or financial facts are complete.
          Unchecked means unknown, not absent.
        </p>
        <div className="form-grid">
          {flags.map((flag) => (
            <label className="check-field" key={flag}>
              <input
                type="checkbox"
                checked={complete[flag]}
                onChange={(e) =>
                  setComplete((current) => ({
                    ...current,
                    [flag]: e.target.checked,
                  }))
                }
              />
              {label(flag)}
            </label>
          ))}
        </div>
      </section>
      {(Object.keys(rowFields) as RowKind[]).map((kind) => (
        <section className="form-section" key={kind}>
          <h2>{label(kind)}</h2>
          {rows[kind].map((row, index) => (
            <div className="dynamic-row" key={index}>
              <div className="form-grid">
                {rowFields[kind].map((field) =>
                  input(
                    field,
                    row[field] || "",
                    (value) => changeRow(kind, index, field, value),
                    `${kind}-${index}-${field}`,
                    field === "name",
                  ),
                )}
              </div>
              <div className="inline-actions">
                <button
                  className="secondary"
                  type="button"
                  aria-label={`Remove ${kind} row ${index + 1}`}
                  onClick={() =>
                    setRows((current) => ({
                      ...current,
                      [kind]: current[kind].filter((_, i) => i !== index),
                    }))
                  }
                >
                  Remove row
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="secondary"
            disabled={rows[kind].length >= 200}
            onClick={() =>
              setRows((current) => ({
                ...current,
                [kind]: [...current[kind], {}],
              }))
            }
          >
            + Add{" "}
            {kind === "capabilities"
              ? "capability"
              : kind === "certifications"
                ? "certification"
                : "experience"}
          </button>
        </section>
      ))}
      <div className="form-section">
        <p className="helper">
          This creates a company-provided profile. Facts are not externally
          verified.
        </p>
        {error && (
          <p role="alert" className="notice error">
            {error}
          </p>
        )}
        <button disabled={pending}>
          {pending ? "Saving profile…" : "Create company profile"}
        </button>
      </div>
    </form>
  );
}
