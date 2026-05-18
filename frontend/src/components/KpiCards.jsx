import { num, dec, moneyCompact } from "../lib/format.js";

// Tarjetas de KPI principales del tablero.
export default function KpiCards({ kpis }) {
  if (!kpis) return null;
  const cards = [
    { cls: "", label: "Líneas rechazadas", value: num(kpis.lineas),
      hint: `${num(kpis.comprobantes)} comprobantes` },
    { cls: "b-bultos", label: "Bultos rechazados", value: dec(kpis.bultos),
      hint: "unidades de venta" },
    { cls: "b-importe", label: "Importe rechazado", value: moneyCompact(kpis.importe),
      hint: "neto no facturado" },
    { cls: "b-clientes", label: "Clientes afectados", value: num(kpis.clientes),
      hint: "a encarar en la matinal" },
  ];
  return (
    <div className="kpis">
      {cards.map((c) => (
        <div key={c.label} className={`kpi ${c.cls}`}>
          <div className="label">{c.label}</div>
          <div className="value">{c.value}</div>
          <div className="hint">{c.hint}</div>
        </div>
      ))}
    </div>
  );
}
