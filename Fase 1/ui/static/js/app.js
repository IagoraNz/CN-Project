/**
 * CN-Project control panel
 */

const TARGET_LABELS = {
  setup: "Setup",
  "test-all": "Test",
  analyze: "Analyze",
  down: "Down",
};

const PROGRESS_HINTS = {
  setup: {
    patterns: [
      { re: /build/i, pct: 25, sub: "Construindo imagem Docker…" },
      { re: /up|start|creat/i, pct: 60, sub: "Iniciando containers…" },
      { re: /quickstart|success|done|ready/i, pct: 90, sub: "Finalizando setup…" },
    ],
    defaultSub: "Build Docker · Subindo containers",
  },
  "test-all": {
    patterns: [
      { re: /scenario\s*a/i, pct: 15, sub: "Cenário A — rede ideal", chip: "A" },
      { re: /scenario\s*b/i, pct: 40, sub: "Cenário B — perda 10%", chip: "B" },
      { re: /scenario\s*c/i, pct: 65, sub: "Cenário C — perda 20%", chip: "C" },
      { re: /rudp/i, pct: 80, sub: "Protocolo R-UDP" },
      { re: /completed|finished|all tests/i, pct: 95, sub: "Testes concluídos" },
    ],
    defaultSub: "Cenários A · B · C × TCP & R-UDP",
    steps: 6,
  },
  analyze: {
    patterns: [
      { re: /validacao|overhead/i, pct: 20, sub: "Validação overhead…" },
      { re: /eficiencia|vazao/i, pct: 45, sub: "Eficiência e vazão…" },
      { re: /retransmis/i, pct: 65, sub: "Retransmissões…" },
      { re: /saved|✓|sucesso/i, pct: 90, sub: "Salvando gráficos…" },
    ],
    defaultSub: "Seaborn · Validação cruzada",
  },
  down: {
    patterns: [
      { re: /chown|fix-perm/i, pct: 20, sub: "Ajustando permissões…" },
      { re: /stop|down|remov/i, pct: 50, sub: "Parando containers…" },
      { re: /clean|rm |pcap|csv|logs/i, pct: 85, sub: "Limpando csv, logs e pcap…" },
    ],
    defaultSub: "Parando containers · Limpando dados",
  },
};

let running = false;
let eventSource = null;
let progressTimer = null;
let testStep = 0;

const terminal = document.getElementById("terminal");
const stage = document.getElementById("animation-stage");
const statusPill = document.getElementById("status-pill");
const buttons = document.querySelectorAll(".action-btn");

function setButtonsDisabled(disabled) {
  buttons.forEach((b) => (b.disabled = disabled));
}

function setStatus(mode, text) {
  statusPill.className = `status-pill status-pill--${mode}`;
  statusPill.textContent = text;
}

function showScene(target) {
  stage.dataset.mode = target;
  stage.querySelectorAll(".scene").forEach((s) => {
    s.classList.toggle("active", s.dataset.scene === target);
  });
}

function getProgressBar(target) {
  const map = {
    setup: "progress-setup",
    "test-all": "progress-test",
    analyze: "progress-analyze",
    down: "progress-down",
  };
  return document.getElementById(map[target]);
}

function setProgress(target, pct, indeterminate = false) {
  const bar = getProgressBar(target);
  if (!bar) return;
  bar.classList.toggle("indeterminate", indeterminate);
  if (!indeterminate) {
    bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  }
}

function resetProgress(target) {
  const bar = getProgressBar(target);
  if (bar) {
    bar.classList.remove("indeterminate");
    bar.style.width = "0%";
  }
  if (target === "test-all") {
    document.querySelectorAll(".chip").forEach((c) => {
      c.classList.remove("active", "done");
    });
    testStep = 0;
  }
}

function activateChip(letter) {
  document.querySelectorAll(".chip").forEach((c) => {
    const s = c.dataset.s;
    if (s === letter) c.classList.add("active");
    else if (["A", "B", "C"].indexOf(s) < ["A", "B", "C"].indexOf(letter)) {
      c.classList.remove("active");
      c.classList.add("done");
    }
  });
}

function updateSub(target, text) {
  const ids = {
    setup: "setup-sub",
    "test-all": "test-sub",
    analyze: "analyze-sub",
    down: "down-sub",
  };
  const el = document.getElementById(ids[target]);
  if (el && text) el.textContent = text;
}

function parseProgress(target, line) {
  const hints = PROGRESS_HINTS[target];
  if (!hints) return;

  for (const p of hints.patterns) {
    if (p.re.test(line)) {
      if (p.pct != null) setProgress(target, p.pct, false);
      if (p.sub) updateSub(target, p.sub);
      if (p.chip) activateChip(p.chip);
      return;
    }
  }

  if (target === "test-all" && /running|test completed|\[OK\]/i.test(line)) {
    testStep = Math.min((hints.steps || 6) - 1, testStep + 1);
    const pct = Math.round(((testStep + 1) / (hints.steps || 6)) * 100);
    setProgress(target, pct, false);
  }
}

function appendLog(line) {
  const span = document.createElement("span");
  span.className = "line";
  if (/error|failed|fatal/i.test(line)) span.classList.add("line-err");
  else if (/warn/i.test(line)) span.classList.add("line-warn");
  else if (/\[TEST\]|\[OK\]/i.test(line)) span.classList.add("line-info");
  else if (/^make |^docker /i.test(line)) span.classList.add("line-cmd");

  span.textContent = line + "\n";
  terminal.appendChild(span);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearTerminal() {
  terminal.innerHTML = "";
}

function startIndeterminateProgress(target) {
  const bar = getProgressBar(target);
  if (bar) {
    bar.style.width = "30%";
    bar.classList.add("indeterminate");
  }
  let fake = 5;
  clearInterval(progressTimer);
  progressTimer = setInterval(() => {
    if (!running) return;
    fake = Math.min(85, fake + 0.8);
    const b = getProgressBar(target);
    if (b && !b.classList.contains("indeterminate")) {
      const cur = parseFloat(b.style.width) || 0;
      if (cur < fake) setProgress(target, fake, false);
    }
  }, 800);
}

async function runTarget(target) {
  if (running) return;

  running = true;
  setButtonsDisabled(true);
  setStatus("running", `Executando ${TARGET_LABELS[target]}…`);
  showScene(target);
  resetProgress(target);
  updateSub(target, PROGRESS_HINTS[target]?.defaultSub);
  startIndeterminateProgress(target);

  appendLog(`$ make ${target}`);
  appendLog("—".repeat(48));

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target }),
    });

    const body = await res.json();
    if (!res.ok) {
      appendLog(`[ERRO] ${body.error || res.statusText}`);
      setStatus("err", "Erro");
      finishRun(target, false);
      return;
    }

    connectStream(target);
  } catch (err) {
    appendLog(`[ERRO] ${err.message}`);
    setStatus("err", "Falha de rede");
    finishRun(target, false);
  }
}

function connectStream(target) {
  if (eventSource) eventSource.close();

  eventSource = new EventSource("/api/stream");

  eventSource.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }

    if (msg.type === "log" && msg.line) {
      appendLog(msg.line);
      parseProgress(target, msg.line);
    }

    if (msg.type === "done") {
      const bar = getProgressBar(target);
      if (bar) bar.classList.remove("indeterminate");
      setProgress(target, 100, false);
      if (target === "test-all") {
        document.querySelectorAll(".chip").forEach((c) => {
          c.classList.remove("active");
          c.classList.add("done");
        });
      }
      appendLog("—".repeat(48));
      appendLog(
        msg.success
          ? `[OK] make ${target} concluído (código 0)`
          : `[ERRO] make ${target} falhou (código ${msg.code})`
      );
      setStatus(msg.success ? "ok" : "err", msg.success ? "Concluído" : "Falhou");
      finishRun(target, msg.success);
      eventSource.close();
      eventSource = null;
    }
  };

  eventSource.onerror = () => {
    if (!running) return;
    appendLog("[ERRO] Conexão com stream perdida.");
    setStatus("err", "Stream perdido");
    finishRun(target, false);
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  };
}

let graphsCache = [];

async function loadGraphs() {
  const res = await fetch("/api/graphs");
  const data = await res.json();
  graphsCache = data.graphs || [];
  return graphsCache;
}

function selectGraph(graph) {
  const img = document.getElementById("graph-image");
  const caption = document.getElementById("graph-caption");
  document.querySelectorAll(".graph-chip").forEach((c) => {
    c.classList.toggle("active", c.dataset.id === graph.id);
  });
  img.src = `${graph.url}?t=${Date.now()}`;
  img.classList.remove("hidden");
  img.alt = graph.label;
  caption.textContent = graph.label;
}

async function showGraphViewer() {
  const graphs = await loadGraphs();
  const picker = document.getElementById("graph-picker");
  const img = document.getElementById("graph-image");
  const caption = document.getElementById("graph-caption");

  picker.innerHTML = "";
  if (graphs.length === 0) {
    showScene("idle");
    appendLog("[AVISO] Nenhum gráfico encontrado em results/graphs/");
    return;
  }

  graphs.forEach((g, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "graph-chip" + (i === 0 ? " active" : "");
    btn.dataset.id = g.id;
    btn.textContent = g.label;
    btn.addEventListener("click", () => selectGraph(g));
    picker.appendChild(btn);
  });

  showScene("graphs");
  selectGraph(graphs[0]);
}

function finishRun(target, success) {
  running = false;
  setButtonsDisabled(false);
  clearInterval(progressTimer);
  progressTimer = null;

  if (!success) return;

  if (target === "analyze") {
    setTimeout(() => {
      if (!running) showGraphViewer();
    }, 600);
    return;
  }

  setTimeout(() => {
    if (!running) showScene("idle");
  }, 4000);
}

document.getElementById("btn-back-idle").addEventListener("click", () => {
  showScene("idle");
});

buttons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.target;
    if (target === "down") {
      if (!confirm("Parar containers e limpar csv, logs e pcap?")) return;
    }
    runTarget(target);
  });
});

document.getElementById("btn-clear-logs").addEventListener("click", clearTerminal);

// Check server status on load
fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    if (s.running) {
      setStatus("running", `Executando ${TARGET_LABELS[s.target]}…`);
      setButtonsDisabled(true);
      showScene(s.target);
      connectStream(s.target);
      running = true;
    }
  })
  .catch(() => {});
