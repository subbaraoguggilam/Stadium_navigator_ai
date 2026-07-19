/**
 * app.js
 * Stadium Navigator AI — front-end logic.
 *
 * Responsibilities:
 *  1. Load venue graph + crowd data from /api/venue
 *  2. Render an interactive SVG map (click nodes to set destination)
 *  3. Handle chat form submissions + quick-action chips
 *  4. Animate route paths on the map
 *  5. Display step-by-step route directions and walk-time estimates
 *  6. Persist the user's "current location" in sessionStorage
 */

'use strict';

// ---------------------------------------------------------------------------
// Fixed pixel layout coordinates for the SVG viewBox 640×640.
// A real deployment would replace this with venue-provided GeoJSON/SVG.
// ---------------------------------------------------------------------------
const LAYOUT = {
  gate_a:              [560, 320],
  gate_b:              [320,  55],
  gate_c:              [ 80, 320],
  gate_d:              [320, 585],

  concourse_e1:        [460, 320],
  concourse_e2:        [460, 210],
  concourse_n1:        [320, 155],
  concourse_n2:        [320, 235],
  concourse_w1:        [180, 320],
  concourse_s1:        [320, 485],

  section_101:         [505, 405],
  section_112:         [420, 405],
  section_128:         [220, 405],
  section_215:         [505, 148],
  section_230:         [275, 148],
  section_301:         [358, 128],

  amenity_restroom_e:  [430, 378],
  amenity_restroom_n:  [278, 200],
  amenity_food_e:      [502, 278],
  amenity_food_n:      [380, 218],
  amenity_medical:     [418, 340],
  amenity_prayer:      [258, 178],
  amenity_merch:       [148, 362],
  amenity_atm:         [278, 442],

  transport_metro:     [610, 258],
  transport_bus:       [298,  18],
  transport_taxi:      [ 38, 278],
};

// Colors per node type — premium stadium palette
const TYPE_COLOR = {
  gate:      '#e8b44a',
  concourse: '#2d5a40',
  section:   '#3d9e70',
  restroom:  '#6a9f8a',
  food:      '#c8944a',
  medical:   '#d94f3c',
  prayer:    '#7a9fb0',
  shop:      '#8a7faf',
  service:   '#6a8fa0',
  transport: '#5ab8a0',
};

const TYPE_EMOJI = {
  gate: '🚪', concourse: '🏟', section: '🪑',
  restroom: '🚻', food: '🍔', medical: '🏥',
  prayer: '🕌', shop: '🛍', service: 'ℹ️', transport: '🚇',
};

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------
let venueData = null;
let currentPath = [];
let isLoading = false;

// ---------------------------------------------------------------------------
// DOM references (resolved after DOMContentLoaded)
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Venue loading
// ---------------------------------------------------------------------------
async function loadVenue() {
  try {
    const res = await fetch('/api/venue');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    venueData = await res.json();
    populateLocationPicker();
    drawMap();
    renderWelcomeMessage();
  } catch (err) {
    console.error('Failed to load venue data:', err);
    appendMessage(
      'Unable to load venue map. Please refresh the page.',
      'bot',
      false
    );
  }
}

// ---------------------------------------------------------------------------
// Location picker
// ---------------------------------------------------------------------------
function populateLocationPicker() {
  const select = $('current-location');
  select.innerHTML = '';

  // Group options by node type for better UX
  const typeOrder = ['gate', 'section', 'concourse', 'food', 'restroom', 'medical', 'prayer', 'shop', 'service', 'transport'];
  const grouped = {};
  Object.entries(venueData.nodes).forEach(([id, node]) => {
    const t = node.type || 'other';
    (grouped[t] = grouped[t] || []).push({ id, ...node });
  });

  typeOrder.forEach((type) => {
    if (!grouped[type] || !grouped[type].length) return;
    const group = document.createElement('optgroup');
    group.label = `${TYPE_EMOJI[type] || ''} ${type.charAt(0).toUpperCase() + type.slice(1)}s`;
    grouped[type].forEach(({ id, label }) => {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = label.split(' (')[0]; // strip "(Accessible)" suffix for brevity
      group.appendChild(opt);
    });
    select.appendChild(group);
  });

  // Restore last location from sessionStorage
  const saved = sessionStorage.getItem('stadium_nav_location');
  if (saved && venueData.nodes[saved]) {
    select.value = saved;
  } else {
    select.value = 'gate_a';
  }

  select.addEventListener('change', () => {
    sessionStorage.setItem('stadium_nav_location', select.value);
    drawMap();
  });
}

// ---------------------------------------------------------------------------
// Crowd utilities
// ---------------------------------------------------------------------------
function crowdLevel(nodeId) {
  return (venueData && venueData.crowd && venueData.crowd[nodeId]) || 2;
}

function crowdColor(level) {
  if (level >= 4) return 'var(--busy)';
  if (level === 3) return 'var(--moderate)';
  return 'var(--quiet)';
}

// ---------------------------------------------------------------------------
// SVG Map Rendering
// ---------------------------------------------------------------------------
const SVG_NS = 'http://www.w3.org/2000/svg';

function createSvgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function isPathEdge(a, b) {
  for (let i = 0; i < currentPath.length - 1; i++) {
    if (
      (currentPath[i] === a && currentPath[i + 1] === b) ||
      (currentPath[i] === b && currentPath[i + 1] === a)
    ) return true;
  }
  return false;
}

function drawMap() {
  const svg = $('stadium-map');
  if (!svg || !venueData) return;
  svg.innerHTML = '';

  const current = $('current-location').value;

  // -- Background stadium oval decoration --
  const oval = createSvgEl('ellipse', {
    cx: 320, cy: 320, rx: 260, ry: 240,
    fill: 'none',
    stroke: 'hsl(140, 22%, 14%)',
    'stroke-width': 1.5,
    'stroke-dasharray': '6 4',
    opacity: 0.5,
  });
  svg.appendChild(oval);

  // -- Edges --
  venueData.edges.forEach((edge) => {
    const a = LAYOUT[edge.from];
    const b = LAYOUT[edge.to];
    if (!a || !b) return;
    const onPath = isPathEdge(edge.from, edge.to);
    const line = createSvgEl('line', {
      x1: a[0], y1: a[1],
      x2: b[0], y2: b[1],
      stroke: onPath ? '#e8b44a' : 'hsl(140, 22%, 18%)',
      'stroke-width': onPath ? 4 : 1.5,
      'stroke-linecap': 'round',
      opacity: onPath ? 1 : 0.7,
    });
    if (onPath) {
      line.style.strokeDasharray = '1000';
      line.style.strokeDashoffset = '0';
      line.style.animation = 'path-draw 0.6s ease forwards';
      line.setAttribute('filter', 'url(#glow)');
    }
    svg.appendChild(line);
  });

  // -- Nodes --
  Object.entries(venueData.nodes).forEach(([id, node]) => {
    const pos = LAYOUT[id];
    if (!pos) return;
    const [x, y] = pos;
    const level = crowdLevel(id);
    const onPath = currentPath.includes(id);
    const isCurrent = id === current;
    const isGoal = currentPath.length > 0 && id === currentPath[currentPath.length - 1];

    // Pulse ring for current location
    if (isCurrent) {
      const ring = createSvgEl('circle', {
        cx: x, cy: y, r: 16,
        fill: 'none',
        stroke: '#ffffff',
        'stroke-width': 1.5,
        opacity: 0,
        class: 'current-ring',
      });
      // CSS animation via inline style
      ring.style.animation = 'ring-pulse 2s ease-out infinite';
      svg.appendChild(ring);
    }

    // Glow ring for goal node
    if (isGoal) {
      const glow = createSvgEl('circle', {
        cx: x, cy: y, r: 18,
        fill: 'hsla(40, 80%, 60%, 0.15)',
        stroke: '#e8b44a',
        'stroke-width': 1.5,
        opacity: 0.8,
      });
      svg.appendChild(glow);
    }

    const r = isGoal ? 13 : onPath ? 11 : isCurrent ? 10 : 7;
    const fill = onPath || isCurrent ? TYPE_COLOR[node.type] || '#6a9f8a' : TYPE_COLOR[node.type] || '#6a9f8a';
    const strokeColor = isCurrent ? '#ffffff' : onPath ? '#e8b44a' : crowdColor(level);
    const strokeW = isCurrent || onPath || isGoal ? 2.5 : 1.5;

    const circle = createSvgEl('circle', {
      cx: x, cy: y, r,
      fill,
      stroke: strokeColor,
      'stroke-width': strokeW,
      opacity: onPath || isCurrent ? 1 : 0.8,
      class: 'map-node-clickable',
      'data-node-id': id,
      'aria-label': `${node.label} — crowd: ${crowdLabel(level)}`,
      tabindex: '0',
      role: 'button',
    });

    if (onPath) {
      circle.setAttribute('filter', 'url(#glow)');
    }

    // Click to navigate
    circle.addEventListener('click', () => {
      const input = $('chat-input');
      if (input) {
        input.value = `Take me to ${node.label.split(' (')[0]}`;
        input.focus();
        updateCharCounter(input.value.length);
      }
    });
    circle.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        circle.click();
      }
    });

    // Tooltip title element for accessibility
    const titleEl = createSvgEl('title');
    titleEl.textContent = `${node.label} — ${crowdLabel(level)} (Level ${level}/5)`;
    circle.appendChild(titleEl);

    svg.appendChild(circle);

    // Labels: show for important types, path nodes, or current
    const showLabel = ['gate', 'section', 'transport', 'medical'].includes(node.type) || onPath || isCurrent;
    if (showLabel) {
      const shortLabel = node.label.split(' (')[0];
      const lx = x;
      const ly = onPath || isGoal ? y - 16 : y - 12;
      const label = createSvgEl('text', {
        x: lx, y: ly,
        fill: onPath ? '#e8b44a' : isCurrent ? '#ffffff' : 'hsl(110, 25%, 78%)',
        'font-size': onPath || isGoal ? '10.5' : '9.5',
        'font-weight': onPath || isGoal ? '700' : '500',
        'text-anchor': 'middle',
        'font-family': 'Inter, system-ui, sans-serif',
        opacity: onPath || isCurrent ? 1 : 0.85,
        'pointer-events': 'none',
      });
      label.textContent = shortLabel;
      svg.appendChild(label);
    }
  });

  // Current location marker (star/diamond indicator)
  const curPos = LAYOUT[current];
  if (curPos) {
    const [cx, cy] = curPos;
    const you = createSvgEl('text', {
      x: cx, y: cy + 3,
      'text-anchor': 'middle',
      'dominant-baseline': 'middle',
      'font-size': '10',
      'pointer-events': 'none',
    });
    you.textContent = '📍';
    svg.appendChild(you);
  }
}

function crowdLabel(level) {
  return ['', 'very quiet', 'quiet', 'moderate', 'busy', 'very busy'][Math.min(5, Math.max(1, level))];
}

// ---------------------------------------------------------------------------
// Chat messaging
// ---------------------------------------------------------------------------
function renderWelcomeMessage() {
  const log = $('chat-log');
  if (!log) return;
  const welcome = document.createElement('div');
  welcome.className = 'welcome-msg';
  welcome.setAttribute('role', 'status');
  welcome.innerHTML = `
    <span class="welcome-icon" aria-hidden="true">🏟️</span>
    <strong>Welcome to ${venueData?.venue_name?.split('(')[0]?.trim() || 'Stadium Navigator AI'}!</strong><br>
    I can help you find your seat, nearest restroom, food, medical help, and more.<br>
    Type a question or tap a suggestion below.
  `;
  log.appendChild(welcome);
}

function appendMessage(text, sender, isEmergency = false) {
  const log = $('chat-log');
  if (!log) return;

  const div = document.createElement('div');
  div.className = `msg ${sender}`;
  if (isEmergency) div.classList.add('emergency-msg');

  // Split text into lines; highlight warning lines
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    if (line.startsWith('⚠') || line.startsWith('🚨')) {
      const warn = document.createElement('span');
      warn.className = 'warning-text';
      warn.setAttribute('role', 'alert');
      warn.textContent = line;
      div.appendChild(warn);
    } else {
      if (i > 0) div.appendChild(document.createElement('br'));
      div.appendChild(document.createTextNode(line));
    }
  });

  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------------------
// Route display
// ---------------------------------------------------------------------------
function displayRoute(routeData) {
  if (!routeData) return;

  const summary = $('route-summary');
  const stepsPanel = $('route-steps-panel');
  const stepsList = $('route-steps-list');

  if (routeData.found && routeData.path.length > 0) {
    // Update summary bar
    if (summary) {
      $('route-distance').textContent = `${routeData.distance_meters}m`;
      $('route-time').textContent = `~${routeData.estimated_minutes} min`;
      $('route-steps-label').textContent = `${routeData.steps.length} steps`;
      summary.hidden = false;
    }

    // Populate steps panel
    if (stepsPanel && stepsList) {
      stepsList.innerHTML = '';
      routeData.steps.forEach((step, idx) => {
        const li = document.createElement('li');
        li.className = idx === 0 ? 'step-active' : '';
        const numSpan = document.createElement('span');
        numSpan.className = 'route-step-num';
        numSpan.textContent = idx + 1;
        const textSpan = document.createElement('span');
        textSpan.textContent = step;
        li.appendChild(numSpan);
        li.appendChild(textSpan);
        stepsList.appendChild(li);
      });
      stepsPanel.hidden = false;
    }
  } else {
    if (summary) summary.hidden = true;
    if (stepsPanel) stepsPanel.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Typing indicator
// ---------------------------------------------------------------------------
function showTyping() {
  const indicator = $('typing-indicator');
  if (indicator) indicator.hidden = false;
  const sendBtn = $('send-btn');
  if (sendBtn) sendBtn.disabled = true;
}

function hideTyping() {
  const indicator = $('typing-indicator');
  if (indicator) indicator.hidden = true;
  const sendBtn = $('send-btn');
  if (sendBtn) sendBtn.disabled = false;
}

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------
async function sendMessage(message) {
  if (isLoading || !message.trim()) return;
  isLoading = true;

  appendMessage(message, 'user');
  showTyping();

  const currentLocation = $('current-location').value;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, current_location: currentLocation }),
    });
    const data = await res.json();

    if (!res.ok) {
      appendMessage(data.error || 'Something went wrong. Please try again.', 'bot');
      return;
    }

    const isEmergency = data.intent && data.intent.emergency === true;
    appendMessage(data.reply, 'bot', isEmergency);

    // Update map path
    currentPath = (data.route && data.route.path) || [];
    drawMap();

    // Display route details
    if (data.route) {
      displayRoute(data.route);
    }

  } catch (err) {
    console.error('Chat request failed:', err);
    appendMessage(
      'Network error — the assistant is unreachable. Please check your connection and try again.',
      'bot'
    );
  } finally {
    hideTyping();
    isLoading = false;
  }
}

// ---------------------------------------------------------------------------
// Character counter
// ---------------------------------------------------------------------------
function updateCharCounter(length) {
  const counter = $('char-counter');
  if (!counter) return;
  counter.textContent = `${length} / 500`;
  counter.className = 'char-counter';
  if (length > 450) counter.classList.add('warn');
  if (length >= 500) counter.classList.add('limit');
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  // Chat form submission
  const form = $('chat-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const input = $('chat-input');
      const message = (input.value || '').trim();
      if (!message || isLoading) return;
      input.value = '';
      updateCharCounter(0);
      sendMessage(message);
    });
  }

  // Character counter live update
  const input = $('chat-input');
  if (input) {
    input.addEventListener('input', () => updateCharCounter(input.value.length));
    // Keyboard shortcuts
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        input.value = '';
        updateCharCounter(0);
        input.blur();
      }
    });
  }

  // Quick-action chips
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const msg = chip.dataset.msg;
      if (msg && !isLoading) sendMessage(msg);
    });
  });

  // Close route steps panel
  const closeSteps = $('close-steps');
  if (closeSteps) {
    closeSteps.addEventListener('click', () => {
      const panel = $('route-steps-panel');
      if (panel) panel.hidden = true;
    });
  }

  // Keyboard shortcut: / to focus input
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== input) {
      e.preventDefault();
      input && input.focus();
    }
  });

  // Initial venue load
  loadVenue();
});
