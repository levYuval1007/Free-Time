"""A small page for the comparison: start a run, watch it, read the report. It holds no data and no secrets: the
admin token is typed into the page, kept only in memory, and sent as a bearer token to the admin endpoints.
Everything shown is put on the page as text (never as HTML)."""

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leeway comparison</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; background: #f4f5fa; color: #22232b; }
  main { max-width: 56rem; margin: 0 auto; padding: 1rem; }
  h1 { font-size: 1.4rem; margin: 0.5rem 0; }
  h2 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }
  p { color: #444758; }
  label { display: block; font-weight: 600; font-size: 0.9rem; margin: 0.75rem 0 0.25rem; }
  input { width: 100%; box-sizing: border-box; padding: 0.6rem; border: 1px solid #d3d5df; border-radius: 8px; font-size: 1rem; }
  button { padding: 0.55rem 1rem; border: 0; border-radius: 8px; background: #5b6ad8; color: white; font-size: 0.95rem; cursor: pointer; margin: 0.75rem 0.5rem 0 0; }
  button:disabled { background: #d3d5df; cursor: default; }
  table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; }
  th, td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid #e4e5ec; font-size: 0.9rem; }
  td button { margin: 0; padding: 0.3rem 0.7rem; }
  pre { background: white; padding: 1rem; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; font-size: 0.85rem; }
  #message { min-height: 1.4rem; font-weight: 600; }
</style>
</head>
<body>
<main>
  <h1>AI agent vs rule-based planner</h1>
  <p>Runs the real agent and the planner on fixed trips and writes a report. This spends real money, limited by the budget below.</p>

  <label for="token">Admin token (kept only in this page, never stored)</label>
  <input id="token" type="password" autocomplete="new-password">
  <label for="budget">Budget in US dollars (0.05 to 1.00)</label>
  <input id="budget" type="number" min="0.05" max="1" step="0.05" value="0.30">
  <label for="only">Run only scenarios whose name contains this text (leave empty to run them all)</label>
  <input id="only" name="scenario-filter" maxlength="40" autocomplete="off" placeholder="empty = all scenarios">
  <p id="scenarios"></p>
  <button id="start">Start comparison</button>
  <button id="refresh">Refresh the list</button>
  <button id="check">Check storage</button>
  <p id="message" role="status"></p>
  <p id="storage"></p>

  <h2>Runs</h2>
  <table id="runs">
    <thead><tr><th>Started</th><th>Status</th><th>Progress</th><th></th></tr></thead>
    <tbody></tbody>
  </table>

  <h2>Report</h2>
  <button id="download" hidden>Download as .md</button>
  <pre id="report">Start a run, or pick one from the list, to see its report here.</pre>
</main>
<script>
  const $ = (id) => document.getElementById(id);
  let timer = null;
  let current = null;
  let currentText = "";

  function say(text) { $("message").textContent = text; }

  async function call(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { Authorization: "Bearer " + $("token").value.trim(), ...(options.headers || {}) },
    });
    const type = response.headers.get("content-type") || "";
    const body = type.includes("json") ? await response.json() : await response.text();
    if (!response.ok) {
      const error = new Error((body && body.error) || "Request failed (" + response.status + ")");
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function renderRuns(runs) {
    const body = $("runs").querySelector("tbody");
    body.replaceChildren();
    for (const run of runs) {
      const row = body.insertRow();
      row.insertCell().textContent = run.started ? String(run.started).replace("T", " ").replace("+00:00", " UTC") : "";
      row.insertCell().textContent = run.status;
      row.insertCell().textContent = run.progress;
      const button = document.createElement("button");
      button.textContent = "Show report";
      button.disabled = run.status === "running";
      button.onclick = () => show(run.id);
      row.insertCell().appendChild(button);
    }
  }

  async function show(id) {
    current = id;
    try {
      currentText = await call("/api/admin/evals/" + encodeURIComponent(id) + "?format=md");
      $("report").textContent = currentText;
      $("download").hidden = false;
      say("");
    } catch (err) {
      currentText = "";
      say(err.message);
    }
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      const { runs, storage, scenarios } = await call("/api/admin/evals");
      renderRuns(runs);
      $("scenarios").textContent = "Scenarios: " + scenarios.join(", ");
      $("storage").textContent = storage === "postgres"
        ? "Reports are saved in the database and survive restarts."
        : "Reports are saved as files on the server; a free host loses them when it restarts. The log keeps a copy.";
      say(runs.length ? "" : "No runs yet. Start one above.");
      if (runs.some((run) => run.status === "running")) timer = setTimeout(refresh, 3000);
      const mine = runs.find((run) => run.id === current);
      if (mine && mine.status === "done" && !currentText) await show(current);
    } catch (err) {
      say(err.status === 401 ? "That token is not right." : err.message);
    }
  }

  $("start").onclick = async () => {
    try {
      const only = $("only").value.trim();
      const started = await call("/api/admin/evals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_usd: Number($("budget").value), only: only || null }),
      });
      current = started.id;
      currentText = "";
      $("download").hidden = true;
      $("report").textContent = "Running. The report appears here when it is ready (a minute or two).";
      say("Started " + started.id);
      refresh();
    } catch (err) {
      say(err.status === 401 ? "That token is not right." : err.message);
    }
  };

  $("refresh").onclick = refresh;

  $("check").onclick = async () => {
    try {
      const result = await call("/api/admin/storage");
      say(result.ok
        ? "Storage works (" + result.kind + "), " + result.reports + " saved report(s)."
        : "Storage problem (" + result.kind + "): " + result.error);
    } catch (err) {
      say(err.status === 401 ? "That token is not right." : err.message);
    }
  };

  $("download").onclick = () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([currentText], { type: "text/markdown" }));
    link.download = (current || "report") + ".md";
    link.click();
    URL.revokeObjectURL(link.href);
  };
</script>
</body>
</html>
"""

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
