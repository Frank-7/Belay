import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../site/index.html", import.meta.url), "utf8");
const script = readFileSync(new URL("../site/assets/site.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../site/assets/site.css", import.meta.url), "utf8");
const strategies = ["belay", "naive", "stable"];

function attributes(source) {
  return Object.fromEntries(
    [...source.matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map(([, name, value]) => [name, value ?? ""]),
  );
}

function loadPage({ protocol = "file:", evidence, fetchFailure = false, clipboard = true } = {}) {
  // A small DOM surface runs the actual page script. Elements and attributes
  // come from the real HTML; this is not a second implementation of recovery.
  const nodes = [...html.matchAll(/<([a-z][\w-]*)\b([^<>]*)>/g)].map(([, tag, attrs]) => element(tag, attributes(attrs)));
  const byId = new Map(nodes.filter((node) => node.attrs.id).map((node) => [node.attrs.id, node]));
  const radios = nodes.filter((node) => node.tag === "input" && node.attrs.name === "scenario");
  const sourceLinks = nodes.filter((node) => node.dataset.source);
  const cards = nodes.filter((node) => node.classes.has("strategy"));
  const dots = [...html.match(/class="step-dots"[^>]*>([\s\S]*?)<\/div>/)[1].matchAll(/<i\b([^>]*)>/g)]
    .map(([, attrs]) => element("i", attributes(attrs)));
  const menu = nodes.find((node) => node.classes.has("menu-toggle"));
  const nav = byId.get("main-nav");
  const navMarkup = html.match(/<nav\b[^>]*id="main-nav"[^>]*>([\s\S]*?)<\/nav>/)[1];
  const navLinks = [...navMarkup.matchAll(/<a\b([^>]*)>/g)].map(([, attrs]) => element("a", attributes(attrs)));
  nav.querySelectorAll = (selector) => {
    assert.equal(selector, "a");
    return navLinks;
  };
  strategies.forEach((strategy, index) => {
    nodes.find((node) => node.dataset.status === strategy).closest = (selector) => {
      assert.equal(selector, ".strategy");
      return cards[index];
    };
  });
  byId.get("setup-command").textContent = html.match(/<code\b[^>]*id="setup-command"[^>]*>([\s\S]*?)<\/code>/)[1];
  const documentListeners = new Map();
  const fetches = [];
  const copied = [];
  const selected = [];

  function element(tag, attrs = {}) {
    return {
      tag, attrs, value: attrs.value, checked: Object.hasOwn(attrs, "checked"),
      href: attrs.href, focused: false, listeners: new Map(), children: [],
      classes: new Set((attrs.class || "").split(/\s+/).filter(Boolean)),
      dataset: Object.fromEntries(Object.entries(attrs).filter(([name]) => name.startsWith("data-"))
        .map(([name, value]) => [name.slice(5), value])),
      get classList() {
        return {
          toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
          remove: (name) => this.classes.delete(name),
        };
      },
      get textContent() { return this.children.map((child) => child.textContent).join(""); },
      set textContent(value) { this.children = [{ textContent: String(value) }]; },
      replaceChildren(...children) { this.children = children; },
      append(child) { this.children.push(child); },
      setAttribute(name, value) { this.attrs[name] = value; },
      getAttribute(name) { return this.attrs[name] ?? null; },
      addEventListener(name, listener) { this.listeners.set(name, listener); },
      fire(name, event = {}) {
        assert.ok(this.listeners.has(name), `${tag} must handle ${name}`);
        return this.listeners.get(name)(event);
      },
      focus() { this.focused = true; },
    };
  }

  const document = {
    getElementById: (id) => byId.get(id),
    createElement: (tag) => element(tag),
    createTextNode: (textContent) => ({ textContent }),
    createRange: () => ({ selectNodeContents: (node) => selected.push(node) }),
    addEventListener: (name, listener) => documentListeners.set(name, listener),
    querySelector(selector) {
      if (selector === ".menu-toggle") return menu;
      const match = selector.match(/^\[data-(total|status|detail)="(\w+)"\]$/);
      assert.ok(match, `Unexpected selector: ${selector}`);
      return nodes.find((node) => node.dataset[match[1]] === match[2]);
    },
    querySelectorAll(selector) {
      if (selector === '.step-dots i') return dots;
      if (selector === 'input[name="scenario"]') return radios;
      if (selector === '[data-source]') return sourceLinks;
      assert.fail(`Unexpected selector: ${selector}`);
    },
  };
  const context = vm.createContext({
    document,
    navigator: clipboard ? { clipboard: { writeText: async (text) => copied.push(text) } } : {},
    window: {
      location: { protocol },
      getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
    },
    fetch(path, options) {
      assert.equal(protocol, "https:", "A file preview must not fetch metadata");
      assert.equal(path, "evidence.json", "The browser simulation must not call an execution API");
      assert.equal(options?.method ?? "GET", "GET", "Only read-only evidence enrichment is permitted");
      assert.equal(options?.body, undefined, "The static page must not submit execution data");
      fetches.push(path);
      return fetchFailure ? Promise.reject(new Error("Synthetic unavailable metadata"))
        : Promise.resolve({ ok: true, json: async () => evidence || {} });
    },
  });
  vm.runInContext(script, context, { filename: "site/assets/site.js" });
  return {
    element: (id) => byId.get(id), nodes, radios, cards, dots, menu, nav, navLinks,
    fetches, copied, selected, sourceLinks,
    next: () => byId.get("demo-next").fire("click"),
    reset: () => byId.get("demo-reset").fire("click"),
    key: (key) => documentListeners.get("keydown")({ key }),
    choose(value) {
      const target = radios.find((radio) => radio.value === value);
      assert.ok(target, `Missing scenario control: ${value}`);
      radios.forEach((radio) => { radio.checked = radio === target; });
      target.fire("change");
    },
    totals: () => strategies.map((name) => document.querySelector(`[data-total="${name}"]`).textContent),
    statuses: () => strategies.map((name) => document.querySelector(`[data-status="${name}"]`).textContent),
    details: () => strategies.map((name) => document.querySelector(`[data-detail="${name}"]`).textContent),
  };
}

test("lost receipt compares recovery with a fair stable-key baseline", () => {
  const page = loadPage();
  assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
  assert.deepEqual(page.statuses(), ["Ready", "Ready", "Ready"]);
  page.next();
  assert.deepEqual(page.totals(), ["$50", "$50", "$50"]);
  assert.deepEqual(page.statuses(), ["Receipt missing", "Receipt missing", "Receipt missing"]);
  page.next();
  assert.deepEqual(page.totals(), ["$50", "$80", "$50"]);
  assert.deepEqual(page.statuses(), ["Reconciled", "Second refund", "Deduplicated"]);
  assert.match(page.details()[2], /same key.*original \$50 receipt/i);
  assert.deepEqual(page.fetches, []);
});

test("all three strategies refuse a new payment after revocation", () => {
  const page = loadPage();
  page.choose("revoked");
  page.next();
  assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
  page.next();
  assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
  assert.deepEqual(page.statuses(), ["Refused", "Refused", "Refused"]);
  assert.match(page.element("demo-explanation").textContent, /All three strategies.*current permission/i);
});

test("opaque provider totals remain observer knowledge rather than verified recovery", () => {
  const page = loadPage();
  page.choose("opaque");
  page.next();
  page.next();
  assert.deepEqual(page.totals(), ["$50", "$80", "$50"]);
  assert.match(page.statuses()[0], /Unknown.*halted/);
  assert.match(page.statuses()[2], /Unknown.*halted/);
  assert.match(page.element("demo-evidence").textContent, /teaching only.*cannot use.*oracle/i);
  assert.match(page.details()[2], /does not honor/i);
});

test("changing scenarios and resetting remove every prior outcome", () => {
  const page = loadPage();
  page.next();
  page.next();
  for (const scenario of ["opaque", "revoked", "lost"]) {
    page.choose(scenario);
    assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
    assert.deepEqual(page.statuses(), ["Ready", "Ready", "Ready"]);
    assert.match(page.element("step-label").textContent, /STEP 01/);
    assert.deepEqual(page.dots.map((dot) => dot.classes.has("active")), [true, false, false]);
    page.next();
    page.next();
  }
  page.reset();
  assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
  assert.deepEqual(page.statuses(), ["Ready", "Ready", "Ready"]);
});

test("replaying the walkthrough cannot accumulate additional synthetic payments", () => {
  const page = loadPage();
  for (let replay = 0; replay < 5; replay += 1) {
    page.next();
    page.next();
    assert.deepEqual(page.totals(), ["$50", "$80", "$50"]);
    page.next();
    assert.deepEqual(page.totals(), ["$0", "$0", "$0"]);
  }
});

test("unchecked or unknown scenario changes cannot corrupt the active state", () => {
  const page = loadPage();
  page.next();
  const headline = page.element("demo-headline").textContent;
  const radio = page.radios[1];
  radio.checked = false;
  radio.fire("change");
  radio.checked = true;
  radio.value = "constructor";
  radio.fire("change");
  assert.equal(page.element("demo-headline").textContent, headline);
  page.next();
  assert.deepEqual(page.totals(), ["$50", "$80", "$50"]);
});

test("step announcements communicate unknown outcomes and comparison totals", () => {
  const page = loadPage();
  const announcement = page.element("demo-announcement");
  assert.equal(announcement.textContent, "", "Initial rendering should not interrupt page reading");
  page.choose("opaque");
  page.next();
  assert.match(announcement.textContent, /^Step 2 of 3\./);
  page.next();
  assert.match(announcement.textContent, /With Belay: Unknown.*observer total \$50/);
  assert.match(announcement.textContent, /Fresh-key retry: observer total \$80/);
  assert.match(announcement.textContent, /Stable provider key: Unknown/);
  assert.equal(announcement.attrs["aria-live"], "polite");
  assert.equal(announcement.attrs["aria-atomic"], "true");
});

test("mobile navigation keeps expanded state and Escape focus in sync", () => {
  const page = loadPage();
  page.menu.fire("click");
  assert.equal(page.menu.attrs["aria-expanded"], "true");
  assert.equal(page.nav.classes.has("is-open"), true);
  page.key("Escape");
  assert.equal(page.menu.attrs["aria-expanded"], "false");
  assert.equal(page.nav.classes.has("is-open"), false);
  assert.equal(page.menu.focused, true);
  page.menu.fire("click");
  page.navLinks[0].fire("click");
  assert.equal(page.menu.attrs["aria-expanded"], "false");
  assert.equal(page.nav.classes.has("is-open"), false);
});

test("copy commands supports both Clipboard API and keyboard-copy fallback", async () => {
  const page = loadPage();
  await page.element("copy-command").fire("click");
  assert.deepEqual(page.copied, [page.element("setup-command").textContent.trim()]);
  assert.match(page.element("copy-status").textContent, /copied/i);
  const fallback = loadPage({ clipboard: false });
  await fallback.element("copy-command").fire("click");
  assert.deepEqual(fallback.selected, [fallback.element("setup-command")]);
  assert.match(fallback.element("copy-status").textContent, /selected.*copy command/i);
});

test("evidence enrichment accepts repository source links without execution requests", async () => {
  const pinned = "https://github.com/Frank-7/Belay/blob/0123456/results/matrix.json";
  const page = loadPage({ protocol: "https:", evidence: { sources: {
    matrix: { url: pinned }, findings: "javascript:alert(1)",
    adjudication: "https://example.invalid/unsupported",
  } } });
  const original = page.sourceLinks.map((link) => link.href);
  await setImmediate();
  assert.equal(page.sourceLinks.find((link) => link.dataset.source === "matrix").href, pinned);
  page.sourceLinks.forEach((link, index) => {
    if (link.dataset.source !== "matrix") assert.equal(link.href, original[index]);
  });
  page.next();
  page.next();
  assert.deepEqual(page.fetches, ["evidence.json"]);
});

test("unavailable metadata leaves the demonstration and source links usable", async () => {
  const page = loadPage({ protocol: "https:", fetchFailure: true });
  const original = page.sourceLinks.map((link) => link.href);
  await setImmediate();
  assert.deepEqual(page.sourceLinks.map((link) => link.href), original);
  page.next();
  page.next();
  assert.deepEqual(page.totals(), ["$50", "$80", "$50"]);
});

test("markup provides native keyboard controls and reduced-motion hooks", () => {
  const page = loadPage();
  for (const id of ["demo-next", "demo-reset", "copy-command"]) {
    assert.equal(page.element(id).tag, "button");
    assert.equal(page.element(id).attrs.type, "button");
  }
  assert.equal(page.radios.length, 3);
  assert.ok(page.radios.every((radio) => radio.attrs.type === "radio"));
  assert.match(html, /<fieldset[^>]*class="scenario-control"[^>]*>\s*<legend>[^<]+<\/legend>/);
  assert.match(html, /class="skip-link" href="#main"/);
  assert.match(css, /input:focus-visible\s*\+\s*span/);
  assert.match(css, /prefers-reduced-motion\s*:\s*reduce/);
  assert.match(css, /scroll-behavior\s*:\s*auto/);
  assert.match(html, /Browser simulation/);
});
