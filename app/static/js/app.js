/**
 * RackWatch front-end: live WS, i18n, dark/light theme, in-place updates.
 */
(function () {
  "use strict";

  const FILTER_KEYS = ["host", "service", "severity", "status", "time_range"];
  const STORAGE = "rackwatch.filters";
  const RW = window.RW || { lang: "en", theme: "dark", i18n: {} };

  function $(id) {
    return document.getElementById(id);
  }

  function t(key, vars) {
    let text = (RW.i18n && RW.i18n[key]) || key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        text = text.replaceAll("{" + k + "}", String(vars[k]));
      });
    }
    return text;
  }

  function statusLabel(code) {
    const key = "status." + (code === "critical" ? "critical" : code || "unknown");
    return t(key);
  }

  function live(state, labelKey) {
    const el = $("live-indicator");
    if (!el) return;
    el.dataset.state = state;
    const text = el.querySelector(".rw-live-label");
    if (text) text.textContent = t(labelKey);
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtPct(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(digits ?? 0) + "%";
  }

  function pill(status, label) {
    const cls = status === "critical" ? "error" : status || "unknown";
    return `<span class="rw-pill is-${esc(cls)}">${esc(label || statusLabel(cls))}</span>`;
  }

  function setHtml(el, html) {
    if (!el) return false;
    if (el.dataset.sig === html) return false;
    el.dataset.sig = html;
    el.innerHTML = html;
    return true;
  }

  function readFilters() {
    const data = {};
    FILTER_KEYS.forEach((key) => {
      const el = $("filter-" + (key === "time_range" ? "range" : key));
      data[key] = el ? el.value : "";
    });
    return data;
  }

  function writeFilters(data) {
    FILTER_KEYS.forEach((key) => {
      const el = $("filter-" + (key === "time_range" ? "range" : key));
      if (el && data[key] !== undefined) el.value = data[key];
    });
  }

  function persistFilters(data) {
    try {
      sessionStorage.setItem(STORAGE, JSON.stringify(data));
    } catch (_) {
      /* private mode */
    }
  }

  function restoreFilters() {
    try {
      const raw = sessionStorage.getItem(STORAGE);
      if (raw) writeFilters(JSON.parse(raw));
    } catch (_) {
      /* ignore */
    }
  }

  function meter(pct) {
    const n = Math.max(0, Math.min(100, Number(pct) || 0));
    return `<div class="rw-meter" aria-hidden="true"><span style="width:${n}%"></span></div>`;
  }

  function renderMetrics(hosts) {
    const root = $("metric-cards");
    if (!root) return;
    if (!hosts || !hosts.length) {
      setHtml(
        root,
        `<div class="rw-empty"><strong>${esc(t("empty.hosts_title"))}</strong><p>${esc(t("empty.hosts_body"))}</p></div>`
      );
      return;
    }
    const html = hosts
      .map((h) => {
        const src = t("metric.source", { source: h.source || "" });
        const load = h.load1 != null ? " · " + t("metric.load", { load: h.load1 }) : "";
        return `<article class="rw-gauge is-${esc(h.status)}" data-host="${esc(h.name)}">
        <header>${pill(h.status, statusLabel(h.status))}<h3>${esc(h.name)}</h3></header>
        <dl>
          <div><dt>${esc(t("metric.cpu"))}</dt><dd class="mono" data-k="cpu">${fmtPct(h.cpu_percent)}</dd>${meter(h.cpu_percent)}</div>
          <div><dt>${esc(t("metric.ram"))}</dt><dd class="mono" data-k="ram">${fmtPct(h.ram_percent)}</dd>${meter(h.ram_percent)}</div>
          <div><dt>${esc(t("metric.disk"))}</dt><dd class="mono" data-k="disk">${fmtPct(h.disk_percent)}</dd>${meter(h.disk_percent)}</div>
        </dl>
        <p class="rw-muted">${esc(src)}${esc(load)}</p>
      </article>`;
      })
      .join("");
    setHtml(root, html);
  }

  function renderContainers(rows) {
    const root = $("container-table");
    const count = $("container-count");
    if (count) {
      const down = (rows || []).filter((c) => c.severity === "error").length;
      count.textContent = rows && rows.length ? t("count.containers", { total: rows.length, down }) : "";
    }
    if (!root) return;
    if (!rows || !rows.length) {
      setHtml(
        root,
        `<div class="rw-empty"><strong>${esc(t("empty.containers_title"))}</strong><p>${esc(t("empty.containers_body"))}</p></div>`
      );
      return;
    }
    const body = rows
      .map((c) => {
        const label = c.health ? `${c.status} · ${c.health}` : c.status;
        return `<tr class="is-${esc(c.severity)}" data-name="${esc(c.name)}">
          <td>${pill(c.severity, label)}</td>
          <td class="mono">${esc(c.name)}</td>
          <td class="rw-ellipsis" title="${esc(c.image)}">${esc(c.image)}</td>
          <td class="mono">${fmtPct(c.cpu_percent, 1)}</td>
          <td class="mono">${c.memory_percent != null ? fmtPct(c.memory_percent, 0) : "—"}</td>
          <td>
          <button class="outline secondary rw-tiny" type="button" data-restart="${esc(c.name)}">
            ${esc(t("action.restart"))}
          </button>
          <button class="outline secondary rw-tiny" type="button" data-container-logs="${esc(c.name)}">${esc(t("action.logs"))}</button>
          <button class="outline secondary rw-tiny" type="button" data-container-inspect="${esc(c.name)}">${esc(t("action.inspect"))}</button>
          </td>
        </tr>`;
      })
      .join("");
    const html = `<div class="rw-table-wrap"><table class="rw-table">
      <thead><tr>
        <th>${esc(t("table.status"))}</th><th>${esc(t("table.name"))}</th>
        <th>${esc(t("table.image"))}</th><th>${esc(t("table.cpu"))}</th>
        <th>${esc(t("table.ram"))}</th>
        <th><span class="visually-hidden">${esc(t("table.actions"))}</span></th>
      </tr></thead>
      <tbody>${body}</tbody></table></div>`;
    setHtml(root, html);
  }

  function renderZfs(pools) {
    const root = $("zfs-list");
    if (!root) return;
    if (!pools || !pools.length) {
      setHtml(root, `<div class="rw-empty rw-empty-tight"><p>${esc(t("empty.zfs"))}</p></div>`);
      return;
    }
    const html =
      '<ul class="rw-plain">' +
      pools
        .map((z) => {
          const used =
            z.capacity_percent != null
              ? t("count.used", { pct: fmtPct(z.capacity_percent) })
              : z.source || "";
          return `<li class="rw-row">${pill(z.status, z.health)}
          <strong>${esc(z.name)}</strong>
          <span class="mono rw-muted">${esc(used)}</span>
        </li>`;
        })
        .join("") +
      "</ul>";
    setHtml(root, html);
  }

  function renderHa(entities, haOk) {
    const mini = $("ha-mini");
    const grid = $("ha-grid");
    const count = $("ha-count");
    if (count) {
      count.textContent = entities && entities.length ? t("count.entities", { n: entities.length }) : "";
    }

    function empty(msg, cta) {
      return `<div class="rw-empty rw-empty-tight"><p>${esc(msg)}</p>${cta || ""}</div>`;
    }
    const settingsLink = `<a href="/settings">${esc(t("empty.open_settings"))}</a>`;

    if (mini) {
      if (!haOk) setHtml(mini, empty(t("empty.ha_off"), settingsLink));
      else if (!entities.length) setHtml(mini, empty(t("empty.ha_none")));
      else {
        setHtml(
          mini,
          '<ul class="rw-plain rw-ha-mini">' +
            entities
              .slice(0, 8)
              .map(
                (e) => `<li>
              <span class="rw-dot is-${esc(e.status)}" aria-hidden="true"></span>
              <span class="rw-ellipsis">${esc(e.name)}</span>
              <strong class="mono">${esc(e.state)}${e.unit ? " " + esc(e.unit) : ""}</strong>
            </li>`
              )
              .join("") +
            "</ul>"
        );
      }
    }

    if (grid) {
      if (!haOk) {
        setHtml(grid, empty(t("empty.ha_off_full"), settingsLink));
        return;
      }
      if (!entities.length) {
        setHtml(grid, empty(t("empty.ha_none_full")));
        return;
      }
      setHtml(
        grid,
        '<div class="rw-ha-grid">' +
          entities
            .map(
              (e) => `<article class="rw-ha-card is-${esc(e.status)}">
            <div class="eid">${esc(e.entity_id)}</div>
            <strong>${esc(e.name)}</strong>
            <div class="state mono">${esc(e.state)}${e.unit ? " " + esc(e.unit) : ""}</div>
          </article>`
            )
            .join("") +
          "</div>"
      );
    }
  }

  function renderAlerts(alerts) {
    const root = $("alert-mini");
    if (!root) return;
    if (!alerts || !alerts.length) {
      setHtml(root, `<div class="rw-empty rw-empty-tight"><p>${esc(t("empty.alerts"))}</p></div>`);
      return;
    }
    const html =
      '<ul class="rw-plain">' +
      alerts
        .slice(0, 8)
        .map((a) => {
          const sev = a.severity === "critical" ? "error" : a.severity;
          return `<li class="rw-alert is-${esc(a.severity)}">${pill(sev, statusLabel(a.severity))}
            <div><strong>${esc(a.title)}</strong>
            <p class="rw-muted">${esc(a.host)} · ${esc(a.service)}</p></div></li>`;
        })
        .join("") +
      "</ul>";
    setHtml(root, html);
  }

  function renderGlances(data) {
    const root = $("glances-panel");
    const status = $("glances-status");
    if (!root) return;
    if (!data || !Object.keys(data).length) {
      if (status) status.textContent = "offline / no configurado";
      return;
    }
    if (status) status.textContent = "conectado";
    const q = data.quicklook || {};
    const m = data.memswap || {};
    const net = Array.isArray(data.network) ? data.network.slice(0, 6) : [];
    const procs = Array.isArray(data.processes) ? data.processes.slice(0, 6) : [];
    const pct = (v) => v == null ? "—" : `${Number(v).toFixed(1)}%`;
    root.className = "rw-output";
    root.innerHTML = `<div class="rw-glances-grid">
      <span>CPU <b>${pct(q.cpu)}</b></span><span>RAM <b>${pct(q.mem)}</b></span>
      <span>SWAP <b>${pct(m.percent)}</b></span><span>Load <b>${q.load || "—"}</b></span>
    </div><details><summary>Procesos y red</summary>
      <pre>${esc(procs.map(p => `${p.name || p.cmdline || "?"}: CPU ${pct(p.cpu_percent)} RAM ${pct(p.memory_percent)}`).join("\n") || "Sin procesos")}
${esc(net.map(n => `${n.interface_name || n.key || "?"}: ↓ ${n.bytes_recv_rate_per_sec || 0}/s ↑ ${n.bytes_sent_rate_per_sec || 0}/s`).join("\n") || "Sin interfaces")}</pre>
    </details>`;
  }

  function banner(snap) {
    const el = $("backend-banner");
    if (!el) return;
    const bits = [];
    if (!snap.prometheus_ok) bits.push(t("banner.prom"));
    if (!snap.docker_ok) bits.push(t("banner.docker"));
    if (document.body.dataset.nav === "ha" && !snap.ha_ok) bits.push(t("banner.ha"));
    if (!bits.length) {
      el.classList.add("is-hidden");
      el.textContent = "";
      return;
    }
    el.classList.remove("is-hidden");
    el.textContent = bits.join(" ");
  }

  function applySnapshot(snap) {
    if (!snap || snap.type === "pong" || snap.type === "chat") return;
    renderMetrics(snap.hosts || []);
    renderContainers(snap.containers || []);
    renderZfs(snap.zfs || []);
    renderHa(snap.ha_entities || [], !!snap.ha_ok);
    renderAlerts(snap.alerts || []);
    renderGlances(snap.glances || {});
    banner(snap);
    const n = (snap.alerts || []).length;
    document.querySelectorAll('a[href="/alerts"]').forEach((a) => {
      a.classList.toggle("has-unread", n > 0);
      if (n > 0) a.setAttribute("data-unread", String(n));
      else a.removeAttribute("data-unread");
    });
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws`);
    let pingTimer = null;

    socket.addEventListener("open", () => {
      live("live", "live.live");
      socket.send(JSON.stringify({ type: "filter", ...readFilters() }));
      pingTimer = setInterval(() => {
        if (socket.readyState === 1) socket.send(JSON.stringify({ type: "ping" }));
      }, 15000);
    });

    socket.addEventListener("message", (ev) => {
      try {
        applySnapshot(JSON.parse(ev.data));
      } catch (_) {
        /* ignore malformed */
      }
    });

    socket.addEventListener("close", () => {
      live("offline", "live.reconnecting");
      if (pingTimer) clearInterval(pingTimer);
      setTimeout(connect, 2000);
    });

    socket.addEventListener("error", () => socket.close());

    window.__rwSocket = socket;
  }

  function bindFilters() {
    const form = $("filter-form");
    if (!form) return;
    restoreFilters();
    const send = () => {
      const data = readFilters();
      persistFilters(data);
      const socket = window.__rwSocket;
      if (socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: "filter", ...data }));
      }
    };
    form.addEventListener("input", send);
    form.addEventListener("change", send);
    const reset = $("filter-reset");
    if (reset) {
      reset.addEventListener("click", () => {
        writeFilters({ host: "", service: "", severity: "", status: "", time_range: "1h" });
        send();
      });
    }
  }

  function bindToasts() {
    document.body.addEventListener("htmx:afterSwap", (ev) => {
      if (ev.detail.target && ev.detail.target.id === "toast-root") {
        setTimeout(() => {
          ev.detail.target.innerHTML = "";
        }, 6000);
      }
    });
  }

  function showToast(ok, title, body) {
    const root = $("toast-root");
    if (!root) return;
    root.innerHTML = `<div class="rw-toast ${ok ? "is-ok" : "is-error"}" role="status">
      <strong>${esc(title)}</strong>
      <p>${esc(body || "")}</p>
    </div>`;
    setTimeout(() => {
      root.innerHTML = "";
    }, 6000);
  }

  function bindTestAlerts() {
    document.querySelectorAll("[data-test-channel]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const body = new URLSearchParams();
          body.set("channel", btn.getAttribute("data-test-channel") || "all");
          const res = await fetch("/alerts/test", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body,
          });
          if (res.ok) {
            const root = $("toast-root");
            if (root) {
              root.innerHTML = await res.text();
              setTimeout(() => {
                root.innerHTML = "";
              }, 6000);
            }
          } else {
            showToast(false, t("toast.test_fail"), String(res.status));
          }
        } catch (err) {
          console.error(err);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  function applyTheme(theme) {
    const html = document.documentElement;
    html.setAttribute("data-theme", theme);
    html.style.colorScheme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f3f1fb" : "#07070f");
    const scheme = document.querySelector('meta[name="color-scheme"]');
    if (scheme) scheme.setAttribute("content", theme);
    const btn = $("theme-toggle");
    if (btn) btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    RW.theme = theme;
  }

  function bindTheme() {
    const btn = $("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      const next = (RW.theme || "dark") === "dark" ? "light" : "dark";
      applyTheme(next);
      try {
        await fetch("/prefs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme: next }),
        });
      } catch (_) {
        /* cookie will catch up on next nav */
      }
    });
  }

  function bindParallax() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const root = document.body;
    const set = (x, y, sy) => {
      root.style.setProperty("--rw-px", x.toFixed(2) + "px");
      root.style.setProperty("--rw-py", y.toFixed(2) + "px");
      if (sy !== undefined) root.style.setProperty("--rw-sy", sy.toFixed(2) + "px");
    };
    window.addEventListener(
      "pointermove",
      (ev) => {
        const nx = (ev.clientX / Math.max(window.innerWidth, 1) - 0.5) * 28;
        const ny = (ev.clientY / Math.max(window.innerHeight, 1) - 0.5) * 18;
        set(nx, ny);
      },
      { passive: true }
    );
    window.addEventListener(
      "scroll",
      () => root.style.setProperty("--rw-sy", (window.scrollY * 0.12).toFixed(2) + "px"),
      { passive: true }
    );
  }

  function bindChatTest() {
    const btn = $("test-n8n-chat");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/v1/chat/test", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
          showToast(true, t("chat.test_ok"), data.preview || "");
        } else {
          showToast(false, t("chat.test_fail"), data.detail || data.preview || String(res.status));
        }
      } catch (err) {
        showToast(false, t("chat.test_fail"), String(err));
      } finally {
        btn.disabled = false;
      }
    });
  }

  function bindRestart() {
    const modal = $("confirm-root");
    const title = $("confirm-title");
    const body = $("confirm-body");
    const okBtn = $("confirm-ok");
    const cancelBtn = $("confirm-cancel");
    let pending = null;

    function close() {
      if (modal) modal.hidden = true;
      pending = null;
    }

    document.body.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-restart]");
      if (!btn) return;
      ev.preventDefault();
      pending = btn.getAttribute("data-restart");
      if (!modal || !title) return;
      title.textContent = t("action.restart_confirm", { name: pending });
      if (body) body.textContent = "";
      modal.hidden = false;
      if (cancelBtn) cancelBtn.focus();
    });

    if (cancelBtn) cancelBtn.addEventListener("click", close);
    if (modal) {
      modal.addEventListener("click", (ev) => {
        if (ev.target === modal) close();
      });
    }
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && modal && !modal.hidden) close();
    });
    if (okBtn) {
      okBtn.addEventListener("click", async () => {
        const name = pending;
        close();
        if (!name) return;
        const row = document.querySelector(`[data-name="${CSS.escape(name)}"]`);
        if (row) row.classList.add("is-warning");
        try {
          const res = await fetch(`/services/${encodeURIComponent(name)}/restart`, { method: "POST" });
          const root = $("toast-root");
          if (root && res.ok) {
            root.innerHTML = await res.text();
            setTimeout(() => {
              root.innerHTML = "";
            }, 6000);
          } else if (!res.ok) {
            showToast(false, t("toast.restart_fail", { name }), String(res.status));
          }
        } catch (err) {
          showToast(false, t("toast.restart_fail", { name }), String(err));
        }
      });
    }
  }

  function bindContainerOperations() {
    const panel = $("container-ops");
    const output = $("container-output");
    const selected = $("ops-container");
    const command = $("container-command");
    const run = $("container-exec");
    if (!panel || !output || !selected) return;
    let container = null;
    async function load(path) {
      try {
        const res = await fetch(`/services/${encodeURIComponent(container)}${path}`);
        const data = await res.json().catch(() => ({}));
        output.textContent = res.ok ? (data.logs || JSON.stringify(data.inspect, null, 2)) : (data.detail || String(res.status));
      } catch (err) { output.textContent = String(err); }
    }
    document.body.addEventListener("click", (ev) => {
      const logs = ev.target.closest("[data-container-logs]");
      const inspect = ev.target.closest("[data-container-inspect]");
      if (!logs && !inspect) return;
      container = (logs || inspect).getAttribute(logs ? "data-container-logs" : "data-container-inspect");
      panel.hidden = false;
      selected.textContent = container;
      output.textContent = "";
      load(logs ? "/logs?lines=160" : "/inspect");
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    if (run) run.addEventListener("click", async () => {
      if (!container || !command.value.trim()) return;
      run.disabled = true;
      try {
        const res = await fetch(`/services/${encodeURIComponent(container)}/exec`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command: command.value.trim() }) });
        const data = await res.json().catch(() => ({}));
        output.textContent = res.ok ? `exit ${data.exit_code}\n${data.output || ""}` : (data.detail || String(res.status));
      } catch (err) { output.textContent = String(err); }
      finally { run.disabled = false; }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    live("connecting", "live.connecting");
    bindFilters();
    bindToasts();
    bindTestAlerts();
    bindTheme();
    bindRestart();
    bindContainerOperations();
    bindParallax();
    bindChatTest();
    connect();
  });
})();
