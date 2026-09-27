import type * as T from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
export type Params = Record<string, string | number | undefined>;
export function query(params: Params = {}) {
  const values = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") values.set(key, String(value));
  return values.size ? `?${values}` : "";
}
async function request<T>(
  path: string,
  body?: unknown,
  timeout = 15000,
): Promise<T> {
  const base = (
    typeof window === "undefined"
      ? process.env.API_INTERNAL_BASE_URL ||
        process.env.NEXT_PUBLIC_API_BASE_URL
      : process.env.NEXT_PUBLIC_API_BASE_URL
  )?.replace(/\/$/, "");
  if (!base)
    throw new ApiError(
      "api_not_configured",
      "The API address has not been configured.",
    );
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      cache: "no-store",
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
    });
  } catch {
    throw new ApiError(
      "api_unavailable",
      "The API could not be reached. Check that it is running, then try again.",
    );
  }
  if (!response.ok) {
    const data: { error?: { code?: string; message?: string } } = await response
      .json()
      .catch(() => ({}));
    throw new ApiError(
      data.error?.code || "request_failed",
      data.error?.message || "The request could not be completed.",
      response.status,
    );
  }
  return response.json() as Promise<T>;
}
export const api = {
  dashboard: () => request<T.Dashboard>("/dashboard/summary"),
  tenders: (params: Params = {}) =>
    request<T.Page<T.Tender>>(`/tenders${query(params)}`),
  discover: (params: Params = {}) =>
    request<T.DiscoverResponse>(`/discover${query(params)}`, undefined, 30000),
  tender: (id: string | number) => request<T.TenderDetail>(`/tenders/${id}`),
  documents: (id: string | number, cursor?: number) =>
    request<T.Page<T.TenderDocument>>(
      `/tenders/${id}/documents${query({ cursor })}`,
    ),
  versions: (id: number, cursor?: number) =>
    request<T.Page<T.Version>>(`/documents/${id}/versions${query({ cursor })}`),
  analyses: (id: string | number, cursor?: number) =>
    request<T.Page<T.AnalysisSummary>>(
      `/tenders/${id}/analyses${query({ cursor })}`,
    ),
  analysis: (id: string | number) => request<T.Analysis>(`/analyses/${id}`),
  revisions: (id: string | number, cursor?: number) =>
    request<T.Page<T.Revision>>(`/tenders/${id}/revisions${query({ cursor })}`),
  changes: (id: string | number, kind: string, cursor?: number) =>
    request<T.Page<T.ChangeSummary>>(
      `/tenders/${id}/changes${query({ kind, cursor })}`,
    ),
  change: (kind: string, id: string | number) =>
    request<T.Change>(`/changes/${kind}/${id}`),
  companies: (cursor?: number) =>
    request<T.Page<T.CompanySummary>>(`/companies${query({ cursor })}`),
  company: (id: string | number) => request<T.Company>(`/companies/${id}`),
  createCompany: (body: T.CompanyProfile) =>
    request<T.Company>("/companies", body),
  matches: (
    kind: "tenders" | "companies",
    id: string | number,
    cursor?: number,
  ) =>
    request<T.Page<T.MatchSummary>>(
      `/${kind}/${id}/matches${query({ cursor })}`,
    ),
  match: (id: string | number) => request<T.Match>(`/matches/${id}`),
  createMatch: (company_id: number, analysis_id: number) =>
    request<T.Match>("/matches", { company_id, analysis_id }),
  ask: (version: number, question: string) =>
    request<T.Answer>(
      `/document-versions/${version}/ask`,
      { question },
      150000,
    ),
  runs: (cursor?: number) =>
    request<T.Page<T.Run>>(`/pipeline/runs${query({ cursor })}`),
  run: (id: string | number, after_stage_id?: number) =>
    request<T.RunDetail>(`/pipeline/runs/${id}${query({ after_stage_id })}`),
  trigger: (source: T.Source) =>
    request<{
      run_id: number;
      source: string;
      status: string;
      celery_task_id: string;
      reused: boolean;
    }>("/pipeline/runs", { source }),
};
