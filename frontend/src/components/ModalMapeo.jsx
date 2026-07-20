import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { num } from "../lib/format.js";

// Apartado de administración: mapear clientes de GESCOM a un promotor de Chess.
// Los clientes de GESCOM que no matchean automáticamente quedan como mostrador
// y se excluyen; asignarles un promotor real los reincorpora al tablero
// (y heredan el supervisor de ese promotor).
export default function ModalMapeo({ onClose, onChange }) {
  const [data, setData] = useState(null);
  const [cliente, setCliente] = useState("");
  const [vendedor, setVendedor] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargar = () => {
    api
      .mapeo()
      .then(setData)
      .catch((e) => setError(e.message));
  };
  useEffect(cargar, []);

  async function guardar() {
    setError("");
    setMsg("");
    if (!cliente.trim() || !vendedor) {
      setError("Elegí un cliente y un promotor.");
      return;
    }
    setGuardando(true);
    try {
      const r = await api.guardarMapeo(cliente.trim(), vendedor);
      setMsg(
        `Mapeo guardado · supervisor: ${r.supervisor || "—"} · ${num(
          r.filas_actualizadas
        )} rechazos reincorporados.`
      );
      setCliente("");
      setVendedor("");
      cargar();
      onChange && onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(nombreNorm) {
    setError("");
    setMsg("");
    try {
      await api.borrarMapeo(nombreNorm);
      cargar();
      onChange && onChange();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Mapeo de clientes a promotores</h2>
          <button className="modal-x" onClick={onClose}>
            ✕
          </button>
        </div>

        {!data ? (
          <div className="loading">
            <div className="spinner" />
            Cargando…
          </div>
        ) : (
          <div className="modal-body">
            <p className="leyenda">
              Los clientes de mostrador que no matchean con un promotor quedan
              excluidos del tablero. Asignándoles un promotor real se
              reincorporan, y heredan el supervisor de ese promotor.
            </p>

            {/* --- Formulario --- */}
            <div className="mapeo-form">
              <div className="field" style={{ flex: 2 }}>
                <label>Cliente</label>
                <input
                  list="clientes-sin-resolver"
                  value={cliente}
                  placeholder="Nombre del cliente"
                  onChange={(e) => setCliente(e.target.value)}
                />
                <datalist id="clientes-sin-resolver">
                  {data.sin_resolver.map((c) => (
                    <option key={c.cliente} value={c.cliente} />
                  ))}
                </datalist>
              </div>
              <div className="field">
                <label>Promotor</label>
                <select
                  value={vendedor}
                  onChange={(e) => setVendedor(e.target.value)}
                >
                  <option value="">Elegir…</option>
                  {data.promotores.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>&nbsp;</label>
                <button
                  className="btn-primary"
                  onClick={guardar}
                  disabled={guardando}
                >
                  {guardando ? "Guardando…" : "Guardar mapeo"}
                </button>
              </div>
            </div>

            {error && <div className="banner err">{error}</div>}
            {msg && <div className="banner">{msg}</div>}

            {/* --- Clientes de mostrador sin resolver --- */}
            <h3 className="modal-sub">
              Clientes de mostrador sin resolver
              <span className="count">{data.sin_resolver.length}</span>
            </h3>
            {data.sin_resolver.length === 0 ? (
              <div className="empty">
                No hay clientes de mostrador sin resolver 🎉
              </div>
            ) : (
              <div className="chips">
                {data.sin_resolver.map((c) => (
                  <button
                    key={c.cliente}
                    className={`chip ${cliente === c.cliente ? "sel" : ""}`}
                    onClick={() => setCliente(c.cliente)}
                    title="Usar este cliente en el formulario"
                  >
                    {c.cliente} <b>· {c.lineas}</b>
                  </button>
                ))}
              </div>
            )}

            {/* --- Mapeos cargados --- */}
            <h3 className="modal-sub">
              Mapeos cargados
              <span className="count">{data.mapeos.length}</span>
            </h3>
            {data.mapeos.length === 0 ? (
              <div className="empty">Todavía no hay mapeos manuales.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Cliente</th>
                    <th>Promotor</th>
                    <th>Supervisor</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.mapeos.map((m) => (
                    <tr key={m.nombre_norm}>
                      <td>
                        <b>{m.cliente}</b>
                      </td>
                      <td>{m.vendedor || "—"}</td>
                      <td>{m.supervisor || "—"}</td>
                      <td className="num">
                        <button
                          className="btn-del"
                          onClick={() => borrar(m.nombre_norm)}
                        >
                          Eliminar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
