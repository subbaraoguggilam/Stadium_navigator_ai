// Fixed layout coordinates for the sample venue graph (viewBox 640x640).
// A real deployment would replace this with venue-provided GeoJSON/SVG.
const LAYOUT = {
  gate_a: [560, 320], gate_b: [320, 60], gate_c: [80, 320], gate_d: [320, 580],
  concourse_e1: [460, 320], concourse_e2: [460, 220],
  concourse_n1: [320, 160], concourse_n2: [320, 240],
  concourse_w1: [180, 320], concourse_s1: [320, 480],
  section_101: [500, 400], section_112: [420, 400], section_128: [220, 400],
  section_215: [500, 150], section_230: [280, 150], section_301: [360, 130],
  amenity_restroom_e: [430, 380], amenity_restroom_n: [280, 200],
  amenity_food_e: [500, 280], amenity_food_n: [380, 220],
  amenity_medical: [420, 340], amenity_prayer: [260, 180],
  amenity_merch: [150, 360], amenity_atm: [280, 440],
  transport_metro: [610, 260], transport_bus: [300, 20], transport_taxi: [40, 280],
};

const TYPE_COLOR = {
  gate: "#e8b44a", concourse: "#3a5a4a", section: "#4fae84",
  restroom: "#9fb3a6", food: "#e8b44a", medical: "#e2574c",
  prayer: "#9fb3a6", shop: "#9fb3a6", service: "#9fb3a6", transport: "#7fd6b3",
};

let venueData = null;
let currentPath = [];

async function loadVenue() {
  const res = await fetch("/api/venue");
  venueData = await res.json();
  populateLocationPicker();
  drawMap();
}

function populateLocationPicker() {
  const select = document.getElementById("current-location");
  select.innerHTML = "";
  Object.entries(venueData.nodes).forEach(([id, node]) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = node.label;
    select.appendChild(opt);
  });
  select.value = "gate_a";
  select.addEventListener("change", drawMap);
}

function crowdColor(level) {
  if (level >= 4) return "var(--busy)";
  if (level === 3) return "var(--moderate)";
  return "var(--quiet)";
}

function drawMap() {
  const svg = document.getElementById("stadium-map");
  svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  const current = document.getElementById("current-location").value;

  // edges
  venueData.edges.forEach((edge) => {
    const a = LAYOUT[edge.from], b = LAYOUT[edge.to];
    if (!a || !b) return;
    const onPath = isPathEdge(edge.from, edge.to);
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", a[0]); line.setAttribute("y1", a[1]);
    line.setAttribute("x2", b[0]); line.setAttribute("y2", b[1]);
    line.setAttribute("stroke", onPath ? "#e8b44a" : "#23402f");
    line.setAttribute("stroke-width", onPath ? 4 : 2);
    svg.appendChild(line);
  });

  // nodes
  Object.entries(venueData.nodes).forEach(([id, node]) => {
    const pos = LAYOUT[id];
    if (!pos) return;
    const [x, y] = pos;
    const level = venueData.crowd[id] || 2;

    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", x); circle.setAttribute("cy", y);
    circle.setAttribute("r", currentPath.includes(id) ? 12 : (id === current ? 11 : 7));
    circle.setAttribute("fill", TYPE_COLOR[node.type] || "#9fb3a6");
    circle.setAttribute("stroke", id === current ? "#fff" : (currentPath.includes(id) ? "#e8b44a" : "none"));
    circle.setAttribute("stroke-width", id === current || currentPath.includes(id) ? 3 : 0);
    svg.appendChild(circle);

    if (["gate", "section", "transport"].includes(node.type) || currentPath.includes(id)) {
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", x); label.setAttribute("y", y - 12);
      label.setAttribute("fill", "#f2f5ee");
      label.setAttribute("font-size", "10");
      label.setAttribute("text-anchor", "middle");
      label.textContent = node.label.split(" (")[0];
      svg.appendChild(label);
    }
  });
}

function isPathEdge(a, b) {
  for (let i = 0; i < currentPath.length - 1; i++) {
    if ((currentPath[i] === a && currentPath[i + 1] === b) || (currentPath[i] === b && currentPath[i + 1] === a)) {
      return true;
    }
  }
  return false;
}

function appendMessage(text, sender) {
  const log = document.getElementById("chat-log");
  const div = document.createElement("div");
  div.className = `msg ${sender}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function sendMessage(message) {
  appendMessage(message, "user");
  const currentLocation = document.getElementById("current-location").value;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, current_location: currentLocation }),
    });
    const data = await res.json();

    if (!res.ok) {
      appendMessage(data.error || "Something went wrong.", "bot");
      return;
    }

    appendMessage(data.reply, "bot");
    currentPath = (data.route && data.route.path) || [];
    drawMap();
  } catch (err) {
    appendMessage("Network error — the assistant is unreachable right now.", "bot");
  }
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  sendMessage(message);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => sendMessage(chip.dataset.msg));
});

loadVenue();
