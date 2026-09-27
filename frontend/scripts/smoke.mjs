// Production-render smoke test against an isolated, synthetic HTTP API.
// This does not exercise browser hydration, PostgreSQL, Redis or providers.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";

const empty = { items: [], next_cursor: null };
const tender = {
  id: 1,
  source: "contracts-finder",
  external_id: "smoke-only",
  title: "Synthetic smoke tender",
  organization: null,
  category: null,
  location: null,
  published_at: null,
  deadline: null,
  first_seen_at: "2026-01-01T00:00:00Z",
  last_seen_at: "2026-01-01T00:00:00Z",
  latest_revision_index: 0,
  document_count: 0,
  latest_analysis_status: null,
  description: null,
  description_truncated: false,
  source_url: null,
  latest_revision: null,
  documents: empty,
  analyses: empty,
  latest_metadata_change: null,
  matches_count: 0,
};
let unavailable = false;
const fixture = createServer((req, res) => {
  res.setHeader("Content-Type", "application/json");
  if (unavailable) {
    res.writeHead(503).end(
      JSON.stringify({
        error: {
          code: "database_unavailable",
          message: "Data is temporarily unavailable",
        },
      }),
    );
    return;
  }
  const path = new URL(req.url, "http://localhost").pathname;
  let data;
  if (path === "/api/v1/dashboard/summary")
    data = {
      active_tenders_count: 0,
      tender_count: 0,
      company_count: 0,
      upcoming_deadlines: [],
      recent_changes: [],
      recent_runs: [],
    };
  else if (path === "/api/v1/tenders/1") data = tender;
  else if (
    ["/api/v1/tenders", "/api/v1/companies", "/api/v1/pipeline/runs"].includes(
      path,
    ) ||
    /^\/api\/v1\/tenders\/1\/(documents|analyses|matches|revisions|changes)$/.test(
      path,
    )
  )
    data = empty;
  else {
    res
      .writeHead(404)
      .end(
        JSON.stringify({
          error: { code: "not_found", message: "Resource does not exist" },
        }),
      );
    return;
  }
  res.end(JSON.stringify(data));
});
fixture.listen(0, "127.0.0.1");
await once(fixture, "listening");
const probe = createServer();
probe.listen(0, "127.0.0.1");
await once(probe, "listening");
const port = probe.address().port;
await new Promise((resolve) => probe.close(resolve));
const child = spawn(
  process.execPath,
  [
    "node_modules/next/dist/bin/next",
    "start",
    "-H",
    "127.0.0.1",
    "-p",
    String(port),
  ],
  {
    env: {
      ...process.env,
      NEXT_TELEMETRY_DISABLED: "1",
      API_INTERNAL_BASE_URL: `http://127.0.0.1:${fixture.address().port}/api/v1`,
    },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let log = "";
for (const stream of [child.stdout, child.stderr])
  stream.on("data", (data) => {
    log = (log + data).slice(-8000);
  });
const exited = once(child, "exit");
const base = `http://127.0.0.1:${port}`;
try {
  let ready = false;
  for (let attempt = 0; attempt < 120; attempt++) {
    if (child.exitCode !== null)
      throw new Error(`Next exited before startup: ${log}`);
    try {
      ready = (await fetch(`${base}/companies/new`)).ok;
    } catch {
      /* starting */
    }
    if (ready) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.ok(ready, `Next startup timed out: ${log}`);
  const checks = [
    ["/", "No upcoming deadlines"],
    ["/discover", "No tenders found"],
    ["/matches", "Match overview coming soon"],
    ["/saved", "Saving is not available yet"],
    ["/alerts", "Alerts are not available yet"],
    ["/settings", "Data &amp; product preferences"],
    ["/companies", "No company profiles"],
    ["/companies/new", "Create company profile"],
    ["/pipeline", "No pipeline runs"],
    ["/tenders/1", "Synthetic smoke tender"],
    ["/tenders/1?tab=analysis", "No completed analysis"],
    ["/tenders/1?tab=documents", "No documents recorded"],
    ["/tenders/1?tab=changes", "No changes recorded"],
    ["/tenders/1?tab=ask", "No indexed document selected"],
    ["/tenders/1?tab=matches", "Matching needs an analysis"],
  ];
  for (const [path, expected] of checks) {
    const response = await fetch(base + path);
    const html = await response.text();
    assert.equal(response.status, 200, path);
    assert.ok(html.includes(expected), `${path} is missing ${expected}`);
    assert.ok(
      html.includes('id="main"'),
      `${path} is missing the main landmark`,
    );
  }
  const overviewHtml = await (await fetch(base)).text();
  assert.ok(!overviewHtml.includes('href="/pipeline"'), "Pipeline is exposed in customer navigation");
  const oldList = await (await fetch(`${base}/tenders`)).text();
  assert.match(oldList, /<meta[^>]+http-equiv="refresh"[^>]+\/discover/i);
  unavailable = true;
  for (const path of ["/", "/discover", "/companies", "/pipeline"]) {
    const html = await (await fetch(base + path)).text();
    assert.ok(
      html.includes("Data is temporarily unavailable"),
      `${path} did not render the API error`,
    );
  }
  console.log(
    `Passed ${checks.length + 6} production SSR smoke checks using synthetic test-only API responses.`,
  );
} finally {
  child.kill();
  await exited;
  fixture.closeAllConnections();
  await new Promise((resolve) => fixture.close(resolve));
}
