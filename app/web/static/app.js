/* Keitaro Wrapper UI: vanilla JS, no build step. */
(function () {
  "use strict";

  const SERIES = 8; // fixed categorical slots; positions >= 8 fold into "other"

  // ---------- helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

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
      throw new ApiError("The wrapper server is not reachable. Check that it is running and reload the page.", 0);
    }
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (!resp.ok) {
      const fallback =
        resp.status >= 500
          ? `The server hit an error (${resp.status}). Try again; if it repeats, check the server logs.`
          : `Request failed (${resp.status}).`;
      throw new ApiError((data && data.detail) || fallback, resp.status);
    }
    return data;
  }

  function toast(msg, kind) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : "");
    el.textContent = msg;
    box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 3000);
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

  function alertBox(kind, html, extra = "") {
    return `<div class="alert alert-${kind}" role="${kind === "error" ? "alert" : "status"}"><div class="grow">${html}</div>${extra}</div>`;
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
    constructor(host, { placeholder = "Search offers by name or ID", label, onPick, onClear, exclude } = {}) {
      const id = `ac-${++acCounter}`;
      this.onPick = onPick;
      this.onClear = onClear;
      this.exclude = exclude || (() => new Set());
      this.items = [];
      this.active = -1;
      this.selected = null;
      this.seq = 0;
      this.host = host;
      host.classList.add("ac");
      const labelled = host.dataset.label ? `aria-labelledby="${host.dataset.label}"` : `aria-label="${esc(label || placeholder)}"`;
      host.innerHTML = `
        <input type="search" id="${id}-input" role="combobox" aria-autocomplete="list" aria-expanded="false"
               aria-controls="${id}-list" autocomplete="off" placeholder="${esc(host.dataset.placeholder || placeholder)}" ${labelled}>
        <ul class="ac-list" id="${id}-list" role="listbox" hidden></ul>
        <span class="sr-only" aria-live="polite"></span>`;
      this.input = host.querySelector("input");
      this.list = host.querySelector("ul");
      this.live = host.querySelector(".sr-only");
      this.listId = `${id}-list`;
      const search = debounce(() => this.search(), 250);
      this.input.addEventListener("input", () => {
        if (this.selected) {
          this.selected = null;
          this.onClear && this.onClear();
        }
        search();
      });
      this.input.addEventListener("focus", () => {
        if (!this.selected) this.search();
      });
      this.input.addEventListener("keydown", (e) => this.key(e));
      this.list.addEventListener("mousedown", (e) => {
        const li = e.target.closest("li[data-i]");
        if (li) {
          e.preventDefault();
          this.pick(Number(li.dataset.i));
        }
      });
      this.list.addEventListener("mousemove", (e) => {
        const li = e.target.closest("li[data-i]");
        if (li && Number(li.dataset.i) !== this.active) {
          this.active = Number(li.dataset.i);
          this.highlight(false);
        }
      });
      this._outside = (e) => {
        if (!host.isConnected) return document.removeEventListener("mousedown", this._outside);
        if (!host.contains(e.target)) this.close();
      };
      document.addEventListener("mousedown", this._outside);
      this.input.addEventListener("blur", () => setTimeout(() => this.close(), 150));
    }

    async search() {
      const q = this.input.value.trim();
      const seq = ++this.seq;
      try {
        const rows = await api("GET", `/api/offers?q=${encodeURIComponent(q)}&limit=20`);
        if (seq !== this.seq || document.activeElement !== this.input) return; // stale or user left
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
                `<li role="option" id="${this.listId}-${i}" data-i="${i}" aria-selected="false">` +
                `<span class="id">#${o.id}</span><span class="nm">${esc(o.name)}</span></li>`
            )
            .join("")
        : `<li class="ac-empty">No offers match “${esc(q)}”</li>`;
      this.live.textContent = this.items.length ? plural(this.items.length, "offer found", "offers found") : "No offers found";
      this.open();
      this.highlight(true);
    }

    highlight(scroll) {
      this.list.querySelectorAll("li[data-i]").forEach((li) => {
        const on = Number(li.dataset.i) === this.active;
        li.setAttribute("aria-selected", String(on));
        if (on && scroll) li.scrollIntoView({ block: "nearest" });
      });
      if (this.active >= 0) this.input.setAttribute("aria-activedescendant", `${this.listId}-${this.active}`);
      else this.input.removeAttribute("aria-activedescendant");
    }

    key(e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (this.list.hidden) return this.search();
        const n = this.items.length;
        if (!n) return;
        this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
        this.highlight(true);
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
      this.input.removeAttribute("aria-activedescendant");
    }

    reset() {
      this.seq++; // drop in-flight searches
      this.selected = null;
      this.input.value = "";
      this.close();
    }
  }

  // ---------- page: new campaign ----------
  function initCreatePage(prefix) {
    const form = $("#create-form");
    const nameEl = $("#f-name");
    const geoEl = $("#f-geo");
    const selects = { domain: $("#f-domain"), group: $("#f-group"), source: $("#f-source") };
    let offer = null;

    function setOffer(o) {
      offer = o;
      $("#offer-picked").textContent = o ? `Selected: #${o.id} ${o.name}` : "Nothing selected";
      $("#r-offer").textContent = o ? `Offer #${o.id} ${o.name}` : "Offer not selected";
      if (o) fieldError("offer", null);
    }

    const ac = new OfferAutocomplete($("#offer-ac"), { onPick: setOffer, onClear: () => setOffer(null) });

    const stripPrefix = (v) => (v.startsWith(prefix) ? v.slice(prefix.length) : v);
    function syncName() {
      $("#r-name").textContent = prefix + (stripPrefix(nameEl.value.trim()) || "…");
    }
    nameEl.addEventListener("input", () => {
      syncName();
      if (nameEl.value.trim()) fieldError("name", null);
    });
    nameEl.addEventListener("paste", () =>
      setTimeout(() => {
        nameEl.value = stripPrefix(nameEl.value.trim());
        syncName();
      })
    );

    function geoState() {
      const code = geoEl.value.trim().toUpperCase();
      const name = code.length === 2 && regionNames ? regionNames.of(code) : null;
      const valid = /^[A-Z]{2}$/.test(code) && !!name && name !== code && name !== "Unknown Region";
      return { code, name, valid };
    }
    function syncGeo() {
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
      if (g.valid) fieldError("geo", null);
    }
    geoEl.addEventListener("input", () => {
      geoEl.value = geoEl.value.replace(/[^a-z]/gi, "").toUpperCase();
      syncGeo();
    });

    function fieldError(key, msg) {
      const el = $(`#err-${key}`);
      if (!el) return;
      el.textContent = msg || "";
      el.hidden = !msg;
      const ctl = { name: nameEl, geo: geoEl, offer: ac.input, ...selects }[key];
      if (ctl && key !== "geo") ctl.setAttribute("aria-invalid", msg ? "true" : "false");
      if (ctl && key === "geo" && msg) ctl.setAttribute("aria-invalid", "true");
    }

    // catalog dropdowns
    (async () => {
      try {
        const cat = await api("GET", "/api/catalog");
        const fill = (sel, rows, def) => {
          sel.innerHTML = rows.length
            ? rows.map((r) => `<option value="${Number(r.id)}" title="${esc(r.name)} · ID ${Number(r.id)}" ${r.id === def ? "selected" : ""}>${esc(r.name)}</option>`).join("")
            : `<option value="">Nothing in Keitaro</option>`;
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
      const errors = {
        name: name ? null : "Enter a campaign name.",
        geo: g.valid ? null : "Enter a valid two-letter country code, for example MX.",
        offer: offer ? null : "Pick an offer from the list.",
      };
      for (const [k, s] of Object.entries(selects)) errors[k] = s.value ? null : `Choose a ${k === "source" ? "traffic source" : k}.`;
      Object.entries(errors).forEach(([k, m]) => fieldError(k, m));
      const first = Object.entries(errors).find(([, m]) => m);
      if (first) {
        ({ name: nameEl, geo: geoEl, offer: ac.input, ...selects })[first[0]].focus();
        return;
      }

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
            <section class="panel success-card" tabindex="-1" aria-live="polite">
              <div class="panel-body">
                <h2>Campaign created</h2>
                <div><b class="mono">${esc(res.name)}</b> <span class="muted">· Keitaro #${Number(res.keitaro_id)}</span></div>
                <div class="muted">Stream 1: ${esc(g.code)} → Google. Stream 2: everyone else → offer #${offer.id} at 100%.</div>
                <div class="success-links">
                  <a class="btn btn-primary" href="${esc(res.editor_url)}">Open in editor</a>
                  <a class="btn" href="${esc(res.keitaro_url)}" target="_blank" rel="noopener">View in Keitaro ↗</a>
                </div>
              </div>
            </section>`;
          const card = $("#result .success-card");
          card.scrollIntoView({ block: "nearest", behavior: "smooth" });
          card.focus({ preventScroll: true });
          toast("Campaign created");
          form.reset();
          ac.reset();
          setOffer(null);
          syncName();
          syncGeo();
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

  const seriesColor = (i) => (i < SERIES ? `var(--s${i + 1})` : "var(--s-other)");

  function draftSummary(s) {
    let added = 0, removed = 0, restored = 0, weights = 0;
    for (const o of s.offers) {
      if (o.status === "active" && o.added_in_draft) added++;
      else if (o.status === "removed" && o.published_status === "active") removed++;
      else if (o.status === "active" && o.published_status === "removed") restored++;
      else if (o.status === "active" && o.share !== o.published_share) weights++;
    }
    const parts = [];
    if (added) parts.push(`+${plural(added, "offer", "offers")}`);
    if (restored) parts.push(`${plural(restored, "offer", "offers")} back`);
    if (removed) parts.push(`−${plural(removed, "offer", "offers")}`);
    if (weights) parts.push(plural(weights, "weight changed", "weights changed"));
    return { text: parts.join(" · ") || "weights changed", count: added + removed + restored + weights || 1 };
  }

  function initEditorPage(initialId, prefix) {
    const select = $("#campaign-select");
    const fetchBtn = $("#fetch-btn");
    const root = $("#campaign");
    const msg = $("#fetch-msg");
    let campaign = null;
    const conflicts = new Map(); // stream id -> message of a pending 409
    const notRefreshed = new Set(); // dirty streams skipped by the last fetch
    const confirmCancel = new Set();
    const queues = new Map(); // stream id -> promise chain (one request at a time per stream)

    // ----- campaign list -----
    async function loadList() {
      try {
        const rows = await api("GET", "/api/campaigns");
        const opts = rows.map(
          (c) => `<option value="${Number(c.id)}">${esc(c.name)} (#${Number(c.id)})${c.has_draft ? " • draft" : ""}</option>`
        );
        if (initialId && !rows.some((c) => c.id === initialId))
          opts.unshift(`<option value="${Number(initialId)}">Campaign #${Number(initialId)}</option>`);
        const any = opts.length > 0;
        if (any && !initialId) opts.unshift(`<option value="" disabled selected>Choose a campaign…</option>`);
        select.innerHTML = any ? opts.join("") : `<option value="">No ${esc(prefix)}… campaigns yet. Create one first.</option>`;
        select.disabled = fetchBtn.disabled = !any;
        if (initialId) select.value = String(initialId);
      } catch (err) {
        if (initialId) {
          select.innerHTML = `<option value="${Number(initialId)}">Campaign #${Number(initialId)}</option>`;
          select.disabled = fetchBtn.disabled = false;
        } else {
          select.innerHTML = `<option value="">Unavailable</option>`;
        }
        msg.innerHTML = alertBox(
          "error",
          `Could not load the campaign list from Keitaro. ${esc(err.message)}`,
          `<button class="btn btn-sm" type="button" id="retry-list">Retry</button>`
        );
        $("#retry-list").addEventListener("click", () => {
          msg.innerHTML = "";
          loadList();
        });
      }
    }

    select.addEventListener("change", () => {
      if (!select.value) return;
      msg.innerHTML = "";
      history.replaceState(null, "", `/campaigns/${Number(select.value)}`);
      loadLocal(select.value);
    });

    async function loadLocal(id) {
      root.innerHTML = `<div class="skeleton"></div>`;
      try {
        campaign = await api("GET", `/api/campaigns/${id}`);
        resetState();
        render();
      } catch (err) {
        campaign = null;
        if (err.status === 404)
          root.innerHTML = `<div class="empty-state"><h2>Not loaded yet</h2>Press <b>Fetch streams</b> to load this campaign's streams from Keitaro.</div>`;
        else root.innerHTML = alertBox("error", esc(err.message));
      }
    }

    function resetState() {
      conflicts.clear();
      notRefreshed.clear();
      confirmCancel.clear();
    }

    async function doFetch(id) {
      msg.innerHTML = "";
      if (!campaign || campaign.keitaro_id !== Number(id)) root.innerHTML = `<div class="skeleton"></div>`;
      await busy(fetchBtn, async () => {
        try {
          const r = await api("POST", `/api/campaigns/${id}/fetch`);
          const switched = !campaign || campaign.keitaro_id !== r.campaign.keitaro_id;
          campaign = r.campaign;
          if (switched) resetState();
          notRefreshed.clear();
          for (const s of campaign.streams) {
            if (r.skipped_dirty.includes(s.name) && s.is_dirty) notRefreshed.add(s.id);
            else conflicts.delete(s.id);
          }
          const notes = [];
          if (r.offers_marked_removed)
            notes.push(
              alertBox(
                "warn",
                `${plural(r.offers_marked_removed, "offer is", "offers are")} no longer in Keitaro and ${r.offers_marked_removed === 1 ? "was" : "were"} archived. Use <b>Bring back</b> to restore.`
              )
            );
          if (r.deleted_streams.length) notes.push(alertBox("warn", `Deleted in Keitaro: ${r.deleted_streams.map(esc).join(", ")}.`));
          msg.innerHTML = notes.length ? `<div class="notes">${notes.join("")}</div>` : "";
          toast(`Fetched ${plural(r.streams_total, "stream", "streams")} from Keitaro`);
          if (location.pathname !== `/campaigns/${id}`) history.replaceState(null, "", `/campaigns/${id}`);
          render();
          markDraftInPicker();
        } catch (err) {
          msg.innerHTML = `<div class="notes">${alertBox("error", esc(err.message))}</div>`;
          if (!campaign) root.innerHTML = "";
        }
      });
    }

    $("#picker-form").addEventListener("submit", (e) => {
      e.preventDefault();
      if (select.value) doFetch(select.value);
      else select.focus();
    });

    function markDraftInPicker() {
      if (!campaign) return;
      const opt = select.querySelector(`option[value="${campaign.keitaro_id}"]`);
      if (!opt) return;
      const base = opt.textContent.replace(/ • draft$/, "");
      opt.textContent = campaign.streams.some((s) => s.is_dirty) ? `${base} • draft` : base;
    }

    // ----- rendering -----
    const currentStream = (id) => campaign.streams.find((s) => s.id === id);

    function headHtml() {
      const c = campaign;
      const dirty = c.streams.filter((s) => s.is_dirty).length;
      const synced = c.synced_at ? new Date(c.synced_at).toLocaleString() : "never";
      return `
        <div>
          <h1>${esc(c.name)}</h1>
          <div class="meta"><span>Keitaro #${Number(c.keitaro_id)}</span><span>Fetched ${esc(synced)}</span>
            <span>${plural(c.streams.length, "stream", "streams")}${dirty ? ` · <b class="draft-count">${dirty} unpublished</b>` : ""}</span></div>
        </div>
        <a class="btn btn-sm" href="${esc(c.keitaro_url)}" target="_blank" rel="noopener">Open in Keitaro ↗</a>`;
    }

    function render() {
      if (!campaign) return;
      root.innerHTML = `
        <div class="campaign-head" id="campaign-head">${headHtml()}</div>
        <div class="legend-line" aria-hidden="true">
          <span><i class="lg-clean"></i>Published</span>
          <span><i class="lg-dirty"></i>Unpublished changes</span>
          <span><i class="lg-removed"></i>Removed offer</span>
          <span>${ICON_LOCK} Pinned weight stays fixed</span>
        </div>
        <div class="streams" id="streams"></div>`;
      const list = $("#streams");
      if (!campaign.streams.length) {
        list.innerHTML = `<div class="empty-state"><h2>No streams</h2>This campaign has no streams in Keitaro.</div>`;
        return;
      }
      for (const s of campaign.streams) list.appendChild(buildCard(s));
    }

    function renderHead() {
      const h = $("#campaign-head");
      if (h) h.innerHTML = headHtml();
      markDraftInPicker();
    }

    function renderCard(sid, focusSel) {
      const old = root.querySelector(`[data-stream="${sid}"]`);
      const s = currentStream(sid);
      if (!old || !s) return;
      const keepQuery = old.querySelector(".ac input")?.value || "";
      const fresh = buildCard(s);
      old.replaceWith(fresh);
      const search = fresh.querySelector(".ac input");
      if (search && focusSel !== "[data-add-input]" && keepQuery && !keepQuery.startsWith("#")) search.value = keepQuery;
      if (focusSel) {
        const target = focusSel === "[data-add-input]" ? search : fresh.querySelector(focusSel) || search;
        target && target.focus({ preventScroll: true });
      }
    }

    function buildCard(s) {
      const tpl = document.createElement("template");
      tpl.innerHTML = streamHtml(s).trim();
      const card = tpl.content.firstElementChild;
      if (s.has_offers) attachAdd(card, s);
      return card;
    }

    function attachAdd(card, s) {
      const host = card.querySelector("[data-ac]");
      const btn = card.querySelector("[data-add]");
      let picked = null;
      const ac = new OfferAutocomplete(host, {
        placeholder: "Find an offer to add (name or ID)",
        label: `Add offer to stream ${s.name}`,
        exclude: () => new Set(currentStream(s.id).offers.filter((o) => o.status === "active").map((o) => o.offer_id)),
        onPick: (o) => {
          picked = o;
          btn.disabled = false;
          btn.focus();
        },
        onClear: () => {
          picked = null;
          btn.disabled = true;
        },
      });
      btn.addEventListener("click", () => {
        if (!picked) return;
        const o = picked;
        act(btn, s.id, "POST", `/api/streams/${s.id}/offers`, { offer_id: o.id }, {
          ok: `Added #${o.id}. Push to publish.`,
          focus: "[data-add-input]",
        });
      });
    }

    function streamHtml(s) {
      if (!s.has_offers) {
        return `
          <article class="stream plain" data-stream="${s.id}">
            <div class="stream-head">
              <div class="title"><span class="pos">#${Number(s.position)}</span><h2>${esc(s.name)}</h2></div>
              <span class="kind mono">stream ${Number(s.keitaro_id)} · no offers</span>
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

      const pinned = active.filter((o) => o.pinned);
      const free = active.length - pinned.length;
      const pinSum = pinned.reduce((a, o) => a + o.share, 0);
      const pinNote = pinned.length
        ? `<p class="pin-note">${ICON_LOCK}<span>Pinned ${pinSum}% stays fixed · ${
            free ? `remaining ${100 - pinSum}% is split evenly across ${plural(free, "offer", "offers")}` : "every active offer is pinned"
          }</span></p>`
        : "";

      const summary = s.is_dirty ? draftSummary(s) : null;
      let actions;
      if (s.is_dirty && confirmCancel.has(s.id)) {
        actions = `
          <span class="confirm-text">Discard ${plural(summary.count, "change", "changes")}?</span>
          <button class="btn btn-sm btn-danger" data-cancel-yes="${s.id}">Discard</button>
          <button class="btn btn-sm" data-cancel-no="${s.id}">Keep editing</button>`;
      } else {
        actions = `
          ${s.is_dirty ? `<button class="btn btn-ghost btn-sm" data-cancel="${s.id}">Cancel</button>` : ""}
          <button class="btn btn-push btn-sm" data-push="${s.id}" ${!s.is_dirty || s.problem ? "disabled" : ""}
            title="${s.is_dirty ? (s.problem ? esc(s.problem) : "Send offers and weights to Keitaro") : "Nothing to publish"}">Push</button>`;
      }

      const conflict = conflicts.has(s.id)
        ? alertBox("error", esc(conflicts.get(s.id)), `<button class="btn btn-sm" data-force="${s.id}">Push anyway</button>`)
        : "";
      const stale = notRefreshed.has(s.id)
        ? alertBox("warn", "<b>Not refreshed from Keitaro:</b> this stream has unpublished changes. Push or Cancel them, then press Fetch streams again.")
        : "";

      return `
        <article class="stream ${s.is_dirty ? "dirty" : ""}" data-stream="${s.id}" aria-label="Stream ${esc(s.name)}">
          <div class="stream-head">
            <div class="title">
              <span class="pos">#${Number(s.position)}</span>
              <h2>${esc(s.name)}</h2>
              <span class="state ${s.is_dirty ? "state-dirty" : "state-clean"}">${s.is_dirty ? "Unpublished changes" : "Published"}</span>
              ${summary ? `<span class="draft-summary">${esc(summary.text)}</span>` : ""}
            </div>
            <div class="stream-actions">${actions}</div>
          </div>
          <div class="stream-body">
            <div class="sharebar" role="img" aria-label="Traffic split: ${esc(active.map((o) => `offer ${o.offer_id} ${o.share}%`).join(", ") || "no active offers")}">${bar}</div>
            ${pinNote}
            ${s.problem && (s.is_dirty || active.length === 0) ? alertBox("warn", esc(s.problem)) : ""}
            ${stale}
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
      const label = `${o.name} (#${o.offer_id})`;
      const was =
        s.is_dirty && o.changed && !o.added_in_draft && o.published_share !== o.share
          ? `<span class="was" title="Weight in Keitaro now">${o.published_share}%</span>`
          : "";
      const weight = removed
        ? `<span class="val">0%</span>${was}`
        : o.pinned
          ? `<input type="number" inputmode="numeric" min="0" max="100" step="1" value="${o.share}" data-pinval="${o.id}" data-old="${o.share}" aria-label="Pinned weight of ${esc(label)}"><span class="pct">%</span>${was}`
          : `<span class="val">${o.share}%</span>${was}`;
      const pin = removed
        ? `<button class="pin-btn" disabled title="Removed offers cannot be pinned">${ICON_UNLOCK}<span>Pin</span></button>`
        : `<button class="pin-btn" data-pin="${o.id}" aria-pressed="${o.pinned}" title="${o.pinned ? "Unpin: let this weight be recalculated" : "Pin: keep this weight fixed when others change"}" aria-label="${o.pinned ? "Unpin" : "Pin"} weight of ${esc(label)}">${o.pinned ? ICON_LOCK : ICON_UNLOCK}<span>${o.pinned ? "Pinned" : "Pin"}</span></button>`;
      const action = removed
        ? `<button class="btn btn-sm" data-restore="${o.id}" aria-label="Bring back ${esc(label)}">Bring back</button>`
        : `<button class="btn btn-ghost btn-sm btn-danger-text" data-remove="${o.id}" aria-label="Remove ${esc(label)}">Remove</button>`;
      const removedTag = removed
        ? o.published_status === "active"
          ? '<span class="status-removed pending">removed on Push</span>'
          : '<span class="status-removed">archived</span>'
        : "";
      return `
        <tr class="${removed ? "removed" : ""}" data-link="${o.id}">
          <td class="c-sw"><span class="sw" style="background:${color}"></span></td>
          <td class="c-name"><span class="oname">${esc(o.name)}</span>${o.added_in_draft && !removed ? '<span class="tag-new">new</span>' : ""}${removedTag}<span class="m-id mono">#${Number(o.offer_id)}</span></td>
          <td class="c-id mono">${Number(o.offer_id)}</td>
          <td class="c-w"><div class="weight">${pin}${weight}</div></td>
          <td class="c-act">${action}</td>
        </tr>`;
    }

    // ----- actions -----
    function replaceStream(updated) {
      const i = campaign.streams.findIndex((s) => s.id === updated.id);
      if (i >= 0) campaign.streams[i] = updated;
    }

    function act(btn, sid, method, url, body, { ok, focus, onError } = {}) {
      const run = () =>
        busy(btn, async () => {
          const card = root.querySelector(`[data-stream="${sid}"]`);
          card && card.setAttribute("aria-busy", "true");
          try {
            const updated = await api(method, url, body);
            replaceStream(updated);
            conflicts.delete(sid);
            if (!updated.is_dirty) notRefreshed.delete(sid);
            confirmCancel.delete(sid);
            if (ok) toast(ok);
            renderCard(sid, focus);
            renderHead();
          } catch (err) {
            if (err.status === 409 && /changed in Keitaro|deleted in Keitaro/.test(err.message)) {
              conflicts.set(sid, err.message);
              renderCard(sid, "[data-force]");
            } else {
              toast(err.message, "error");
              if (onError) onError();
            }
          } finally {
            const c = root.querySelector(`[data-stream="${sid}"]`);
            c && c.removeAttribute("aria-busy");
          }
        });
      // one request at a time per stream, so quick clicks never race each other
      const next = (queues.get(sid) || Promise.resolve()).then(run, run);
      queues.set(sid, next);
      return next;
    }

    root.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      const card = b.closest("[data-stream]");
      if (!card) return;
      const sid = Number(card.dataset.stream);
      const d = b.dataset;
      if (d.push) act(b, sid, "POST", `/api/streams/${sid}/push`, {}, { ok: "Pushed to Keitaro", focus: "[data-push]" });
      else if (d.force) act(b, sid, "POST", `/api/streams/${sid}/push`, { force: true }, { ok: "Pushed to Keitaro (Keitaro version overwritten)", focus: "[data-push]" });
      else if (d.cancel) {
        confirmCancel.add(sid);
        renderCard(sid, "[data-cancel-no]");
      } else if (d.cancelNo) {
        confirmCancel.delete(sid);
        renderCard(sid, "[data-cancel]");
      } else if (d.cancelYes) act(b, sid, "POST", `/api/streams/${sid}/cancel`, undefined, { ok: "Draft discarded. The stream matches Keitaro again.", focus: "[data-push]" });
      else if (d.remove) act(b, sid, "POST", `/api/streams/${sid}/offers/${d.remove}/remove`, undefined, { focus: `[data-restore="${d.remove}"]` });
      else if (d.restore) act(b, sid, "POST", `/api/streams/${sid}/offers/${d.restore}/restore`, undefined, { focus: `[data-remove="${d.restore}"]` });
      else if (d.pin) {
        const on = b.getAttribute("aria-pressed") !== "true";
        act(b, sid, "PUT", `/api/streams/${sid}/offers/${d.pin}/pin`, { pinned: on }, {
          focus: on ? `[data-pinval="${d.pin}"]` : `[data-pin="${d.pin}"]`,
        });
      }
    });

    // editing a pinned value: commit on change (blur / Enter); invalid input is put back
    root.addEventListener("change", (e) => {
      const inp = e.target.closest("input[data-pinval]");
      if (!inp) return;
      const sid = Number(inp.closest("[data-stream]").dataset.stream);
      const raw = inp.value.trim();
      const v = Number(raw);
      if (raw === "" || !Number.isInteger(v) || v < 0 || v > 100) {
        toast("A pinned weight must be a whole number from 0 to 100.", "error");
        inp.value = inp.dataset.old;
        return;
      }
      if (String(v) === inp.dataset.old) return;
      act(null, sid, "PUT", `/api/streams/${sid}/offers/${inp.dataset.pinval}/pin`, { pinned: true, share: v }, {
        onError: () => renderCard(sid),
      });
    });
    root.addEventListener("keydown", (e) => {
      if (e.target.matches("input[data-pinval]")) {
        if (e.key === "Enter") e.target.blur();
        if (e.key === "Escape") {
          e.target.value = e.target.dataset.old;
          e.target.blur();
        }
      }
    });

    loadList();
    if (initialId) loadLocal(initialId);
    else
      root.innerHTML = `<div class="empty-state"><h2>Pick a campaign</h2>Choose a campaign above to see its streams. Press <b>Fetch streams</b> to load the latest state from Keitaro.</div>`;
  }

  window.KW = { initCreatePage, initEditorPage };
})();
