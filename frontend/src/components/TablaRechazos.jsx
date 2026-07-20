import { useMemo, useState } from "react";
import {
  num,
  dec,
  money,
  fechaLarga,
  clienteLabel,
  threadKey,
  limpiarEtiqueta,
} from "../lib/format.js";
import { umbrales, nivelDe, indiceCriticidad } from "../lib/criticidad.js";

// Columnas ordenables del detalle. `num` = alineación a la derecha.
// `nivel` y `veces` son métricas POR CLIENTE (criticidad), incorporadas desde
// el antiguo panel "Clientes críticos".
// `w` = ancho fijo en px (la tabla usa table-layout: fixed para que las
// columnas no salten al desplegar filas). Las columnas de texto sin `w`
// reparten el espacio restante.
const COLS = [
  { key: "fecha", label: "Fecha", num: false, w: 78 },
  { key: "cliente", label: "Cliente", num: false },
  { key: "vendedor", label: "Promotor", num: false },
  { key: "supervisor", label: "Supervisor", num: false },
  { key: "nivel", label: "Nivel", num: false, w: 96 },
  { key: "veces", label: "Recurr.", num: true, w: 78 },
  { key: "motivo", label: "Motivo", num: false },
  { key: "sku", label: "SKU", num: true, w: 56 },
  { key: "bultos", label: "Bultos", num: true, w: 72 },
  { key: "importe", label: "Importe", num: true, w: 100 },
  { key: "comentarios", label: "Coment.", num: false, w: 112 },
];

// Valor por el que se ordena un grupo según la columna.
function valorOrden(g, key) {
  switch (key) {
    case "fecha":
      return g.fecha || "";
    case "cliente":
      return clienteLabel(g.id_cliente, g.cliente).toLowerCase();
    case "vendedor":
      return (g.vendedor || "").toLowerCase();
    case "supervisor":
      return (g.supervisor || "").toLowerCase();
    case "nivel":
      // Crítico > Recurrente > Ocasional > sin dato; desempata por días.
      return g.nivel.rango * 1000 + (g.veces || 0);
    case "veces":
      return g.veces == null ? -1 : g.veces;
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
    case "comentarios":
      // Pendientes (con comentarios sin resolver) primero, luego resueltos,
      // luego sin comentarios. Desempata por cantidad de comentarios.
      if (!g.hilo || !g.hilo.n_comentarios) return 0;
      return (g.hilo.resuelto ? 1000 : 2000) + Number(g.hilo.n_comentarios);
    default:
      return 0;
  }
}

// Detalle de rechazos agrupado por fecha + cliente, fusionado con la criticidad
// del cliente. Cada grupo muestra los totales del evento + el nivel de
// criticidad del cliente; al desplegarlo se ve el detalle de SKU.
//
// Ventanas: `nivel`/`veces` se calculan sobre la ventana de criticidad
// (mínimo 15 días, llega en `periodoCriticidad`); `bultos`/`importe` son del
// evento, dentro del período del filtro.
export default function TablaRechazos({
  data,
  criticos,
  periodoCriticidad,
  seleccion,
  onSelectCliente,
  hilos,
  onComentar,
}) {
  const rows = data?.rows || [];
  const total = data?.total || 0;
  const [abiertos, setAbiertos] = useState(() => new Set());
  const [mostrarTodos, setMostrarTodos] = useState(false);
  // Por defecto: lo más crítico arriba (es el foco de la matinal).
  const [orden, setOrden] = useState({ campo: "nivel", dir: "desc" });

  // Índice id_cliente -> { veces } y umbrales de la ventana de criticidad.
  const idx = useMemo(() => indiceCriticidad(criticos), [criticos]);
  const u = useMemo(() => umbrales(periodoCriticidad), [periodoCriticidad]);

  const grupos = useMemo(() => {
    const map = new Map();
    for (const r of rows) {
      const key = `${r.fecha}|${r.fuente}|${r.id_cliente}|${r.cliente}`;
      if (!map.has(key)) {
        map.set(key, {
          key,
          thread_key: threadKey(r.fecha, r.fuente, r.id_cliente),
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
    // Criticidad del cliente: días distintos con rechazo en la ventana cc.
    // Y el hilo de comentarios del evento (si existe).
    for (const g of map.values()) {
      const cc = idx.get(String(g.id_cliente ?? ""));
      g.veces = cc ? cc.veces : null;
      g.nivel = nivelDe(g.veces, u);
      g.hilo = (hilos && hilos[g.thread_key]) || null;
    }
    return [...map.values()];
  }, [rows, idx, u, hilos]);

  const gruposOrdenados = useMemo(() => {
    const { campo, dir } = orden;
    const mul = dir === "asc" ? 1 : -1;
    return [...grupos].sort((a, b) => {
      const va = valorOrden(a, campo);
      const vb = valorOrden(b, campo);
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      // Desempate estable: mayor importe primero.
      return b.importe - a.importe;
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
        <span className="h3-titulo">
          {grupos.length > 10 && (
            <button
              type="button"
              className="btn-toggle-todos"
              onClick={() => setMostrarTodos((v) => !v)}
              title={
                mostrarTodos
                  ? "Mostrar solo los primeros grupos"
                  : `Mostrar los ${grupos.length} grupos`
              }
            >
              {mostrarTodos ? "▾" : "▸"}
            </button>
          )}
          Detalle de rechazos
        </span>
        <span className="count">
          {num(grupos.length)} grupos · {num(rows.length)} de {num(total)} líneas
        </span>
      </h3>
      <div className="leyenda">
        <b>Nivel</b> y <b>recurrencia</b> son del cliente sobre la ventana de
        criticidad (mínimo últimos 15 días); <b>bultos</b> e <b>importe</b> son
        del evento, dentro del período filtrado. Clic en el cliente para filtrar
        todo el tablero.
      </div>
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
                      style={c.w ? { width: c.w } : undefined}
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
                  const label = clienteLabel(g.id_cliente, g.cliente);
                  return (
                    <GrupoFilas
                      key={g.key}
                      g={g}
                      abierto={abierto}
                      motivo={motivo}
                      seleccionado={seleccion === label}
                      onToggle={() => toggle(g.key)}
                      onCliente={() =>
                        onSelectCliente &&
                        onSelectCliente(seleccion === label ? "" : label)
                      }
                      onComentar={() => onComentar && onComentar(g)}
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

function GrupoFilas({
  g,
  abierto,
  motivo,
  seleccionado,
  onToggle,
  onCliente,
  onComentar,
}) {
  const hilo = g.hilo;
  const n = hilo ? Number(hilo.n_comentarios) || 0 : 0;
  return (
    <>
      <tr
        className={`grupo-row${seleccionado ? " sel" : ""}`}
        onClick={onToggle}
        title="Ver detalle de SKU"
      >
        <td className="caret">{abierto ? "▾" : "▸"}</td>
        <td>{fechaLarga(g.fecha)}</td>
        <td>
          <button
            type="button"
            className="cliente-link"
            onClick={(e) => {
              e.stopPropagation();
              onCliente();
            }}
            title={
              seleccionado
                ? "Quitar el filtro de este cliente"
                : "Filtrar todo el tablero por este cliente"
            }
          >
            {clienteLabel(g.id_cliente, g.cliente)}
          </button>
          {g.localidad ? (
            <div style={{ color: "var(--muted)", fontSize: 11 }}>
              {g.localidad}
            </div>
          ) : null}
        </td>
        <td>{limpiarEtiqueta(g.vendedor)}</td>
        <td>{limpiarEtiqueta(g.supervisor)}</td>
        <td>
          <span className={`nivel-tag ${g.nivel.cls}`}>{g.nivel.txt}</span>
        </td>
        <td className="num">{g.veces == null ? "—" : `${num(g.veces)} d`}</td>
        <td>
          <span className="motivo-tag">{motivo}</span>
        </td>
        <td className="num">{num(g.lineas.length)}</td>
        <td className="num">{dec(g.bultos)}</td>
        <td className="num">
          <b>{money(g.importe)}</b>
        </td>
        <td className="coment-cell">
          <button
            type="button"
            className={`btn-coment${n ? " tiene" : ""}${
              hilo?.resuelto ? " resuelto" : ""
            }`}
            onClick={(e) => {
              e.stopPropagation();
              onComentar();
            }}
            title={
              n
                ? hilo?.resuelto
                  ? `Hilo resuelto · ${n} comentario(s)`
                  : `${n} comentario(s) — clic para ver el hilo`
                : "Agregar un comentario"
            }
          >
            {n ? (
              <>
                {hilo?.resuelto ? "✓" : "💬"} {num(n)}
              </>
            ) : (
              "+ Comentar"
            )}
          </button>
        </td>
      </tr>
      {abierto &&
        g.lineas.map((r, i) => (
          <tr key={i} className="det-row">
            <td></td>
            <td colSpan={6} className="det-sku">
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
            <td></td>
          </tr>
        ))}
    </>
  );
}
