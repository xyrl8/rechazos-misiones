import { useMemo, useState } from "react";
import { num, dec, moneyCompact } from "../lib/format.js";

// Panel de barras horizontales para un corte (supervisor, promotor, motivo...).
// Cada barra es clickeable y aplica/quita el filtro correspondiente.
// El encabezado permite ordenar por valor o por nombre, asc/desc.
export default function PanelSegmento({
  titulo,
  data,
  metrica = "bultos", // "importe" | "lineas" | "bultos"
  seleccion,
  onSelect,
}) {
  const rows = data || [];
  const [orden, setOrden] = useState({ campo: "valor", dir: "desc" });
  const max = Math.max(1, ...rows.map((r) => Number(r[metrica]) || 0));
  const fmt =
    metrica === "importe" ? moneyCompact : metrica === "bultos" ? dec : num;

  const ordenadas = useMemo(() => {
    const mul = orden.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (orden.campo === "clave") {
        return String(a.clave).localeCompare(String(b.clave)) * mul;
      }
      return ((Number(a[metrica]) || 0) - (Number(b[metrica]) || 0)) * mul;
    });
  }, [rows, orden, metrica]);

  function ordenarPor(campo) {
    setOrden((o) =>
      o.campo === campo
        ? { campo, dir: o.dir === "asc" ? "desc" : "asc" }
        : { campo, dir: campo === "clave" ? "asc" : "desc" }
    );
  }

  const ind = (campo) =>
    orden.campo === campo ? (orden.dir === "asc" ? "▲" : "▼") : "↕";

  return (
    <div className="panel">
      <h3>
        {titulo}
        <span className="seg-head">
          <span className="seg-orden">
            <button
              className={`seg-sort${orden.campo === "valor" ? " activo" : ""}`}
              onClick={() => ordenarPor("valor")}
              title="Ordenar por valor"
            >
              valor <span className="sort-ind">{ind("valor")}</span>
            </button>
            <button
              className={`seg-sort${orden.campo === "clave" ? " activo" : ""}`}
              onClick={() => ordenarPor("clave")}
              title="Ordenar por nombre"
            >
              nombre <span className="sort-ind">{ind("clave")}</span>
            </button>
          </span>
          <span className="count">{rows.length}</span>
        </span>
      </h3>
      {rows.length === 0 ? (
        <div className="empty">Sin rechazos en el período</div>
      ) : (
        <div className="bars">
          {ordenadas.map((r) => {
            const v = Number(r[metrica]) || 0;
            const sel = seleccion === r.clave;
            return (
              <div
                key={r.clave}
                className={`bar-row ${sel ? "sel" : ""}`}
                onClick={() => onSelect && onSelect(sel ? "" : r.clave)}
                title={`${r.clave}\n${dec(r.bultos)} bultos · ${num(
                  r.clientes
                )} clientes · ${moneyCompact(r.importe)}`}
              >
                <div className="bar-label">{r.clave}</div>
                <div className="bar-val">{fmt(v)}</div>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${(v / max) * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
