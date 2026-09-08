// Review page behaviour. No framework and no build step: this is a few hundred lines of DOM
// work, and a bundler would add a toolchain to a project whose real dependencies are ffmpeg
// and numpy (spec/004_stack.md).

const status = document.getElementById("status");
const grid = document.getElementById("grid");
const cards = [...document.querySelectorAll(".card")];
let current = 0;

// Autosave must never fail quietly. A reviewer who believes a verdict was recorded, and finds
// it was not, has lost work they cannot tell they lost (spec/007_review_ui.md).
function report(message, ok = false) {
  status.textContent = message;
  status.className = ok ? "status ok" : "status";
  status.hidden = false;
  if (ok) setTimeout(() => { status.hidden = true; }, 1200);
}

async function send(method, path, body) {
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      report(`could not save: ${response.status} ${response.statusText}`);
      return false;
    }
    return true;
  } catch (error) {
    report(`could not save: ${error.message}`);
    return false;
  }
}

function countReviewed() {
  const reviewed = cards.filter((card) => !card.querySelector(".verdict.agent.on")).length;
  document.getElementById("reviewed").textContent = reviewed;
}

async function setVerdict(card, verdict) {
  const buttons = [...card.querySelectorAll(".verdict")];
  const previous = buttons.find((button) => button.classList.contains("on"));
  for (const button of buttons) {
    const on = button.dataset.verdict === verdict;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  }
  countReviewed();

  const saved = await send("PUT", `/api/verdict/${card.dataset.id}`, { verdict });
  if (!saved && previous) {
    // Put the button back rather than leave the page claiming something the file does not say.
    for (const button of buttons) {
      const on = button === previous;
      button.classList.toggle("on", on);
      button.setAttribute("aria-checked", on ? "true" : "false");
    }
    countReviewed();
  }
}

function focusCard(index) {
  if (!cards.length) return;
  current = Math.max(0, Math.min(cards.length - 1, index));
  for (const [position, card] of cards.entries()) {
    card.classList.toggle("current", position === current);
  }
  cards[current].scrollIntoView({ block: "nearest", behavior: "smooth" });
  cards[current].focus({ preventScroll: true });
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

for (const [index, card] of cards.entries()) {
  const video = card.querySelector("video");
  if (video) {
    // Playing fifty clips at once makes the page unusable; hover is the intent signal.
    card.addEventListener("mouseenter", () => video.play().catch(() => {}));
    card.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
  }

  card.addEventListener("focus", () => { current = index; });

  for (const button of card.querySelectorAll(".verdict")) {
    button.addEventListener("click", () => setVerdict(card, button.dataset.verdict));
  }

  const start = card.querySelector(".trim-start");
  const end = card.querySelector(".trim-end");
  const readout = card.querySelector(".trim-readout");

  const showTrim = () => {
    readout.textContent = `${(+end.value - +start.value).toFixed(2)}s of ` +
      `${(+card.dataset.end - +card.dataset.start).toFixed(2)}s`;
  };

  const saveTrim = debounce(async () => {
    if (+end.value <= +start.value) {
      report("trim end must come after its start");
      return;
    }
    await send("PUT", `/api/trim/${card.dataset.id}`, {
      start: +start.value,
      end: +end.value,
    });
  }, 300);

  for (const handle of [start, end]) {
    handle.addEventListener("input", () => { showTrim(); saveTrim(); });
  }
  showTrim();

  card.querySelector(".reset-trim").addEventListener("click", async () => {
    start.value = card.dataset.start;
    end.value = card.dataset.end;
    showTrim();
    await send("DELETE", `/api/trim/${card.dataset.id}`);
  });

  const note = card.querySelector(".note-input");
  note.addEventListener(
    "input",
    debounce(() => send("PUT", `/api/note/${card.dataset.id}`, { note: note.value }), 400),
  );
}

document.addEventListener("keydown", (event) => {
  if (event.target.matches("input, textarea")) return;
  const keys = { 1: "drop", 2: "agent", 3: "keep" };
  if (keys[event.key] && cards[current]) {
    event.preventDefault();
    setVerdict(cards[current], keys[event.key]);
  } else if (event.key === "j" || event.key === "ArrowDown") {
    event.preventDefault();
    focusCard(current + 1);
  } else if (event.key === "k" || event.key === "ArrowUp") {
    event.preventDefault();
    focusCard(current - 1);
  }
});

const complete = document.getElementById("complete");
complete.addEventListener("click", async () => {
  if (await send("POST", "/api/complete")) {
    complete.disabled = true;
    complete.textContent = "marked done";
    report("marked done — the agent may proceed", true);
  }
});

if (grid && cards.length) focusCard(0);
