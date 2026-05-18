import { useMemo, useState } from "react";
import { num, dec, money, fechaLarga, clienteLabel } from "../lib/format.js";

// Columnas ordenables del detalle. `num` = alineación a la derecha.
const COLS = [
  { key: "fecha", label: "Fecha", num: false },
  { key: "fuente", label: "Fuente", num: false },
  { key: "cliente", label: "Cliente", num: false },
  { key: "vendedor", label: "Promotor", num: false },
  { key: "supervisor", label: "Supervisor", num: false },
  { key: "motivo", label: "Motivo", num: false },
  { key: "sku", label: "SKU", num: true },
  { key: "bultos", label: "Bultos", num: true },
  { key: "importe", label: "Importe", num: true },
];

// Valor por el que se ordena un grupo según la columna.
function valorOrden(g, key) {
  switch (key) {
    case "fecha":
      return g.fecha || "";
    case "fuente":
      return g.fuente || "";
    case "cliente":
      return clienteLabel(g.id_cliente, g.cliente).toLowerCase();
    case "vendedor":
      return (g.vendedor || "").toLowerCase();
    case "supervisor":
      return (g.supervisor || "").toLowerCase();
    case "motivo":
      return g.motivos.size === 1
        ? [...g.motivos][0]
        : `${g.motivos.size} motivos`;
    case "sku":
      return g.lineas.length;
    case "bultos":
      return g.bultos;
    case "importe":
      return g.importe;
    default:
      return 0;
  }
}

// Detalle de rechazos agrupado por fecha + cliente. Cada grupo muestra los
// totales; al desplegarlo se ve el detalle de SKU.
export default function TablaRechazos({ data }) {
  const rows = data?.rows || [];
  const total = data?.total || 0;
  const [abiertos, setAbiertos] = useState(() => new Set());
  const [mostrarTodos, setMostrarTodos] = useState(false);
  const [orden, setOrden] = useState({ campo: "importe", dir: "desc" });

  const grupos = useMemo(() => {
    const map = new Map();
    for (const r of rows) {
      const key = `${r.fecha}|${r.fuente}|${r.id_cliente}|${r.cliente}`;
      if (!map.has(key)) {
        map.set(key, {
          key,
          fecha: r.fecha,
          fuente: r.fuente,
          id_cliente: r.id_cliente,
          cliente: r.cliente,
          vendedor: r.vendedor,
          supervisor: r.supervisor,
          localidad: r.localidad,
          lineas: [],
          bultos: 0,
          importe: 0,
          motivos: new Set(),
        });
      }
      const g = map.get(key);
      g.lineas.push(r);
      g.bultos += Number(r.bultos_rechazados) || 0;
      g.importe += Number(r.importe_rechazado) || 0;
      g.motivos.add(r.motivo);
    }
    return [...map.values()];
  }, [rows]);

  const gruposOrdenados = useMemo(() => {
    const { campo, dir } = orden;
    const mul = dir === "asc" ? 1 : -1;
    return [...grupos].sort((a, b) => {
      const va = valorOrden(a, campo);
      const vb = valorOrden(b, campo);
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      return 0;
    });
  }, [grupos, orden]);

  function ordenarPor(campo) {
    setOrden((o) =>
      o.campo === campo
        ? { campo, dir: o.dir === "asc" ? "desc" : "asc" }
        : { campo, dir: "desc" }
    );
  }

  function toggle(key) {
    setAbiertos((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  return (
    <div className="panel wide">
      <h3>
        Detalle de rechazos
        <span className="count">
          {num(grupos.length)} grupos · {num(rows.length)} de {num(total)} líneas
        </span>
      </h3>
      {grupos.length === 0 ? (
        <div className="empty">Sin rechazos para los filtros seleccionados</div>
      ) : (
        <div className="tabla-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 24 }}></th>
                {COLS.map((c) => {
                  const activo = orden.campo === c.key;
                  return (
                    <th
                      key={c.key}
                      className={`th-sort${c.num ? " num" : ""}${
                        activo ? " activo" : ""
                      }`}
                      onClick={() => ordenarPor(c.key)}
                      title="Ordenar por esta columna"
                    >
                      {c.label}
                      <span className="sort-ind">
                        {activo ? (orden.dir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {(mostrarTodos ? gruposOrdenados : gruposOrdenados.slice(0, 10)).map(
                (g) => {
                  const abierto = abiertos.has(g.key);
                  const motivo =
                    g.motivos.size === 1
                      ? [...g.motivos][0]
                      : `${g.motivos.size} motivos`;
                  return (
                    <GrupoFilas
                      key={g.key}
                      g={g}
                      abierto={abierto}
                      motivo={motivo}
                      onToggle={() => toggle(g.key)}
                    />
                  );
                }
              )}
            </tbody>
          </table>
          {grupos.length > 10 && (
            <button
              className="btn-ver-mas"
              onClick={() => setMostrarTodos((v) => !v)}
            >
              {mostrarTodos
                ? "Ver menos"
                : `Ver los ${grupos.length - 10} grupos restantes`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function GrupoFilas({ g, abierto, motivo, onToggle }) {
  return (
    <>
      <tr className="grupo-row" onClick={onToggle} title="Ver detalle de SKU">
        <td className="caret">{abierto ? "▾" : "▸"}</td>
        <td>{fechaLarga(g.fecha)}</td>
        <td>
          <span className={`tag ${g.fuente}`}>{g.fuente}</span>
        </td>
        <td>
          <b>{clienteLabel(g.id_cliente, g.cliente)}</b>
          {g.localidad ? (
            <div style={{ color: "var(--muted)", fontSize: 11 }}>
              {g.localidad}
            </div>
          ) : null}
        </td>
        <td>{g.vendedor}</td>
        <td>{g.supervisor}</td>
        <td>
          <span className="motivo-tag">{motivo}</span>
        </td>
        <td className="num">{num(g.lineas.length)}</td>
        <td className="num">{dec(g.bultos)}</td>
        <td className="num">
          <b>{money(g.importe)}</b>
        </td>
      </tr>
      {abierto &&
        g.lineas.map((r, i) => (
          <tr key={i} className="det-row">
            <td></td>
            <td colSpan={5} className="det-sku">
              {r.articulo}
              {r.transporte ? (
                <span className="det-extra"> · transporte {r.transporte}</span>
              ) : null}
            </td>
            <td>
              <span className="motivo-tag">{r.motivo}</span>
            </td>
            <td className="num">—</td>
            <td className="num">{dec(r.bultos_rechazados)}</td>
            <td className="num">{money(r.importe_rechazado)}</td>
          </tr>
        ))}
    </>
  );
}
