(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const scenarios = {
    lost: {
      title: "The payment landed.\nThe receipt didn’t.",
      interruption:
        "The provider paid $50, but the worker stopped before saving the receipt. Recovery has to establish what happened.",
      outcome: "Recover the original.\nDon’t invent a retry.",
      explanation:
        "Belay finds the original receipt. A stable provider key also prevents duplication here. The fresh-key baseline makes a new $30 decision.",
      evidence:
        "Existing provider idempotency also solves this case when the original request and key stay stable.",
      paid: 50,
      strategies: {
        belay: [
          50,
          "Reconciled",
          "Provider lookup confirms the original $50 refund. No new payment.",
          "good",
        ],
        naive: [
          80,
          "Second refund",
          "The scripted retry sends another $30 with a new key. Total: $80.",
          "warn",
        ],
        stable: [
          50,
          "Deduplicated",
          "The provider honors the same key and returns the original $50 receipt.",
          "good",
        ],
      },
    },
    revoked: {
      title: "The worker stopped.\nPermission changed.",
      interruption:
        "No payment was sent. While the worker was down, refund permission was withdrawn. The saved intent is still $50.",
      outcome: "The right next step\nis no new action.",
      explanation:
        "All three strategies in this example check current permission before sending. Each refuses the new refund. An old authorization is not enough.",
      evidence:
        "A fresh permission check is necessary even when a provider supports idempotency.",
      paid: 0,
      strategies: {
        belay: [
          0,
          "Refused",
          "Current permission is revoked. No new refund is sent.",
          "good",
        ],
        naive: [
          0,
          "Refused",
          "This baseline also checks current permission and refuses the refund.",
          "good",
        ],
        stable: [
          0,
          "Refused",
          "A stable key does not authorize a new payment. The request is refused.",
          "good",
        ],
      },
    },
    opaque: {
      title: "A payment happened.\nRecovery can’t prove it.",
      interruption:
        "The observer can see $50 in the teaching ledger. But this provider offers neither lookup nor idempotency, so recovery cannot establish the outcome.",
      outcome: "Leave the unknown\nunknown.",
      explanation:
        "Belay and the stable-key strategy halt. The observer’s ledger is not evidence available to recovery. The fresh-key baseline risks a duplicate.",
      evidence:
        "Observer totals are visible for teaching only. The recovery decision cannot use this ledger as an oracle.",
      paid: 50,
      strategies: {
        belay: [
          50,
          "Unknown · halted",
          "No usable evidence. The outcome stays unknown; no retry is sent.",
          "warn",
        ],
        naive: [
          80,
          "Second refund",
          "Without reconciling the first attempt, the scripted retry adds $30.",
          "warn",
        ],
        stable: [
          50,
          "Unknown · halted",
          "A key cannot deduplicate when the provider does not honor it. Halt.",
          "warn",
        ],
      },
    },
  };

  let scenario = "lost";
  let step = 0;
  const next = $("demo-next");
  const stepLabels = [
    "STEP 01 / THE ORIGINAL INTENT",
    "STEP 02 / THE INTERRUPTION",
    "STEP 03 / THE RECOVERY DECISION",
  ];
  const buttons = [
    "Show the interruption",
    "Show the recovery",
    "Run it again",
  ];
  const initialDetails = {
    belay: "Original identity and intent are saved.",
    naive: "This baseline makes a new decision on retry.",
    stable: "The original request and key are retained.",
  };

  function lines(element, value) {
    element.replaceChildren();
    value.split("\n").forEach((line, index) => {
      if (index) element.append(document.createElement("br"));
      element.append(document.createTextNode(line));
    });
  }

  function render(announce = true) {
    const current = scenarios[scenario];
    $("step-label").textContent = stepLabels[step];
    lines(
      $("demo-headline"),
      step === 0
        ? "One order.\nOne $50 refund."
        : step === 1
          ? current.title
          : current.outcome,
    );
    $("demo-explanation").textContent =
      step === 0
        ? "The agent’s original intent is saved under a stable identity. No refund has been sent yet."
        : step === 1
          ? current.interruption
          : current.explanation;
    next.replaceChildren(document.createTextNode(buttons[step] + " "));
    const arrow = document.createElement("span");
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = step === 2 ? "↺" : "→";
    next.append(arrow);
    Object.keys(initialDetails).forEach((strategy) => {
      const result = step === 2 ? current.strategies[strategy] : null;
      const total = result ? result[0] : step === 1 ? current.paid : 0;
      const status = result
        ? result[1]
        : step === 0
          ? "Ready"
          : scenario === "revoked"
            ? "Permission changed"
            : "Receipt missing";
      const detail = result
        ? result[2]
        : step === 0
          ? initialDetails[strategy]
          : scenario === "revoked"
            ? "No payment was sent. Permission is now withdrawn."
            : "The observer sees $50 paid. The runtime has no saved receipt.";
      document.querySelector(`[data-total="${strategy}"]`).textContent =
        `$${total}`;
      const badge = document.querySelector(`[data-status="${strategy}"]`);
      badge.textContent = status;
      badge.closest(".strategy").dataset.tone = result
        ? result[3]
        : step === 1
          ? "warn"
          : "ready";
      document.querySelector(`[data-detail="${strategy}"]`).textContent =
        detail;
    });
    $("demo-evidence").textContent =
      step === 2
        ? current.evidence
        : step === 1
          ? "A missing local receipt does not establish whether the external action happened."
          : "A durable identity keeps the original operation in view.";
    document
      .querySelectorAll(".step-dots i")
      .forEach((dot, index) => dot.classList.toggle("active", index === step));
    if (announce) {
      const outcome =
        step === 2
          ? ` With Belay: ${current.strategies.belay[1]}, observer total $${current.strategies.belay[0]}. Fresh-key retry: observer total $${current.strategies.naive[0]}. Stable provider key: ${current.strategies.stable[1]}, observer total $${current.strategies.stable[0]}.`
          : "";
      $("demo-announcement").textContent =
        `Step ${step + 1} of 3. ${$("demo-explanation").textContent}${outcome}`;
    }
  }

  next.addEventListener("click", () => {
    step = (step + 1) % 3;
    render();
  });
  $("demo-reset").addEventListener("click", () => {
    step = 0;
    render();
  });
  document.querySelectorAll('input[name="scenario"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (!input.checked || !Object.hasOwn(scenarios, input.value)) return;
      scenario = input.value;
      step = 0;
      render();
    });
  });

  const menu = document.querySelector(".menu-toggle");
  const nav = $("main-nav");
  function closeMenu() {
    menu.setAttribute("aria-expanded", "false");
    nav.classList.remove("is-open");
  }
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("is-open", open);
  });
  nav
    .querySelectorAll("a")
    .forEach((link) => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      menu.getAttribute("aria-expanded") === "true"
    ) {
      closeMenu();
      menu.focus();
    }
  });

  $("copy-command").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(
        $("setup-command").textContent.trim(),
      );
      $("copy-command").textContent = "Copied ✓";
      $("copy-status").textContent = "Setup commands copied to clipboard.";
    } catch {
      const range = document.createRange();
      range.selectNodeContents($("setup-command"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      $("copy-status").textContent =
        "Commands selected. Use your browser’s copy command.";
    }
  });

  // The page is useful without this optional enrichment, including file previews.
  // Published evidence links are pinned to the revision used for the site build.
  if (window.location.protocol !== "file:") {
    fetch("evidence.json")
      .then((response) => {
        if (!response.ok) throw new Error("Evidence metadata unavailable");
        return response.json();
      })
      .then((evidence) => {
        const links = evidence.sources || evidence.source_urls || {};
        document.querySelectorAll("[data-source]").forEach((link) => {
          const source = links[link.dataset.source];
          const url = typeof source === "string" ? source : source?.url;
          if (
            typeof url === "string" &&
            url.startsWith("https://github.com/Frank-7/Belay/blob/")
          )
            link.href = url;
        });
      })
      .catch(() => {
        /* Committed metric text and repository links remain available. */
      });
  }
  render(false);
})();
