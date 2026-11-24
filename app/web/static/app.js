/* Keitaro Wrapper UI: vanilla JS, no build step. */
(function () {
  "use strict";

  const SERIES = 8; // fixed categorical slots; positions >= 8 fold into "other"

  // ---------- helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function api(method, url, body) {
    const opts = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(url, opts);
    } catch {
      throw new ApiError("The wrapper server is not reachable. Is it running?", 0);
    }
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (!resp.ok) throw new ApiError((data && data.detail) || `Request failed (${resp.status})`, resp.status);
    return data;
  }

  function toast(msg, kind) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : "");
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 6000 : 3000);
  }

  async function busy(btn, fn) {
    if (btn) {
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
    }
    try {
      return await fn();
    } finally {
      if (btn && btn.isConnected) {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
      }
    }
  }

  function alertBox(kind, html) {
    return `<div class="alert alert-${kind}" role="${kind === "error" ? "alert" : "status"}"><div class="grow">${html}</div></div>`;
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  const regionNames = (() => {
    try {
      return new Intl.DisplayNames(["en"], { type: "region" });
    } catch {
      return null;
    }
  })();

  // ---------- offer autocomplete ----------
  let acCounter = 0;
  class OfferAutocomplete {
    constructor(host, { placeholder = "Search offers by name or ID", onPick, exclude } = {}) {
      const id = `ac-${++acCounter}`;
      this.onPick = onPick;
      this.exclude = exclude || (() => new Set());
      this.items = [];
      this.active = -1;
      this.selected = null;
      this.seq = 0;
      host.classList.add("ac");
      const labelled = host.dataset.label ? `aria-labelledby="${host.dataset.label}"` : `aria-label="${esc(placeholder)}"`;
      host.innerHTML = `
        <input type="search" id="${id}-input" role="combobox" aria-autocomplete="list" aria-expanded="false"
               aria-controls="${id}-list" autocomplete="off" placeholder="${esc(host.dataset.placeholder || placeholder)}" ${labelled}>
        <ul class="ac-list" id="${id}-list" role="listbox" hidden></ul>`;
      this.input = host.querySelector("input");
      this.list = host.querySelector("ul");
      this.listId = `${id}-list`;
      const search = debounce(() => this.search(), 250);
      this.input.addEventListener("input", () => {
        this.selected = null;
        search();
      });
      this.input.addEventListener("focus", () => {
        if (!this.selected) this.search();
      });
      this.input.addEventListener("keydown", (e) => this.key(e));
      this.input.addEventListener("blur", () => setTimeout(() => this.close(), 150));
      this.list.addEventListener("mousedown", (e) => {
        const li = e.target.closest("li[data-i]");
        if (li) {
          e.preventDefault();
          this.pick(Number(li.dataset.i));
        }
      });
    }

    async search() {
      const q = this.input.value.trim();
      const seq = ++this.seq;
      try {
        const rows = await api("GET", `/api/offers?q=${encodeURIComponent(q)}&limit=20`);
        if (seq !== this.seq) return; // stale response
        const ex = this.exclude();
        this.items = rows.filter((r) => !ex.has(r.id));
        this.render(q);
      } catch (err) {
        if (seq !== this.seq) return;
        this.items = [];
        this.list.innerHTML = `<li class="ac-empty">${esc(err.message)}</li>`;
        this.open();
      }
    }

    render(q) {
      this.active = this.items.length ? 0 : -1;
      this.list.innerHTML = this.items.length
        ? this.items
            .map(
              (o, i) =>
                `<li role="option" id="${this.listId}-${i}" data-i="${i}" aria-selected="${i === this.active}">` +
                `<span class="id">#${o.id}</span><span class="nm">${esc(o.name)}</span></li>`
            )
            .join("")
        : `<li class="ac-empty">No offers match “${esc(q)}”</li>`;
      this.open();
      this.highlight();
    }

    highlight() {
      this.list.querySelectorAll("li[data-i]").forEach((li) => {
        const on = Number(li.dataset.i) === this.active;
        li.setAttribute("aria-selected", String(on));
        if (on) li.scrollIntoView({ block: "nearest" });
      });
      this.input.setAttribute("aria-activedescendant", this.active >= 0 ? `${this.listId}-${this.active}` : "");
    }

    key(e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (this.list.hidden) return this.search();
        const n = this.items.length;
        if (!n) return;
        this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
        this.highlight();
      } else if (e.key === "Enter") {
        if (!this.list.hidden && this.active >= 0) {
          e.preventDefault();
          this.pick(this.active);
        }
      } else if (e.key === "Escape") {
        this.close();
      }
    }

    pick(i) {
      const o = this.items[i];
      if (!o) return;
      this.selected = o;
      this.input.value = `#${o.id} ${o.name}`;
      this.close();
      this.onPick && this.onPick(o);
    }

    open() {
      this.list.hidden = false;
      this.input.setAttribute("aria-expanded", "true");
    }

    close() {
      this.list.hidden = true;
      this.input.setAttribute("aria-expanded", "false");
    }

    reset() {
      this.selected = null;
      this.input.value = "";
    }
  }

  // ---------- page: new campaign ----------
  function initCreatePage(prefix) {
    const form = $("#create-form");
    const nameEl = $("#f-name");
    const geoEl = $("#f-geo");
    const selects = { domain: $("#f-domain"), group: $("#f-group"), source: $("#f-source") };
    let offer = null;

    const ac = new OfferAutocomplete($("#offer-ac"), {
      onPick: (o) => {
        offer = o;
        $("#offer-picked").textContent = `Selected: #${o.id} ${o.name}`;
        $("#r-offer").textContent = `Offer #${o.id} ${o.name}`;
      },
    });
    ac.input.addEventListener("input", () => {
      offer = null;
      $("#offer-picked").textContent = "Nothing selected";
      $("#r-offer").textContent = "Offer not selected";
    });

    const stripPrefix = (v) => (v.startsWith(prefix) ? v.slice(prefix.length) : v);
    nameEl.addEventListener("input", () => {
      $("#r-name").textContent = prefix + (stripPrefix(nameEl.value.trim()) || "…");
    });
    nameEl.addEventListener("paste", () =>
      setTimeout(() => {
        nameEl.value = stripPrefix(nameEl.value.trim());
        nameEl.dispatchEvent(new Event("input"));
      })
    );

    function geoState() {
      const code = geoEl.value.trim().toUpperCase();
      const name = code.length === 2 && regionNames ? regionNames.of(code) : null;
      const valid = /^[A-Z]{2}$/.test(code) && name && name !== code;
      return { code, name, valid };
    }
    geoEl.addEventListener("input", () => {
      geoEl.value = geoEl.value.replace(/[^a-z]/gi, "").toUpperCase();
      const g = geoState();
      $("#r-geo").textContent = g.code || "??";
      $("#geo-name").textContent = !g.code
        ? "ISO-2 country code, e.g. MX, AU, RO"
        : g.valid
          ? g.name
          : g.code.length === 2
            ? "Unknown country code"
            : "Two letters";
      geoEl.setAttribute("aria-invalid", g.code.length === 2 && !g.valid ? "true" : "false");
    });

    // catalog dropdowns
    (async () => {
      try {
        const cat = await api("GET", "/api/catalog");
        const fill = (sel, rows, def) => {
          sel.innerHTML = rows
            .map((r) => `<option value="${r.id}" ${r.id === def ? "selected" : ""}>${esc(r.name)} (#${r.id})</option>`)
            .join("");
          if (!rows.length) sel.innerHTML = `<option value="">Nothing in Keitaro</option>`;
          sel.disabled = !rows.length;
        };
        fill(selects.domain, cat.domains, cat.defaults.domain_id);
        fill(selects.group, cat.groups, cat.defaults.group_id);
        fill(selects.source, cat.sources, cat.defaults.source_id);
      } catch (err) {
        Object.values(selects).forEach((s) => (s.innerHTML = `<option value="">Unavailable</option>`));
        showError(`Could not load domains, groups and sources from Keitaro. ${err.message}`);
      }
    })();

    function showError(msg) {
      const box = $("#form-error");
      box.innerHTML = alertBox("error", esc(msg));
      box.hidden = false;
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      $("#form-error").hidden = true;
      const name = stripPrefix(nameEl.value.trim());
      const g = geoState();
      const problems = [];
      if (!name) problems.push("Enter a campaign name.");
      if (!g.valid) problems.push("Enter a valid two-letter country code, for example MX.");
      if (!offer) problems.push("Pick an offer from the list.");
      for (const [k, s] of Object.entries(selects)) if (!s.value) problems.push(`Choose a ${k}.`);
      if (problems.length) return showError(problems.join(" "));

      const btn = $("#create-btn");
      await busy(btn, async () => {
        $("#form-hint").textContent = "Creating the campaign and 2 streams in Keitaro…";
        try {
          const res = await api("POST", "/api/campaigns", {
            name,
            geo: g.code,
            offer_id: offer.id,
            domain_id: Number(selects.domain.value),
            group_id: Number(selects.group.value),
            source_id: Number(selects.source.value),
          });
          $("#result").innerHTML = `
            <section class="panel success-card" aria-live="polite">
              <div class="panel-body">
                <h2>Campaign created</h2>
                <div><b class="mono">${esc(res.name)}</b> <span class="muted">· Keitaro #${res.keitaro_id}</span></div>
                <div class="muted">Stream 1: ${esc(g.code)} → Google. Stream 2: everyone else → offer #${offer.id} at 100%.</div>
                <div class="success-links">
                  <a class="btn btn-primary" href="${esc(res.editor_url)}">Open in editor</a>
                  <a class="btn" href="${esc(res.keitaro_url)}" target="_blank" rel="noopener">View in Keitaro ↗</a>
                </div>
              </div>
            </section>`;
          toast("Campaign created");
          form.reset();
          ac.reset();
          offer = null;
          nameEl.dispatchEvent(new Event("input"));
          geoEl.dispatchEvent(new Event("input"));
          ac.input.dispatchEvent(new Event("input"));
        } catch (err) {
          showError(err.message);
        } finally {
          $("#form-hint").textContent = "";
        }
      });
    });
  }

  // ---------- page: editor ----------
  const ICON_LOCK =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>';
  const ICON_UNLOCK =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 4.9-.7"/></svg>';

  function seriesColor(i) {
    return i < SERIES ? `var(--s${i + 1})` : "var(--s-other)";
  }

  function initEditorPage(initialId) {
    const select = $("#campaign-select");
    const fetchBtn = $("#fetch-btn");
    const root = $("#campaign");
    const msg = $("#fetch-msg");
    let campaign = null;
    const acs = new Map();
    const conflicts = new Set(); // stream ids with a pending 409

    async function loadList() {
      try {
        const rows = await api("GET", "/api/campaigns");
        const opts = rows.map((c) => `<option value="${c.id}">${esc(c.name)} (#${c.id})</option>`);
        if (initialId && !rows.some((c) => c.id === initialId))
          opts.unshift(`<option value="${initialId}">Campaign #${initialId}</option>`);
        select.innerHTML = opts.length ? opts.join("") : `<option value="">No test_ campaigns yet</option>`;
        select.disabled = fetchBtn.disabled = !opts.length;
        if (initialId) select.value = String(initialId);
      } catch (err) {
        select.innerHTML = `<option value="">Unavailable</option>`;
        msg.innerHTML = alertBox("error", `Could not load campaigns from Keitaro. ${esc(err.message)}`);
      }
    }

    async function loadLocal(id) {
      try {
        campaign = await api("GET", `/api/campaigns/${id}`);
        render();
      } catch (err) {
        if (err.status === 404) return doFetch(id); // first visit: pull from Keitaro
        msg.innerHTML = alertBox("error", esc(err.message));
      }
    }

    async function doFetch(id) {
      msg.innerHTML = "";
      if (!campaign || campaign.keitaro_id !== Number(id)) root.innerHTML = `<div class="skeleton" style="margin-top:28px"></div>`;
      await busy(fetchBtn, async () => {
        try {
          const r = await api("POST", `/api/campaigns/${id}/fetch`);
          campaign = r.campaign;
          conflicts.clear();
          const notes = [];
          if (r.skipped_dirty.length)
            notes.push(
              alertBox(
                "warn",
                `<b>Not refreshed:</b> ${r.skipped_dirty.map(esc).join(", ")} ${r.skipped_dirty.length > 1 ? "have" : "has"} unpublished changes. Push or Cancel ${r.skipped_dirty.length > 1 ? "them" : "it"}, then fetch again.`
              )
            );
          if (r.offers_marked_removed)
            notes.push(alertBox("warn", `${r.offers_marked_removed} offer(s) are no longer in Keitaro and were marked as removed. Use Bring back to restore them.`));
          if (r.deleted_streams.length)
            notes.push(alertBox("warn", `Deleted in Keitaro: ${r.deleted_streams.map(esc).join(", ")}.`));
          msg.innerHTML = notes.length ? `<div style="display:grid;gap:8px;margin-top:16px">${notes.join("")}</div>` : "";
          toast(`Fetched ${r.streams_total} stream(s) from Keitaro`);
          if (location.pathname !== `/campaigns/${id}`) history.replaceState(null, "", `/campaigns/${id}`);
          render();
        } catch (err) {
          msg.innerHTML = `<div style="margin-top:16px">${alertBox("error", esc(err.message))}</div>`;
          if (!campaign) root.innerHTML = "";
        }
      });
    }

    $("#picker-form").addEventListener("submit", (e) => {
      e.preventDefault();
      if (select.value) doFetch(select.value);
    });

    function render() {
      if (!campaign) return;
      const c = campaign;
      const dirty = c.streams.filter((s) => s.is_dirty).length;
      const synced = c.synced_at ? new Date(c.synced_at).toLocaleString() : "never";
      root.innerHTML = `
        <div class="campaign-head">
          <div>
            <h1>${esc(c.name)}</h1>
            <div class="meta"><span>Keitaro #${c.keitaro_id}</span><span>Fetched ${esc(synced)}</span>
              <span>${c.streams.length} stream(s)${dirty ? ` · <b style="color:var(--draft-fg)">${dirty} unpublished</b>` : ""}</span></div>
          </div>
          <a class="btn btn-sm" href="${esc(c.keitaro_url)}" target="_blank" rel="noopener">Open in Keitaro ↗</a>
        </div>
        <div class="legend-line" aria-hidden="true">
          <span><i style="background:var(--surface)"></i>Published</span>
          <span><i style="background:var(--draft-bg);border-color:var(--draft-line)"></i>Unpublished changes</span>
          <span><i style="background:var(--removed-bg)"></i>Removed offer</span>
        </div>
        <div class="streams">${c.streams.map(streamHtml).join("") || `<div class="empty-state"><h2>No streams</h2>This campaign has no streams in Keitaro.</div>`}</div>`;
      acs.clear();
      c.streams.filter((s) => s.has_offers).forEach((s) => {
        const host = root.querySelector(`[data-ac="${s.id}"]`);
        const btn = root.querySelector(`[data-add="${s.id}"]`);
        let picked = null;
        const ac = new OfferAutocomplete(host, {
          placeholder: "Find an offer to add",
          exclude: () => new Set(currentStream(s.id).offers.filter((o) => o.status === "active").map((o) => o.offer_id)),
          onPick: (o) => {
            picked = o;
            btn.disabled = false;
            btn.focus();
          },
        });
        ac.input.addEventListener("input", () => {
          picked = null;
          btn.disabled = true;
        });
        btn.addEventListener("click", () =>
          act(btn, s.id, "POST", `/api/streams/${s.id}/offers`, { offer_id: picked.id }, `Added #${picked.id}. Push to publish.`)
        );
        acs.set(s.id, ac);
      });
    }

    const currentStream = (id) => campaign.streams.find((s) => s.id === id);

    function streamHtml(s) {
      if (!s.has_offers) {
        return `
          <article class="stream plain" data-stream="${s.id}">
            <div class="stream-head">
              <div class="title"><span class="pos">#${s.position}</span><h2>${esc(s.name)}</h2></div>
              <span class="kind mono">stream ${s.keitaro_id} · no offers</span>
            </div>
          </article>`;
      }
      const active = s.offers.filter((o) => o.status === "active");
      const total = active.reduce((a, o) => a + o.share, 0);
      const color = new Map(s.offers.map((o, i) => [o.id, seriesColor(i)]));
      const bar = active.length
        ? active
            .map(
              (o) =>
                `<div class="seg" style="flex:0 0 calc(${o.share}% - 2px);background:${color.get(o.id)}" title="#${o.offer_id} ${esc(o.name)}: ${o.share}%">${o.share >= 8 ? o.share + "%" : ""}</div>`
            )
            .join("")
        : `<div class="empty">No active offers</div>`;
      const conflict = conflicts.has(s.id)
        ? `<div class="alert alert-error" role="alert"><div class="grow">Offers of this stream were changed in Keitaro after your last fetch. <b>Push anyway</b> overwrites them with your draft. <b>Cancel</b>, then <b>Fetch streams</b>, loads the Keitaro version.</div><button class="btn btn-sm" data-force="${s.id}">Push anyway</button></div>`
        : "";
      return `
        <article class="stream ${s.is_dirty ? "dirty" : ""}" data-stream="${s.id}" aria-label="Stream ${esc(s.name)}">
          <div class="stream-head">
            <div class="title">
              <span class="pos">#${s.position}</span>
              <h2>${esc(s.name)}</h2>
              <span class="state ${s.is_dirty ? "state-dirty" : "state-clean"}">${s.is_dirty ? "Unpublished changes" : "Published"}</span>
            </div>
            <div class="stream-actions">
              ${s.is_dirty ? `<button class="btn btn-ghost btn-sm" data-cancel="${s.id}">Cancel</button>` : ""}
              <button class="btn btn-push btn-sm" data-push="${s.id}" ${!s.is_dirty || s.problem ? "disabled" : ""}
                title="${s.is_dirty ? (s.problem ? esc(s.problem) : "Send offers and weights to Keitaro") : "Nothing to publish"}">Push</button>
            </div>
          </div>
          <div class="stream-body">
            <div class="sharebar" role="img" aria-label="Traffic split: ${active.map((o) => `offer ${o.offer_id} ${o.share}%`).join(", ") || "no active offers"}">${bar}</div>
            ${s.problem && (s.is_dirty || active.length === 0) ? alertBox("warn", esc(s.problem)) : ""}
            ${conflict}
            <div class="offers-wrap">
              <table class="offers">
                <thead><tr><th class="c-sw"></th><th>Offer</th><th class="c-id">ID</th><th class="c-w">Weight <span class="muted num">(Σ ${total}%)</span></th><th class="c-act"></th></tr></thead>
                <tbody>${s.offers.map((o) => offerRow(s, o, color.get(o.id))).join("") || `<tr><td colspan="5" class="muted">No offers yet. Add one below.</td></tr>`}</tbody>
              </table>
            </div>
            <div class="add-row">
              <div data-ac="${s.id}"></div>
              <button class="btn" data-add="${s.id}" disabled>Add</button>
            </div>
          </div>
        </article>`;
    }

    function offerRow(s, o, color) {
      const removed = o.status === "removed";
      const was =
        s.is_dirty && o.changed && !o.added_in_draft && o.published_share !== o.share
          ? `<span class="was" title="Published in Keitaro">${o.published_share}%</span>`
          : "";
      const weight = removed
        ? `<span class="val">0%</span>${was}`
        : o.pinned
          ? `<input type="number" min="0" max="100" step="1" value="${o.share}" data-pinval="${o.id}" aria-label="Pinned weight of offer ${o.offer_id}"><span>%</span>${was}`
          : `<span class="val">${o.share}%</span>${was}`;
      const pin = removed
        ? `<button class="icon-btn" disabled title="Removed offers cannot be pinned">${ICON_UNLOCK}</button>`
        : `<button class="icon-btn" data-pin="${o.id}" aria-pressed="${o.pinned}" title="${o.pinned ? "Unpin weight" : "Pin weight"}" aria-label="${o.pinned ? "Unpin" : "Pin"} weight of offer ${o.offer_id}">${o.pinned ? ICON_LOCK : ICON_UNLOCK}</button>`;
      const action = removed
        ? `<button class="btn btn-sm" data-restore="${o.id}">Bring back</button>`
        : `<button class="btn btn-ghost btn-sm btn-danger-text" data-remove="${o.id}">Remove</button>`;
      return `
        <tr class="${removed ? "removed" : ""}" data-link="${o.id}">
          <td class="c-sw"><span class="sw" style="background:${color}"></span></td>
          <td><span class="oname">${esc(o.name)}</span>${o.added_in_draft ? '<span class="tag-new">new</span>' : ""}${removed ? '<span class="status-removed">removed</span>' : ""}</td>
          <td class="c-id mono">${o.offer_id}</td>
          <td class="c-w"><div class="weight">${pin}${weight}</div></td>
          <td class="c-act">${action}</td>
        </tr>`;
    }

    function replaceStream(updated) {
      const i = campaign.streams.findIndex((s) => s.id === updated.id);
      if (i >= 0) campaign.streams[i] = updated;
    }

    async function act(btn, sid, method, url, body, okMsg) {
      await busy(btn, async () => {
        try {
          const updated = await api(method, url, body);
          replaceStream(updated);
          conflicts.delete(sid);
          if (okMsg) toast(okMsg);
          render();
          const card = root.querySelector(`[data-stream="${sid}"]`);
          card && card.scrollIntoView({ block: "nearest" });
        } catch (err) {
          if (err.status === 409) {
            conflicts.add(sid);
            render();
          } else {
            toast(err.message, "error");
          }
        }
      });
    }

    root.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      const card = b.closest("[data-stream]");
      if (!card) return;
      const sid = Number(card.dataset.stream);
      const d = b.dataset;
      if (d.push) act(b, sid, "POST", `/api/streams/${sid}/push`, {}, "Pushed to Keitaro");
      else if (d.force) act(b, sid, "POST", `/api/streams/${sid}/push`, { force: true }, "Pushed to Keitaro (overwritten)");
      else if (d.cancel) act(b, sid, "POST", `/api/streams/${sid}/cancel`, undefined, "Draft discarded");
      else if (d.remove) act(b, sid, "POST", `/api/streams/${sid}/offers/${d.remove}/remove`);
      else if (d.restore) act(b, sid, "POST", `/api/streams/${sid}/offers/${d.restore}/restore`);
      else if (d.pin) {
        const on = b.getAttribute("aria-pressed") !== "true";
        act(b, sid, "PUT", `/api/streams/${sid}/offers/${d.pin}/pin`, { pinned: on });
      }
    });

    // editing a pinned value: commit on change (blur / Enter)
    root.addEventListener("change", (e) => {
      const inp = e.target.closest("input[data-pinval]");
      if (!inp) return;
      const sid = Number(inp.closest("[data-stream]").dataset.stream);
      const v = Number(inp.value);
      if (!Number.isInteger(v) || v < 0 || v > 100) {
        toast("Weight must be a whole number from 0 to 100", "error");
        render();
        return;
      }
      act(null, sid, "PUT", `/api/streams/${sid}/offers/${inp.dataset.pinval}/pin`, { pinned: true, share: v });
    });
    root.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("input[data-pinval]")) e.target.blur();
    });

    // leaving with unpublished drafts is fine (they are saved), but tell the user
    loadList();
    if (initialId) loadLocal(initialId);
    else
      root.innerHTML = `<div class="empty-state" style="margin-top:28px"><h2>Pick a campaign</h2>Choose a campaign above and press <b>Fetch streams</b> to load its streams from Keitaro.</div>`;
  }

  window.KW = { initCreatePage, initEditorPage };
})();
