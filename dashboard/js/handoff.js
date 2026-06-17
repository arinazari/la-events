/* The agent hand-off seam — the ONE place the static page reaches the "brain".
 *
 * Architecture (chosen): static-first + claude.ai/code hand-off. The page composes a
 * precise prompt (a concierge/night-planner request, or a settings change-set) and hands
 * it to a Claude Code session — the agent that already runs this repo — which does the
 * work and commits results back. The daily routine / Pages redeploy then surface them here.
 *
 * UPGRADE PATH (no rewrite): set BACKEND_URL to a small service that holds the Anthropic +
 * GitHub keys. When set, handoffToAgent() POSTs the intent there (streaming chat / auto-
 * commit) instead of opening the copy-and-paste modal. Every caller goes through this one
 * function, so swapping the transport is a localized change.
 */

import { el, $, App } from "./data.js";

// Empty = static hand-off mode. Point this at a backend later to enable in-page execution.
export const BACKEND_URL = "";

// Where the agent lives. Override if you run a project-specific Claude Code URL.
export const CLAUDE_CODE_URL = "https://claude.ai/code";

/* A compact, honest description of repo freshness for the agent prompt. */
export function repoContext() {
  const f = App.feed || {};
  const when = (f.generated_at || "").replace("T", " ");
  return `Repo: arinazari/la-events. Catalog: data/catalog.json (${f.count ?? "?"} events, `
    + `dashboard feed generated ${when}). Use the committed catalog/enrichment; don't re-fetch `
    + `unless asked.`;
}

/* Route a composed request to the agent. Returns true if handled in-page (backend),
 * false if it fell back to the copy-and-paste modal. */
export async function handoffToAgent({ title, prompt, onResult }) {
  if (BACKEND_URL) {
    try {
      const res = await fetch(BACKEND_URL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      onResult?.(data);
      return true;
    } catch (e) {
      // Backend down -> degrade to the static hand-off so the action never dead-ends.
      openHandoffModal({ title, prompt, note: `Backend unreachable (${e.message}) — paste this into a session instead.` });
      return false;
    }
  }
  openHandoffModal({ title, prompt });
  return false;
}

/* ── Copy-and-paste modal (static mode) ──────────────────────────────────── */
export function openHandoffModal({ title, prompt, note }) {
  closeHandoffModal();
  const ta = el("textarea", { className: "handoff-prompt", value: prompt, readOnly: true });

  const copyBtn = el("button", { className: "btn primary", textContent: "Copy prompt" });
  copyBtn.onclick = async () => {
    try { await navigator.clipboard.writeText(prompt); }
    catch { ta.select(); document.execCommand?.("copy"); }
    copyBtn.textContent = "Copied ✓";
    setTimeout(() => (copyBtn.textContent = "Copy prompt"), 1600);
  };
  const openBtn = el("a", {
    className: "btn", href: CLAUDE_CODE_URL, target: "_blank", rel: "noopener",
    textContent: "Open Claude Code ↗",
  });

  const overlay = el("div", { className: "modal-overlay", id: "handoff-modal" },
    el("div", { className: "modal" },
      el("div", { className: "modal-head" },
        el("h3", { textContent: title || "Send to your concierge" }),
        el("button", { className: "modal-x", textContent: "✕", onclick: closeHandoffModal })),
      el("p", { className: "modal-sub", textContent:
        note || "This runs in your Claude Code session (the agent that maintains this repo). "
        + "Copy it, open a session on this repo, and paste — results commit back and show up here "
        + "after the next refresh." }),
      ta,
      el("div", { className: "modal-actions" }, copyBtn, openBtn)));

  overlay.onclick = (e) => { if (e.target === overlay) closeHandoffModal(); };
  document.body.append(overlay);
  // Auto-copy as a convenience; the button is the explicit affordance.
  navigator.clipboard?.writeText(prompt).catch(() => {});
}

export function closeHandoffModal() {
  $("#handoff-modal")?.remove();
}
