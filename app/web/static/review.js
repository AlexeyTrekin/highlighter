// Review page behaviour. No framework and no build step: this is a few hundred lines of DOM
// work, and a bundler would add a toolchain to a project whose real dependencies are ffmpeg
// and numpy (spec/004_stack.md).

const status = document.getElementById("status");
const grid = document.getElementById("grid");
const cards = [...document.querySelectorAll("#grid .card")];

// The longest slot the director builds (CLIP_BARS_LONG). A trim longer than this is cut down
// to it, so the readout must not promise the user the extra seconds.
const MAX_BARS = 3;
const TRIM_STEP = 0.05;

const barSeconds = Number(document.body.dataset.barS) || 0;
const pending = [];
let current = 0;
let hideTimer;

// Autosave must never fail quietly. A reviewer who believes a verdict was recorded, and finds
// it was not, has lost work they cannot tell they lost (spec/007_review_ui.md).
function report(message, ok = false) {
  // The success timer is cancelled rather than left running: it would otherwise hide an error
  // raised in the second after a save, which is exactly when one is most likely.
  clearTimeout(hideTimer);
  status.textContent = message;
  status.className = ok ? "status ok" : "status";
  status.hidden = false;
  if (ok) hideTimer = setTimeout(() => { status.hidden = true; }, 1200);
}

async function send(method, path, body) {
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      // Lets a save started as the tab closes finish, which is what makes the flush below
      // worth doing at all.
      keepalive: true,
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

function paint(buttons, verdict) {
  for (const button of buttons) {
    const on = button.dataset.verdict === verdict;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  }
}

async function setVerdict(card, verdict) {
  const buttons = [...card.querySelectorAll(".verdict")];
  const previous = buttons.find((button) => button.classList.contains("on"));
  paint(buttons, verdict);
  countReviewed();

  const saved = await send("PUT", `/api/verdict/${card.dataset.id}`, { verdict });
  if (!saved && previous) {
    // Put the button back rather than leave the page claiming something the file does not say.
    paint(buttons, previous.dataset.verdict);
    countReviewed();
  }
}

function wireVerdicts(card) {
  for (const button of card.querySelectorAll(".verdict")) {
    button.addEventListener("click", () => setVerdict(card, button.dataset.verdict));
  }
}

// Which card a keystroke acts on. Kept in step with hover and focus both: a verdict recorded
// on a card that is not the one under the pointer is silent and wrong, and it overwrites
// whatever that other card already said.
function markCurrent(index) {
  current = Math.max(0, Math.min(cards.length - 1, index));
  for (const [position, card] of cards.entries()) {
    card.classList.toggle("current", position === current);
  }
}

function focusCard(index) {
  if (!cards.length) return;
  markCurrent(index);
  cards[current].scrollIntoView({ block: "nearest", behavior: "smooth" });
  cards[current].focus({ preventScroll: true });
}

function debounce(fn, delay) {
  let timer;
  let latest;
  const wrapped = (...args) => {
    latest = args;
    clearTimeout(timer);
    timer = setTimeout(() => { timer = undefined; fn(...latest); }, delay);
  };
  wrapped.flush = () => {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    fn(...latest);
  };
  pending.push(wrapped);
  return wrapped;
}

// Closing the tab mid-way is a supported way to stop (spec/007_review_ui.md), so the last few
// hundred milliseconds of typing or dragging must not be the part that is lost.
window.addEventListener("pagehide", () => { for (const save of pending) save.flush(); });

function slotText(length) {
  if (!barSeconds) return "";
  const bars = Math.min(MAX_BARS, Math.floor(length / barSeconds + 1e-9));
  if (bars < 1) {
    return ` — too short to cut: the shortest slot is ${barSeconds.toFixed(2)}s`;
  }
  const cut = (bars * barSeconds).toFixed(2);
  return ` — cuts to ${bars} bar${bars === 1 ? "" : "s"} (${cut}s), ending where you set “end”`;
}

for (const [index, card] of cards.entries()) {
  const video = card.querySelector("video");
  if (video) {
    // Playing fifty clips at once makes the page unusable; hover is the intent signal.
    card.addEventListener("mouseenter", () => video.play().catch(() => {}));
    card.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
  }

  card.addEventListener("mouseenter", () => markCurrent(index));
  // `focusin` and not `focus`: focus does not bubble, so clicking a verdict button — which
  // focuses the button, not the card — would leave the keyboard pointed somewhere else.
  card.addEventListener("focusin", () => markCurrent(index));

  wireVerdicts(card);

  const start = card.querySelector(".trim-start");
  const end = card.querySelector(".trim-end");
  const readout = card.querySelector(".trim-readout");
  const windowStart = +card.dataset.start;

  // Seek the proxy to the handle being dragged, so the user sees the frame they are cutting on
  // rather than a number (spec/007_review_ui.md).
  const scrub = (seconds) => {
    if (!video) return;
    video.pause();
    const at = Math.max(0, seconds - windowStart);
    if (video.readyState === 0) {
      video.preload = "metadata";
      video.addEventListener("loadedmetadata", () => { video.currentTime = at; }, { once: true });
      video.load();
    } else {
      video.currentTime = at;
    }
  };

  const showTrim = () => {
    const length = +end.value - +start.value;
    const whole = +card.dataset.end - windowStart;
    readout.textContent = `${length.toFixed(2)}s of ${whole.toFixed(2)}s${slotText(length)}`;
  };

  const saveTrim = debounce(async () => {
    const saved = await send("PUT", `/api/trim/${card.dataset.id}`, {
      start: +start.value,
      end: +end.value,
    });
    // The dragged position is left in place on failure: throwing it away would destroy the
    // adjustment the user just made. The class says the file does not hold it yet.
    card.classList.toggle("unsaved", !saved);
  }, 300);

  for (const handle of [start, end]) {
    handle.addEventListener("input", () => {
      // The handles are two sliders over one range and can be dragged past each other.
      if (+start.value >= +end.value) {
        if (handle === start) start.value = +end.value - TRIM_STEP;
        else end.value = +start.value + TRIM_STEP;
      }
      showTrim();
      scrub(+handle.value);
      saveTrim();
    });
  }
  showTrim();

  card.querySelector(".reset-trim").addEventListener("click", async () => {
    start.value = card.dataset.start;
    end.value = card.dataset.end;
    showTrim();
    card.classList.toggle("unsaved", !(await send("DELETE", `/api/trim/${card.dataset.id}`)));
  });

  const note = card.querySelector(".note-input");
  const saveNote = debounce(async () => {
    const saved = await send("PUT", `/api/note/${card.dataset.id}`, { note: note.value });
    note.classList.toggle("unsaved", !saved);
  }, 400);
  note.addEventListener("input", saveNote);
}

// Candidates the pipeline dropped carry the same verdict control: a keep there is a rescue,
// and the director lets it override the quality gates (spec/007_review_ui.md).
for (const entry of document.querySelectorAll(".dropped li[data-id]")) {
  wireVerdicts(entry);
}

document.addEventListener("keydown", (event) => {
  // `?.` because a keydown whose focused element has just been removed is retargeted to the
  // document, which has no `matches` — and a throw here stops every keystroke silently.
  if (event.target.matches?.("input, textarea")) return;
  // Cmd+1 switches browser tabs and Cmd+K opens the address bar; neither is a verdict.
  if (event.metaKey || event.ctrlKey || event.altKey) return;
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

// Marked, not focused: taking focus on load scrolls the page away from its own header.
if (grid && cards.length) markCurrent(0);
