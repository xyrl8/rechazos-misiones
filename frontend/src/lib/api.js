// Cliente HTTP del backend de rechazos.
// En dev: rutas relativas /api/* (proxy de Vite -> :8000).
// En prod: VITE_API_URL apunta al alias estable del backend en Vercel.
const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

function qs(params) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.append(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function req(method, path, { params, body } = {}) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}${qs(params)}`, opts);
  if (!resp.ok) {
    let detail = "";
    try {
      const j = await resp.json();
      detail = j.error || j.detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

const get = (path, params) => req("GET", path, { params });

export const api = {
  resumen: (filtros) => get("/api/resumen", filtros),
  rechazos: (filtros) => get("/api/rechazos", filtros),
  filtros: (params) => get("/api/filtros", params),
  syncEstado: () => get("/api/sync/estado"),
  // Sync desde el boton de la UI. `params` = { dias } para la ventana movil
  // reciente, o { desde, hasta } para sincronizar un rango concreto.
  refrescarSync: (params) =>
    req("POST", "/api/sync/refrescar", { params }),
  // Mapeo manual de clientes a supervisores.
  mapeo: () => get("/api/mapeo"),
  guardarMapeo: (cliente, vendedor) =>
    req("POST", "/api/mapeo", { body: { cliente, vendedor } }),
  borrarMapeo: (nombreNorm) =>
    req("DELETE", "/api/mapeo", { params: { nombre_norm: nombreNorm } }),
};
