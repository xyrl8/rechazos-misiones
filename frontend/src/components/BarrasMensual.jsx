import { useMemo, useState } from "react";

// Gráfico de barras verticales por mes, con apilado opcional por segmento.
// SVG propio: el proyecto no usa librerías de gráficos (misma línea que el
// resto del frontend, CSS a mano).
//
// Cada mes es { mes: "2026-01", total: 123, partes: [{clave, valor, color}] }.
// `partes` vacío = barra simple de una sola serie.

const MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];

export function etiquetaMes(iso, conAnio = false) {
  const [y, m] = String(iso).split("-");
  const et = MES_CORTO[Number(m) - 1] || iso;
  return conAnio ? `${et} ${y.slice(2)}` : et;
}

// Escala "linda": el tope del eje se redondea al siguiente 1/2/5 × 10^n para
// que las líneas de grilla caigan en números legibles.
function topeLindo(max) {
  if (!(max > 0)) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(max)));
  const norm = max / exp;
  const paso = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return paso * exp;
}

// Rectángulo con las esquinas superiores redondeadas (el extremo del dato).
function barra(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, h, w / 2));
  return `M${x},${y + h} L${x},${y + rr} Q${x},${y} ${x + rr},${y} `
       + `L${x + w - rr},${y} Q${x + w},${y} ${x + w},${y + rr} `
       + `L${x + w},${y + h} Z`;
}

export default function BarrasMensual({
  data,            // [{ mes, total, partes }]
  formato,         // (v) => string, para tooltip y etiquetas
  formatoEje,      // (v) => string, opcional (default = formato)
  color = "#2a78d6",
  etiquetasArriba = true,
  alto = 260,
  vacio = "Sin datos en el período",
}) {
  const [hover, setHover] = useState(null);
  const fmtEje = formatoEje || formato;

  const W = 900;
  const H = alto;
  const M = { top: 26, right: 12, bottom: 30, left: 62 };
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  const { tope, ticks } = useMemo(() => {
    const max = Math.max(0, ...(data || []).map((d) => d.total || 0));
    const t = topeLindo(max);
    return { tope: t, ticks: [0, 0.25, 0.5, 0.75, 1].map((f) => t * f) };
  }, [data]);

  if (!data || !data.length) return <div className="chart-vacio">{vacio}</div>;

  const paso = innerW / data.length;
  // Barra fina: ocupa como mucho el 55% del paso y nunca más de 46px.
  const ancho = Math.min(46, paso * 0.55);
  const y = (v) => M.top + innerH - (innerH * (v || 0)) / tope;

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img">
        {/* Grilla recesiva + eje Y */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)}
                  className={i === 0 ? "cx-base" : "cx-grid"} />
            <text x={M.left - 8} y={y(t) + 4} className="cx-tick" textAnchor="end">
              {fmtEje(t)}
            </text>
          </g>
        ))}

        {data.map((d, i) => {
          const x = M.left + paso * i + (paso - ancho) / 2;
          const activo = hover && hover.mes === d.mes;
          const partes = d.partes && d.partes.length
            ? d.partes.filter((p) => (p.valor || 0) > 0)
            : [{ clave: null, valor: d.total, color }];
          // Se apila de abajo hacia arriba; 2px de aire entre segmentos.
          let acum = 0;
          const marcas = partes.map((p, j) => {
            const y0 = y(acum);
            const y1 = y(acum + p.valor);
            acum += p.valor;
            const h = Math.max(1, y0 - y1 - (j < partes.length - 1 ? 2 : 0));
            const ultimo = j === partes.length - 1;
            return { ...p, x, y: y1, h, redondeo: ultimo ? 4 : 0, key: `${d.mes}-${j}` };
          });
          return (
            <g key={d.mes}
               onMouseEnter={() => setHover(d)}
               onMouseLeave={() => setHover(null)}>
              {/* Zona de hover más grande que la barra */}
              <rect x={M.left + paso * i} y={M.top} width={paso} height={innerH}
                    className={activo ? "cx-hit activo" : "cx-hit"} />
              {marcas.map((m) => (
                <path key={m.key} d={barra(m.x, m.y, ancho, m.h, m.redondeo)}
                      fill={m.color} className="cx-barra" />
              ))}
              {etiquetasArriba && d.total > 0 && (
                <text x={x + ancho / 2} y={y(d.total) - 7}
                      className="cx-valor" textAnchor="middle">
                  {formato(d.total)}
                </text>
              )}
              <text x={M.left + paso * i + paso / 2} y={H - 10}
                    className="cx-mes" textAnchor="middle">
                {etiquetaMes(d.mes)}
              </text>
            </g>
          );
        })}
      </svg>

      {hover && (
        <div className="chart-tip">
          <div className="tip-tit">{etiquetaMes(hover.mes, true)}</div>
          <div className="tip-total">{formato(hover.total)}</div>
          {(hover.partes || [])
            .filter((p) => (p.valor || 0) > 0)
            .slice()
            .reverse()
            .map((p) => (
              <div key={p.clave} className="tip-fila">
                <span className="tip-punto" style={{ background: p.color }} />
                <span className="tip-cla">{p.clave}</span>
                <span className="tip-val">{formato(p.valor)}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
