import { useMemo, useState } from "react";
import { num, dec, moneyCompact, fechaLarga, clienteLabel } from "../lib/format.js";

const TOP_BASE = 10;

// Umbrales relativos a la longitud de la ventana de criticidad.
// Base: 15 días -> crítico 3, recurrente 2. A partir de 30 días se suma 1 a
// cada umbral, y 1 más por cada mes (30 días) adicional. La ventana mínima
// es de 15 días.
function umbrales(periodo) {
  let dias = 15;
  if (periodo?.desde && periodo?.hasta) {
    const ms = new Date(periodo.hasta) - new Date(periodo.desde);
    dias = Math.max(15, Math.round(ms / 86400000));
  }
  const extra = Math.floor(dias / 30); // 15-29d -> 0, 30-59d -> 1, 60-89d -> 2...
  return {
    dias,
    critico: 3 + extra,
    recurrente: 2 + extra,
  };
}

// Nivel de criticidad según cuántos DÍAS distintos rechazó en el período.
function nivelDe(veces, u) {
  if (veces >= u.critico) return { txt: "Crítico", cls: "critico" };
  if (veces >= u.recurrente) return { txt: "Recurrente", cls: "recurrente" };
  return { txt: "Ocasional", cls: "ocasional" };
}

// Texto de la leyenda según los umbrales vigentes.
function textoUmbrales(u) {
  const rec =
    u.recurrente === u.critico - 1
      ? `${u.recurrente}`
      : `${u.recurrente}-${u.critico - 1}`;
  const oca = u.recurrente - 1 <= 1 ? "1" : `1-${u.recurrente - 1}`;
  return `${u.critico}+ crítico · ${rec} recurrente · ${oca} ocasional`;
}

// Ranking de clientes por cantidad de rechazos: el foco de la matinal.
// "Encarar a estos clientes y preguntar por que rechazaron sus pedidos."
export default function ClientesCriticos({ data, periodo, seleccion, onSelect }) {
  const rows = data || [];
  const [mostrarTodos, setMostrarTodos] = useState(false);
  const u = umbrales(periodo);
  const criticos = rows.filter((c) => c.veces >= u.critico).length;
  const recurrentes = rows.filter(
    (c) => c.veces >= u.recurrente && c.veces < u.critico
  ).length;
  // Orden por defecto: de mayor a menor criticidad (días distintos con
  // rechazo), con el importe como desempate.
  const ordenados = useMemo(
    () => [...rows].sort((a, b) => b.veces - a.veces || b.importe - a.importe),
    [rows]
  );
  const visibles = mostrarTodos ? ordenados : ordenados.slice(0, TOP_BASE);

  return (
    <div className="panel wide">
      <h3>
        Clientes críticos
        <span className="count">
          <span className="nivel-tag critico">{criticos} críticos</span>{" "}
          <span className="nivel-tag recurrente">
            {recurrentes} recurrentes
          </span>
        </span>
      </h3>
      <div className="leyenda">
        Ranking por <b>días distintos con rechazo</b>
        {periodo
          ? ` (${fechaLarga(periodo.desde)} → ${fechaLarga(periodo.hasta)},`
          : " ("}
        {" mínimo últimos 15 días)"} · {textoUmbrales(u)}
      </div>
      {rows.length === 0 ? (
        <div className="empty">Sin rechazos en el período</div>
      ) : (
        visibles.map((c, i) => {
          const label = clienteLabel(c.id_cliente, c.cliente);
          const sel = seleccion === label;
          const niv = nivelDe(c.veces, u);
          return (
            <div
              key={`${c.id_cliente}-${c.cliente}`}
              className="cliente-row"
              style={sel ? { background: "var(--danger-soft)" } : undefined}
              onClick={() => onSelect && onSelect(sel ? "" : label)}
              title="Filtrar todo el tablero por este cliente"
            >
              <div className={`rank ${niv.cls}`}>{i + 1}</div>
              <div>
                <div className="cliente-nom">
                  {label}{" "}
                  <span className={`nivel-tag ${niv.cls}`}>{niv.txt}</span>
                </div>
                <div className="cliente-meta">
                  {c.vendedor}
                  {c.localidad ? ` · ${c.localidad}` : ""} · último:{" "}
                  <b>{c.ultimo_motivo}</b> ({fechaLarga(c.ultima_fecha)})
                </div>
              </div>
              <div className="cliente-stat">
                <div className={`big ${niv.cls}`}>{num(c.veces)}</div>
                <div className="small">
                  {c.veces === 1 ? "día con rechazo" : "días con rechazo"}
                </div>
                <div className="small">
                  {dec(c.bultos)} bultos · {moneyCompact(c.importe)}
                </div>
              </div>
            </div>
          );
        })
      )}
      {rows.length > TOP_BASE && (
        <button
          className="btn-ver-mas"
          onClick={() => setMostrarTodos((v) => !v)}
        >
          {mostrarTodos
            ? "Ver menos"
            : `Ver los ${rows.length - TOP_BASE} restantes`}
        </button>
      )}
    </div>
  );
}
