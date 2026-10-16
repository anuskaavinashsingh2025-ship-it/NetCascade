// Thin client for the NetCascade Flask API. Every call resolves to `data` or throws ApiError.

export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch {
    throw new ApiError("Cannot reach the NetCascade backend. Is `python -m backend` running?", 0, "network_error");
  }
  let payload = null;
  try {
    payload = await resp.json();
  } catch {
    throw new ApiError(`Unexpected response from server (${resp.status})`, resp.status, "bad_response");
  }
  if (!resp.ok || !payload.success) {
    const e = payload.error || {};
    throw new ApiError(e.message || `Request failed (${resp.status})`, resp.status, e.code, e.details);
  }
  return payload.data;
}

const enc = encodeURIComponent;

export const api = {
  topologies: () => request("GET", "/topologies"),
  loadTopology: (name) => request("POST", `/topologies/${enc(name)}/load`),
  topology: () => request("GET", "/topology"),
  resetTopology: () => request("POST", "/topology/reset"),
  connectivity: () => request("GET", "/analysis/connectivity"),
  rankings: () => request("GET", "/analysis/rankings"),
  evaluation: (repeat = 5) => request("GET", `/analysis/evaluation?repeat=${repeat}&records=false`),
  evaluationCompare: (topologies, repeat = 5) =>
    request("GET", `/analysis/evaluation/compare?topologies=${topologies.map(enc).join(",")}&repeat=${repeat}`),

  simulation: () => request("GET", "/simulation"),
  simulateDevice: (deviceId) => request("POST", "/simulate/device", { device_id: deviceId }),
  simulateLink: (source, target) => request("POST", "/simulate/link", { source, target }),
  resetSimulation: () => request("POST", "/simulation/reset"),
  compare: (scenarios) => request("POST", "/simulate/compare", { scenarios }),

  scenarios: () => request("GET", "/scenarios"),
  createScenario: (body) => request("POST", "/scenarios", body),
  updateScenario: (id, body) => request("PATCH", `/scenarios/${enc(id)}`, body),
  copyScenario: (id) => request("POST", `/scenarios/${enc(id)}/copy`),
  deleteScenario: (id) => request("DELETE", `/scenarios/${enc(id)}`),
  runScenario: (id) => request("POST", `/scenarios/${enc(id)}/run`),

  device: (id) => request("GET", `/devices/${enc(id)}`),
  createDevice: (body) => request("POST", "/devices", body),
  updateDevice: (id, body) => request("PATCH", `/devices/${enc(id)}`, body),
  deleteDevice: (id) => request("DELETE", `/devices/${enc(id)}`),

  link: (a, b) => request("GET", `/links/${enc(a)}/${enc(b)}`),
  createLink: (body) => request("POST", "/links", body),
  updateLink: (a, b, body) => request("PATCH", `/links/${enc(a)}/${enc(b)}`, body),
  deleteLink: (a, b) => request("DELETE", `/links/${enc(a)}/${enc(b)}`),
};
