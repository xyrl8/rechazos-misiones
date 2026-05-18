import { Fragment } from "react";
import { num, dec, moneyCompact } from "../lib/format.js";

const pct = (parte, total) => (total ? Math.round((parte / total) * 100) : 0);

// Mayor importe rechazado primero; bultos como desempate.
const porImporte = (a, b) => b.importe - a.importe || b.bultos - a.bultos;

// Dos filas alineadas por el "|": bultos|importe y %|% sobre el total.
const hintGridDe = (item, kpis) => [
  [`${dec(item.bultos)} bultos`, moneyCompact(item.importe)],
  [`${pct(item.bultos, kpis.bultos)}%`, `${pct(item.importe, kpis.importe)}%`],
];

// Tarjetas de KPI principales del tablero.
export default function KpiCards({ kpis, porMotivo, porLocalidad }) {
  if (!kpis) return null;
  // Principal motivo y localidad crítica = el de mayor importe rechazado
  // (coherente con el dato que muestra cada tarjeta).
  const top = [...(porMotivo || [])].sort(porImporte)[0];
  const topLoc = [...(porLocalidad || [])]
    .filter((l) => l.clave && String(l.clave).trim())
    .sort(porImporte)[0];
  const cards = [
    { cls: "b-motivo", label: "Principal motivo",
      value: top ? top.clave : "—",
      hintGrid: top ? hintGridDe(top, kpis) : null,
      hint: top ? null : "sin rechazos" },
    { cls: "b-localidad", label: "Localidad crítica",
      value: topLoc ? topLoc.clave : "—",
      hintGrid: topLoc ? hintGridDe(topLoc, kpis) : null,
      hint: topLoc ? null : "sin datos" },
    { cls: "b-bultos", label: "Bultos rechazados", value: dec(kpis.bultos),
      hint: "unidades de venta" },
    { cls: "b-importe", label: "Importe rechazado", value: moneyCompact(kpis.importe),
      hint: "neto no facturado" },
    { cls: "b-clientes", label: "Clientes con rechazo", value: num(kpis.clientes),
      hint: "distintos en el período" },
  ];
  return (
    <div className="kpis">
      {cards.map((c) => (
        <div key={c.label} className={`kpi ${c.cls}`}>
          <div className="label">{c.label}</div>
          <div className="value">{c.value}</div>
          {c.hintGrid && (
            <div className="hint hint-grid">
              {c.hintGrid.map(([izq, der], i) => (
                <Fragment key={i}>
                  <span className={i === 0 ? "hg-izq first" : "hg-izq"}>
                    {izq}
                  </span>
                  <span className="hg-sep">|</span>
                  <span className="hg-der">{der}</span>
                </Fragment>
              ))}
            </div>
          )}
          {c.hint && <div className="hint">{c.hint}</div>}
        </div>
      ))}
    </div>
  );
}
