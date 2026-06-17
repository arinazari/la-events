/* Entry module: load the feed, wire the tab shell, lazy-mount the three views.
 * Explore (filter the catalog) · Plan (the chatbox concierge) · Settings (tune taste). */

import { App, $, $$, el, on, loadFeed } from "./data.js";
import { mountExplore } from "./explore.js";
import { mountChat } from "./chat.js";
import { mountSettings } from "./settings.js";

const VIEWS = {
  explore: { mount: mountExplore, root: "#view-explore", mounted: false },
  plan: { mount: mountChat, root: "#view-plan", mounted: false },
  settings: { mount: mountSettings, root: "#view-settings", mounted: false },
};

function showView(name) {
  const v = VIEWS[name];
  if (!v) return;
  if (!v.mounted) { v.mount($(v.root)); v.mounted = true; }
  $$(".view").forEach((el) => el.classList.toggle("active", el.id === `view-${name}`));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  if (name !== "explore") window.scrollTo({ top: 0 });
}

async function init() {
  try {
    await loadFeed();
  } catch (e) {
    $("#view-explore").append(el("div", { className: "empty" },
      el("h2", { textContent: "Couldn't load event data" }),
      el("p", {}, "Generate the feed first: ", el("code", { textContent: "python scripts/build_dashboard.py" })),
      el("p", { className: "desc", textContent: `(${e.message})` })));
    return;
  }

  const f = App.feed;
  $("#generated").textContent = `${f.count} events · updated ${(f.generated_at || "").replace("T", " ")}`;
  if (f.is_sample) $("#meta").append(el("span", { className: "sample-badge", textContent: "SAMPLE DATA" }));

  $$("#tabs .tab").forEach((t) => (t.onclick = () => showView(t.dataset.view)));
  on("nav:explore", () => showView("explore"));

  showView("explore");
}

init();
