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

// ---- Ordering (spec/007_review_ui.md §4) -----------------------------------------------
// Order only: which clip comes before which. Bars are the director's business, so nothing here
// ever names one.

const order = JSON.parse(document.getElementById("order-state").textContent);
const sequencePanel = document.getElementById("sequence");
const sequenceList = document.getElementById("sequence-list");
const sequenceEmpty = document.getElementById("sequence-empty");
const cardsById = new Map(cards.map((card) => [card.dataset.id, card]));

// Written whole: a sequence is one statement, and saving it in pieces would leave the file
// describing an order nobody asked for if a save in the middle failed.
let orderSaves = Promise.resolve();
const saveOrder = debounce(() => {
  // Chained, not merely serialised by the server's lock: two whole-object writes that overlap
  // can land out of order, and the file would keep the earlier order while the page shows the
  // later one.
  const body = structuredClone(order);
  orderSaves = orderSaves.then(async () => {
    const saved = await send("PUT", "/api/order", body);
    for (const marker of [sequencePanel, document.querySelector(".modes")]) {
      marker.classList.toggle("unsaved", !saved);
    }
  });
}, 300);

function moveInSequence(from, to) {
  if (to < 0 || to >= order.sequence.length) return;
  const [moved] = order.sequence.splice(from, 1);
  order.sequence.splice(to, 0, moved);
  drawOrder();
  saveOrder();
  sequenceList.children[to]?.focus();
}

function sequenceEntry(id, index) {
  const item = document.createElement("li");
  item.draggable = true;
  item.tabIndex = 0;
  item.dataset.id = id;
  const card = cardsById.get(id);
  // Built as nodes, not markup: the id comes from a file a person can edit by hand.
  const position = document.createElement("span");
  position.className = "seq-index";
  position.textContent = index + 1;
  const name = document.createElement("strong");
  name.textContent = id;
  const material = document.createElement("span");
  material.className = "muted";
  material.textContent = card ? card.querySelector(".badge").textContent : "";
  item.append(position, name, material);

  const remove = document.createElement("button");
  remove.textContent = "remove";
  remove.addEventListener("click", () => {
    order.sequence.splice(index, 1);
    drawOrder();
    saveOrder();
  });
  item.append(remove);

  item.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", index));
  item.addEventListener("dragover", (event) => event.preventDefault());
  item.addEventListener("drop", (event) => {
    event.preventDefault();
    moveInSequence(Number(event.dataTransfer.getData("text/plain")), index);
  });
  // Dragging is not reachable from a keyboard, and every control here has to be
  // (spec/007_review_ui.md).
  item.addEventListener("keydown", (event) => {
    if (!event.altKey) return;
    if (event.key === "ArrowUp") { event.preventDefault(); moveInSequence(index, index - 1); }
    if (event.key === "ArrowDown") { event.preventDefault(); moveInSequence(index, index + 1); }
  });
  return item;
}

function drawOrder() {
  for (const button of document.querySelectorAll('input[name="order-mode"]')) {
    button.checked = button.value === order.mode;
  }
  sequencePanel.hidden = order.mode !== "strict";
  for (const block of document.querySelectorAll(".strict-only")) {
    block.hidden = order.mode !== "strict";
  }
  for (const block of document.querySelectorAll(".weighted-only")) {
    block.hidden = order.mode !== "weighted";
  }

  sequenceList.replaceChildren(...order.sequence.map(sequenceEntry));
  sequenceEmpty.hidden = order.sequence.length > 0;

  for (const card of cards) {
    const id = card.dataset.id;
    const at = order.sequence.indexOf(id);
    card.querySelector(".pin-at").textContent = at === -1 ? "" : `position ${at + 1}`;
    card.querySelector(".pin").textContent = at === -1 ? "add to sequence" : "remove from sequence";

    const weight = weightOf(id);
    const slider = card.querySelector(".weight");
    const readout = card.querySelector(".weight-readout");
    // The handle is reset too, so a cleared weight does not leave it sitting at the old value
    // beside a readout that says nothing is set.
    slider.value = weight === undefined ? 50 : weight;
    readout.textContent = weight === undefined ? "agent's call"
      : weight === 0 ? "opens the reel"
      : weight === 100 ? "closes the reel"
      : `weight ${weight}`;
    card.classList.toggle("pinned", at !== -1 || weight !== undefined);
  }
}

function weightOf(id) {
  if (id in order.weights) return order.weights[id];
  if (order.opening.includes(id)) return 0;
  if (order.ending.includes(id)) return 100;
  return undefined;
}

function setWeight(id, weight) {
  // One spelling on the way out: the buckets are shorthand the page offers, and keeping a clip
  // in both would leave two answers to the same question in the file.
  order.opening = order.opening.filter((other) => other !== id);
  order.ending = order.ending.filter((other) => other !== id);
  if (weight === undefined) delete order.weights[id];
  else order.weights[id] = weight;
  drawOrder();
  saveOrder();
}

for (const card of cards) {
  const id = card.dataset.id;
  card.querySelector(".pin").addEventListener("click", () => {
    const at = order.sequence.indexOf(id);
    if (at === -1) order.sequence.push(id);
    else order.sequence.splice(at, 1);
    drawOrder();
    saveOrder();
  });
  card.querySelector(".weight").addEventListener("input", (event) => {
    setWeight(id, Number(event.target.value));
  });
  card.querySelector(".send-start").addEventListener("click", () => setWeight(id, 0));
  card.querySelector(".send-end").addEventListener("click", () => setWeight(id, 100));
  card.querySelector(".clear-weight").addEventListener("click", () => setWeight(id, undefined));
}

for (const button of document.querySelectorAll('input[name="order-mode"]')) {
  button.addEventListener("change", () => {
    order.mode = button.value;
    drawOrder();
    saveOrder();
  });
}

drawOrder();

document.addEventListener("keydown", (event) => {
  // `?.` because a keydown whose focused element has just been removed is retargeted to the
  // document, which has no `matches` — and a throw here stops every keystroke silently.
  if (event.target.matches?.("input, textarea")) return;
  // The sequence list has its own arrow keys, and a digit pressed there would set a verdict on
  // whichever card the grid last had — a card the user is not looking at.
  if (event.target.closest?.("#sequence")) return;
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
