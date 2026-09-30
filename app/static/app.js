const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const EXAMPLES = [
  { k: "kw", label: "Exact code", q: "ORD-48213" },
  { k: "vec", label: "Plain words", q: "arrived damaged" },
  { k: "hy", label: "Both", q: "ORD-48213 arrived damaged" },
  { k: "vec", label: "Plain words", q: "package never showed up" },
  { k: "vec", label: "Plain words", q: "still waiting for my money back" },
  { k: "kw", label: "Tracking", q: null }, // filled with a real tracking code at load
  { k: "hy", label: "Both", q: "Maya Chen broken plates" },
];
const SOURCES = ["order", "shipment", "return", "conversation", "note"];
let lastQuery = "";

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

// ---------- init ----------
async function init() {
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    $$("[data-tab]").forEach((x) => x.setAttribute("aria-selected", x === b));
    $$("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== b.dataset.tab));
  }));

  $("#sourceChips").innerHTML = SOURCES.map((s) =>
    `<button type="button" class="chip toggle" aria-pressed="false" data-src="${s}">${s}</button>`).join("");
  $$("#sourceChips .chip").forEach((c) => c.addEventListener("click", () => {
    c.setAttribute("aria-pressed", c.getAttribute("aria-pressed") !== "true"); onFilterChange();
  }));
  ["#customer", "#dateFrom", "#dateTo", "#refund"].forEach((s) => $(s).addEventListener("change", onFilterChange));
  $("#clearFilters").addEventListener("click", () => {
    ["#customer", "#dateFrom", "#dateTo", "#refund"].forEach((s) => ($(s).value = ""));
    $$("#sourceChips .chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    onFilterChange();
  });
  $("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); run($("#q").value); });
  $("#closeDrawer").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

  try {
    const m = await api("/api/meta");
    const c = m.counts;
    $("#badges").innerHTML = `
      <span class="badge plain">Postgres ${esc(m.pg_version.split(" ")[0])}</span>
      <span class="badge plain">${c.orders} orders · ${c.returns} returns · ${c.conversations} chats · ${c.notes} notes</span>
      <span class="badge">${c.docs} indexed docs</span>`;
    $("#customer").insertAdjacentHTML("beforeend",
      m.customers.map((x) => `<option value="${esc(x.customer_id)}">${esc(x.name)} · ${esc(x.customer_id)}</option>`).join(""));
    if (m.sample_tracking) EXAMPLES.find((e) => e.q === null).q = m.sample_tracking;
  } catch (e) {
    $("#badges").innerHTML = `<span class="badge plain err">DB unavailable: ${esc(e.message)}</span>`;
  }
  $("#examples").innerHTML = EXAMPLES.filter((e) => e.q).map((e) =>
    `<button type="button" class="chip" data-q="${esc(e.q)}"><span class="k ${e.k}">${e.label}</span>${esc(e.q)}</button>`).join("");
  $$("#examples .chip").forEach((c) => c.addEventListener("click", () => { $("#q").value = c.dataset.q; run(c.dataset.q); }));

  const initial = new URLSearchParams(location.search).get("q");
  if (initial) { $("#q").value = initial; run(initial); }
}

function filterParams() {
  const p = new URLSearchParams();
  const set = (k, v) => v && p.set(k, v);
  set("customer_id", $("#customer").value);
  set("date_from", $("#dateFrom").value);
  set("date_to", $("#dateTo").value);
  set("refund_status", $("#refund").value);
  const src = $$("#sourceChips .chip[aria-pressed='true']").map((c) => c.dataset.src);
  set("sources", src.join(","));
  $("#filterCount").textContent = [...p.keys()].length || "";
  return p;
}
function onFilterChange() { filterParams(); if (lastQuery) run(lastQuery); }

// ---------- search ----------
async function run(q) {
  q = (q || "").trim();
  if (!q) return;
  lastQuery = q;
  const btn = $("#searchForm button");
  btn.disabled = true; btn.textContent = "Searching…";
  const p = filterParams(); p.set("q", q); p.set("limit", "10");
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  try {
    const r = await api("/api/search?" + p);
    render(r);
  } catch (e) {
    $("#results").classList.remove("hidden");
    $$("#results .list").forEach((l) => (l.innerHTML = `<li class="none-msg err">${esc(e.message)}</li>`));
  } finally {
    btn.disabled = false; btn.textContent = "Search";
  }
}

function highlight(text, q) {
  const terms = q.toLowerCase().split(/[^\p{L}\p{N}-]+/u).filter((t) => t.length > 2)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  let out = esc(text);
  if (!terms.length) return out;
  // prefix match approximates the english stemmer (arrived -> arriv*)
  const re = new RegExp(`\\b(${terms.map((t) => t.slice(0, Math.max(4, t.length - 2))).join("|")})[\\p{L}\\p{N}-]*`, "giu");
  return out.replace(re, "<mark>$&</mark>");
}

function render(r) {
  $("#empty").classList.add("hidden");
  $("#results").classList.remove("hidden");
  const q = r.query;
  const hybridIds = new Set();

  const orders = r.orders.rows;
  const top = orders[0];
  if (top) r.hybrid.rows.filter((d) => d.order_id === top.order_id).forEach((d) => hybridIds.add(d.doc_id));

  for (const mode of ["keyword", "vector", "hybrid"]) {
    const col = $(`.col[data-mode="${mode}"]`);
    const { rows, ms, sql } = r[mode];
    const emb = r.embed_ms < 5 ? " + embed cached" : ` + ${r.embed_ms} ms embed`;
    $(".col-meta", col).textContent = `${ms} ms${mode !== "keyword" ? emb : ""}`;
    $("pre", col).textContent = sql + "\n\n-- params: " + JSON.stringify(r.params) + (mode !== "keyword" ? "\n-- qvec: embedding of %(q)s from databricks-gte-large-en" : "");
    $(".list", col).innerHTML = rows.length ? rows.map((d, i) => item(d, i, mode, q, hybridIds)).join("")
      : `<li class="none-msg">${mode === "keyword" ? "No document shares a word with this query" : "No results"}</li>`;
    $$(".item", col).forEach((el) => el.addEventListener("click", () => openOrder(el.dataset.order)));
  }

  const best = $("#best");
  if (!top) { best.classList.add("hidden"); return; }
  const second = orders[1];
  const close = second && second.order_score / top.order_score > 0.8;
  best.classList.remove("hidden");
  best.innerHTML = `
    <span class="star">✦</span>
    <div><div class="lbl">Best matching order</div><div class="oid">${esc(top.order_id)}</div>
      <div class="why">${esc(top.customer_name)} · ${esc(top.items)}</div></div>
    <div class="facts">
      <span class="fact">${top.docs} matching doc${top.docs > 1 ? "s" : ""}: ${top.sources.join(", ")}</span>
      <span class="fact">refund: ${esc(top.refund_status || "no return")}</span>
      <span class="fact">best keyword #${top.best_keyword_rank ?? "–"} · vector #${top.best_vector_rank ?? "–"}</span>
      <span class="fact">Σ RRF ${top.order_score.toFixed(4)}</span>
      ${close ? `<span class="fact" style="border-color:var(--warn);color:var(--warn)">Close call with ${esc(second.order_id)}. Confirm with the customer</span>` : ""}
    </div>
    <span class="why">${r.orders.ms} ms · open order →</span>
    <details class="sql" onclick="event.stopPropagation()" style="flex-basis:100%"><summary>Order rollup SQL</summary><pre></pre></details>`;
  $("pre", best).textContent = r.orders.sql;
  best.onclick = () => openOrder(top.order_id);
}

function item(d, i, mode, q, hybridIds) {
  let score = "";
  if (mode === "keyword") score = `bm25 ${(-d.score).toFixed(2)}`;
  if (mode === "vector") score = `cos dist ${d.score.toFixed(3)}`;
  if (mode === "hybrid") score = `rrf ${d.rrf_score.toFixed(4)}`;
  const ranks = mode === "hybrid" ? `<div class="ranks">
      <span class="rk ${d.keyword_rank ? "kw" : "none"}">keyword #${d.keyword_rank ?? "–"}</span>
      <span class="rk ${d.vector_rank ? "vec" : "none"}">vector #${d.vector_rank ?? "–"}</span></div>` : "";
  const match = hybridIds.has(d.doc_id) ? " match" : "";
  return `<li class="item${match}" data-order="${esc(d.order_id)}" tabindex="0">
    <div class="row1"><span class="pos">${i + 1}</span><span class="src ${d.source}">${d.source}</span>
      <span class="oidtag">${esc(d.order_id)}</span><span class="score">${score}</span></div>
    <div class="title">${highlight(d.title, q)}</div>
    <div class="body">${highlight(d.body, q)}</div>${ranks}</li>`;
}

// ---------- order drawer ----------
async function openOrder(id) {
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#drawerBody").innerHTML = `<p class="none-msg">Loading ${esc(id)}…</p>`;
  try {
    const d = await api(`/api/orders/${encodeURIComponent(id)}`);
    $("#drawerBody").innerHTML = drawerHtml(d);
    $("#noteForm").addEventListener("submit", (e) => addNote(e, id));
  } catch (e) {
    $("#drawerBody").innerHTML = `<p class="err">${esc(e.message)}</p>`;
  }
}
function closeDrawer() {
  $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
}
function drawerHtml({ order: o, shipments, returns, conversations, notes }) {
  const s = shipments[0];
  const tl = [
    ...returns.map((r) => ({ when: r.created_at, what: `Return ${r.return_id} <span class="status ${r.refund_status}">${r.refund_status}</span>`, text: r.reason })),
    ...conversations.map((c) => ({ when: c.created_at, what: `${c.channel} · ${c.conversation_id}`, text: c.transcript })),
    ...notes.map((n) => ({ when: n.created_at, what: `Note by ${esc(n.author)}`, text: n.note })),
  ].sort((a, b) => a.when.localeCompare(b.when));
  return `
    <h2>${esc(o.order_id)}</h2>
    <p class="sub" style="font-size:15px">${esc(o.customer_name)} · ${esc(o.customer_id)} · ${esc(o.tier)}</p>
    <h3>Order</h3>
    <dl class="kv">
      <dt>Items</dt><dd>${esc(o.items)}</dd>
      <dt>Total</dt><dd>$${esc(o.total)}</dd>
      <dt>Placed</dt><dd>${esc(o.order_date)}</dd>
      <dt>Status</dt><dd>${esc(o.status)}</dd>
      ${s ? `<dt>Shipment</dt><dd>${esc(s.carrier)} <code>${esc(s.tracking_code)}</code> · ${esc(s.status)}${s.delivered_at ? " · delivered " + esc(s.delivered_at) : ""}</dd>` : ""}
    </dl>
    <h3>Support history</h3>
    ${tl.length ? `<ul class="tl">${tl.map((t) => `<li><div class="when">${esc(t.when)} · ${t.what}</div><div class="text">${esc(t.text)}</div></li>`).join("")}</ul>`
      : `<p class="none-msg">No returns, conversations or notes.</p>`}
    <h3>Add a service note (live row)</h3>
    <form class="note-form" id="noteForm">
      <textarea name="note" required minlength="3" placeholder="e.g. Customer says the lid was bent and the seal leaks"></textarea>
      <span class="hint">Writes to retail.service_notes and retail.support_docs with an embedding. Search for it right away.</span>
      <button class="btn primary" type="submit">Save note</button>
    </form>`;
}
async function addNote(e, id) {
  e.preventDefault();
  const f = e.target, btn = $("button", f);
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const r = await api(`/api/orders/${encodeURIComponent(id)}/notes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: f.note.value }),
    });
    toast(`Saved ${r.note_id} — it is searchable now`);
    openOrder(id);
  } catch (err) {
    toast("Failed: " + err.message);
    btn.disabled = false; btn.textContent = "Save note";
  }
}

init();
