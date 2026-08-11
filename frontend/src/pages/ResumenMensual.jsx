import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api.js";
import { dec, num, money, moneyCompact, limpiarEtiqueta, hoyISO } from "../lib/format.js";
import BarrasMensual, { etiquetaMes } from "../components/BarrasMensual.jsx";

// Solapa 2: cómo viene el rechazo mes a mes. La solapa 1 es el detalle
// operativo (qué cliente rechazó y por qué); acá el foco es la evolución y el
// peso de cada motivo sobre la venta del período.

// Unidades en las que se puede leer el rechazo. `pct` es el % sobre la venta
// del mismo corte (denominador = tabla ventas_dia).
const UNIDADES = [
  { key: "bultos", label: "Bultos", fmt: (v) => dec(v), fmtEje: (v) => num(v) },
  { key: "hl", label: "Hectolitros", fmt: (v) => dec(v) + " HL", fmtEje: (v) => num(v) },
  { key: "importe", label: "Valorizado", fmt: (v) => moneyCompact(v), fmtEje: (v) => moneyCompact(v) },
];

// Paleta categórica validada para fondo claro (ΔE CVD adyacente 9.1; los
// motivos van SIEMPRE etiquetados en la leyenda y la tabla, nunca solo color).
const COLORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const COLOR_OTROS = "#98a1b3";
const TOP_MOTIVOS = 6;

// Denominador del %. `reparto` es el criterio del PBI oficial de Quilmes: mide
// contra lo que salió en CAMIÓN PROPIO. `total` es toda la venta facturada
// (incluye mostrador, retiro y fleteros) y da un % ~3 veces menor: sirve para
// leer el peso del rechazo sobre el negocio, NO para comparar con el PBI.
const DENOMINADORES = [
  { key: "reparto", label: "Reparto en camión", sub: "criterio PBI Quilmes",
    hint: "repartidos en camión" },
  { key: "total", label: "Venta total facturada", sub: "incluye mostrador y retiro",
    hint: "vendidos" },
];

// Switch VENTAS / DISTRIBUCIÓN del PBI: no cambia la dimensión, cambia QUÉ
// MOTIVOS entran. El objetivo de 1,29 % se mide contra la vista de ventas.
const VISTAS = [
  { key: "todos", label: "Todos" },
  { key: "ventas", label: "Ventas", sub: "imputable a preventa" },
  { key: "distribucion", label: "Distribución", sub: "no imputable a preventa" },
];

const pctTxt = (v) =>
  v === null || v === undefined
    ? "—"
    : new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2,
                                       maximumFractionDigits: 2 }).format(v) + " %";

const anioActual = new Date().getFullYear();

export default function ResumenMensual() {
  const [filtros, setFiltros] = useState({
    fuente: "TODO",
    fecha_desde: `${anioActual}-01-01`,
    fecha_hasta: hoyISO(),
    supervisor: "",
    vendedor: "",
    motivo: "",
    denominador: "reparto",
    vista: "todos",
  });
  const [unidad, setUnidad] = useState("hl");
  const [data, setData] = useState(null);
  const [opciones, setOpciones] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const U = UNIDADES.find((u) => u.key === unidad) || UNIDADES[0];
  const D = DENOMINADORES.find((d) => d.key === filtros.denominador) || DENOMINADORES[0];
  const setCampo = (campo, valor) => setFiltros((f) => ({ ...f, [campo]: valor }));

  // Las dos columnas de venta viajan siempre; el sufijo elige cuál se muestra
  // (el % ya viene calculado con el denominador pedido).
  const sufDen = D.key === "reparto" ? "_reparto" : "";
  const venta = (fila, u = unidad) => fila?.[`venta_${u}${sufDen}`];

  // El objetivo del PBI (1,29 %) está definido en HECTOLITROS y contra el
  // reparto: dibujarlo sobre otra unidad o sobre la venta total sería comparar
  // contra una vara que no es la suya.
  const objetivo = D.key === "reparto" && unidad === "hl" ? data?.objetivo_pct || null : null;

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setError("");
    api
      .mensual(filtros)
      .then((r) => !cancel && setData(r))
      .catch((e) => !cancel && setError(e.message))
      .finally(() => !cancel && setLoading(false));
    return () => { cancel = true; };
  }, [filtros]);

  useEffect(() => {
    let cancel = false;
    api
      .filtros({ fuente: filtros.fuente, fecha_desde: filtros.fecha_desde,
                 fecha_hasta: filtros.fecha_hasta })
      .then((o) => !cancel && setOpciones(o))
      .catch(() => !cancel && setOpciones({}));
    return () => { cancel = true; };
  }, [filtros.fuente, filtros.fecha_desde, filtros.fecha_hasta]);

  // Motivos ordenados por la unidad que se está mirando: el backend los manda
  // por importe, pero el ranking tiene que seguir la columna que se lee.
  const motivosOrden = useMemo(
    () => [...(data?.por_motivo || [])].sort(
      (a, b) => (Number(b[unidad]) || 0) - (Number(a[unidad]) || 0)),
    [data, unidad]
  );

  // Motivos que se dibujan con color propio: los TOP por peso en el período.
  // El resto se agrupa en "Otros" (nunca se generan colores nuevos).
  const colorMotivo = useMemo(() => {
    const mapa = new Map();
    motivosOrden.slice(0, TOP_MOTIVOS).forEach((m, i) => mapa.set(m.motivo, COLORES[i]));
    return mapa;
  }, [motivosOrden]);

  // Serie del gráfico de volumen: un mes = una barra apilada por motivo.
  const serieVolumen = useMemo(() => {
    if (!data) return [];
    const porMes = new Map();
    (data.motivos_mes || []).forEach((r) => {
      const v = Number(r[unidad]) || 0;
      if (!v) return;
      const clave = colorMotivo.has(r.motivo) ? r.motivo : "OTROS MOTIVOS";
      const m = porMes.get(r.mes) || new Map();
      m.set(clave, (m.get(clave) || 0) + v);
      porMes.set(r.mes, m);
    });
    return (data.meses || []).map((mes) => {
      const m = porMes.get(mes.mes) || new Map();
      const partes = [...m.entries()]
        .map(([clave, valor]) => ({
          clave, valor,
          color: colorMotivo.get(clave) || COLOR_OTROS,
          orden: colorMotivo.has(clave) ? [...colorMotivo.keys()].indexOf(clave) : 99,
        }))
        .sort((a, b) => a.orden - b.orden);
      return {
        mes: mes.mes,
        total: partes.reduce((s, p) => s + p.valor, 0),
        partes,
      };
    });
  }, [data, unidad, colorMotivo]);

  // Serie del gráfico de %: una sola barra por mes (sin apilar). Los meses con
  // la venta cargada a medias van atenuados: su % está sobreestimado.
  const seriePct = useMemo(
    () => (data?.meses || [])
      .filter((m) => m[`pct_${unidad}`] !== null && m[`pct_${unidad}`] !== undefined)
      .map((m) => ({ mes: m.mes, total: m[`pct_${unidad}`], partes: [],
                     color: m.parcial ? "#a8c2ea" : "#2a78d6" })),
    [data, unidad]
  );

  const k = data?.kpis;
  const sinVenta = !!data && !Number(venta(k, "bultos")) && !Number(venta(k, "importe"));
  const parciales = (data?.meses || []).filter((m) => m.parcial);
  // El corte por camión se completa al re-sincronizar la venta: hasta que eso
  // corra para un período, ese denominador está vacío y el % no se puede
  // mostrar. Se distingue de "no hubo reparto" con la cobertura del backend.
  const sinReparto = D.key === "reparto" && !!data && !Number(data.cobertura_venta?.filas_reparto);

  return (
    <>
      {/* ---------- Filtros propios de la solapa ----------
           Sin selector de fuente: el tablero unifica preventa y mostrador bajo
           una sola lectura (la solapa 1 tampoco lo muestra, y `limpiarEtiqueta`
           saca la palabra GESCOM de los textos visibles). `filtros.fuente`
           queda fijo en "TODO". */}
      <div className="filtros">
        <div className="field">
          <label>Desde</label>
          <input type="date" value={filtros.fecha_desde}
                 onChange={(e) => setCampo("fecha_desde", e.target.value)} />
        </div>
        <div className="field">
          <label>Hasta</label>
          <input type="date" value={filtros.fecha_hasta}
                 onChange={(e) => setCampo("fecha_hasta", e.target.value)} />
        </div>
        <div className="field">
          <label>Período</label>
          <div className="quick">
            {[anioActual, anioActual - 1].map((a) => (
              <button key={a}
                      className={filtros.fecha_desde === `${a}-01-01` ? "activo" : ""}
                      onClick={() =>
                        setFiltros((f) => ({
                          ...f,
                          fecha_desde: `${a}-01-01`,
                          fecha_hasta: a === anioActual ? hoyISO() : `${a}-12-31`,
                        }))
                      }>
                Año {a}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>Supervisor</label>
          <select value={filtros.supervisor}
                  onChange={(e) => setCampo("supervisor", e.target.value)}>
            <option value="">Todos</option>
            {(opciones.supervisor || []).map((s) => (
              <option key={s} value={s}>{limpiarEtiqueta(s)}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Promotor</label>
          <select value={filtros.vendedor}
                  onChange={(e) => setCampo("vendedor", e.target.value)}>
            <option value="">Todos</option>
            {(opciones.vendedor || []).map((s) => (
              <option key={s} value={s}>{limpiarEtiqueta(s)}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Motivo</label>
          <select value={filtros.motivo}
                  onChange={(e) => setCampo("motivo", e.target.value)}>
            <option value="">Todos los motivos</option>
            {(opciones.motivo || []).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>% calculado sobre</label>
          <div className="toggle">
            {DENOMINADORES.map((d) => (
              <button key={d.key}
                      className={filtros.denominador === d.key ? "active" : ""}
                      data-f={filtros.denominador === d.key ? "TODO" : ""}
                      title={d.sub}
                      onClick={() => setCampo("denominador", d.key)}>
                {d.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>Motivos</label>
          <div className="toggle">
            {VISTAS.map((v) => (
              <button key={v.key}
                      className={filtros.vista === v.key ? "active" : ""}
                      data-f={filtros.vista === v.key ? "TODO" : ""}
                      title={v.sub}
                      onClick={() => setCampo("vista", v.key)}>
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>Unidad</label>
          <div className="toggle">
            {UNIDADES.map((u) => (
              <button key={u.key}
                      className={unidad === u.key ? "active" : ""}
                      data-f={unidad === u.key ? "TODO" : ""}
                      onClick={() => setUnidad(u.key)}>
                {u.label}
              </button>
            ))}
          </div>
        </div>

        {(filtros.supervisor || filtros.vendedor || filtros.motivo) && (
          <button className="btn-clear"
                  onClick={() => setFiltros((f) => ({ ...f, supervisor: "", vendedor: "", motivo: "" }))}>
            Limpiar
          </button>
        )}
      </div>

      {error && <div className="banner err">No se pudo cargar el resumen: {error}</div>}

      {sinReparto && !loading ? (
        <div className="banner warn">
          Todavía no está cargado el <b>reparto en camión</b> como denominador:
          se completa re-sincronizando la venta del período
          (<code>POST /api/sync/ventas</code>). Mientras tanto se puede leer el %
          sobre la venta total facturada.
        </div>
      ) : sinVenta && !loading && (
        <div className="banner warn">
          No hay {D.key === "reparto" ? "reparto en camión" : "venta"} cargado para
          este período, así que el <b>%</b> no se puede calcular (sí los volúmenes).
          La venta se completa sincronizando el período desde la solapa de seguimiento.
        </div>
      )}

      {D.key === "reparto" && !loading && !sinReparto && (
        <div className="banner info">
          El <b>%</b> se mide contra los hectolitros que salieron en <b>camión
          propio</b>, igual que el PBI de Quilmes: quedan afuera mostrador, retiro,
          fleteros, refuerzos y segundas vueltas de refuerzo. Con la venta total
          facturada el mismo rechazo da un % unas tres veces menor.
        </div>
      )}

      {!!parciales.length && !loading && (
        <div className="banner warn">
          Venta cargada a medias en {parciales.map((m) => etiquetaMes(m.mes, true)).join(", ")}:
          ahí el <b>%</b> queda sobreestimado (el rechazo del mes completo se compara
          contra una parte de la venta). Esos meses van atenuados en el gráfico.
        </div>
      )}

      {loading && !data ? (
        <div className="loading"><div className="spinner" />Cargando resumen…</div>
      ) : data ? (
        <>
          {/* ---------- KPIs del período ---------- */}
          <div className="kpis kpis-4">
            <div className="kpi b-pct">
              <div className="label">% de rechazo · {U.label}</div>
              <div className="value">{pctTxt(k[`pct_${unidad}`])}</div>
              <div className="hint">
                {U.fmt(k[unidad])} sobre {U.fmt(venta(k))} {D.hint}
                {objetivo ? ` · objetivo ${pctTxt(objetivo)}` : ""}
              </div>
            </div>
            <div className="kpi b-bultos">
              <div className="label">Bultos rechazados</div>
              <div className="value">{dec(k.bultos)}</div>
              <div className="hint">{pctTxt(k.pct_bultos)} de lo {D.hint}</div>
            </div>
            <div className="kpi b-hl">
              <div className="label">Hectolitros rechazados</div>
              <div className="value">{dec(k.hl)}</div>
              <div className="hint">{pctTxt(k.pct_hl)} de lo {D.hint}</div>
            </div>
            <div className="kpi b-importe">
              <div className="label">Valorizado rechazado</div>
              <div className="value">{moneyCompact(k.importe)}</div>
              <div className="hint">{pctTxt(k.pct_importe)} de lo {D.hint}</div>
            </div>
          </div>

          {/* ---------- % de rechazo por mes ---------- */}
          <div className="panel">
            <div className="panel-head">
              <h2>% de rechazo por mes · {U.label}</h2>
              <span className="panel-sub">
                rechazo ÷ {D.key === "reparto" ? "lo despachado en camión propio" : "venta total"} del mismo mes
                {filtros.vista !== "todos" ? ` · motivos de ${filtros.vista}` : ""}
                {filtros.motivo ? ` · sólo motivo ${filtros.motivo}` : ""}
              </span>
            </div>
            <BarrasMensual
              data={seriePct}
              color="#2a78d6"
              formato={(v) => pctTxt(v)}
              formatoEje={(v) =>
                new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(v) + "%"}
              objetivo={objetivo}
              objetivoTexto={`objetivo ${pctTxt(objetivo)} (PBI)`}
              vacio={D.key === "reparto"
                ? "Sin reparto en camión cargado en el período: el % necesita denominador."
                : "Sin venta cargada en el período: el % necesita denominador."}
            />
          </div>

          {/* ---------- Volumen rechazado por mes y motivo ---------- */}
          <div className="panel">
            <div className="panel-head">
              <h2>Rechazo por mes y motivo · {U.label}</h2>
              <span className="panel-sub">
                {filtros.motivo
                  ? `filtrado por motivo ${filtros.motivo}`
                  : `los ${TOP_MOTIVOS} motivos de mayor peso; el resto agrupado`}
              </span>
            </div>
            <div className="leyenda">
              {[...colorMotivo.entries()].map(([m, c]) => (
                <button key={m}
                        className={filtros.motivo === m ? "leg on" : "leg"}
                        onClick={() => setCampo("motivo", filtros.motivo === m ? "" : m)}>
                  <span className="leg-punto" style={{ background: c }} />
                  {m}
                </button>
              ))}
              {motivosOrden.length > TOP_MOTIVOS && (
                <span className="leg estatico">
                  <span className="leg-punto" style={{ background: COLOR_OTROS }} />
                  OTROS MOTIVOS
                </span>
              )}
            </div>
            <BarrasMensual
              data={serieVolumen}
              formato={U.fmt}
              formatoEje={U.fmtEje}
              etiquetasArriba={false}
            />
          </div>

          {/* ---------- Tabla mensual ---------- */}
          <div className="panel">
            <div className="panel-head">
              <h2>Detalle mensual</h2>
              <span className="panel-sub">
                {D.key === "reparto"
                  ? "denominador: HL despachados en camión propio (criterio PBI)"
                  : "denominador: venta bruta facturada"}
              </span>
            </div>
            <div className="tabla-scroll">
              <table className="tabla-mensual">
                <thead>
                  <tr>
                    <th>Mes</th>
                    <th className="n">Bultos rech.</th>
                    <th className="n">% bultos</th>
                    <th className="n">HL rech.</th>
                    <th className="n">% HL</th>
                    <th className="n">Valorizado</th>
                    <th className="n">% valor</th>
                    <th className="n">Clientes</th>
                  </tr>
                </thead>
                <tbody>
                  {data.meses.map((m) => {
                    // Mes con la venta a medias: el % se muestra atenuado y
                    // dice cuántos días de venta tiene cargados.
                    const cls = m.parcial ? "n destac parcial" : "n destac";
                    const tit = m.parcial
                      ? `Sobreestimado: solo ${m.dias_venta} día(s) de venta cargados`
                      : undefined;
                    return (
                      <tr key={m.mes}>
                        <td className="mes">{etiquetaMes(m.mes, true)}</td>
                        <td className="n">{dec(m.bultos)}</td>
                        <td className={cls} title={tit}>{pctTxt(m.pct_bultos)}</td>
                        <td className="n">{dec(m.hl)}</td>
                        <td className={cls} title={tit}>{pctTxt(m.pct_hl)}</td>
                        <td className="n">{money(m.importe)}</td>
                        <td className={cls} title={tit}>{pctTxt(m.pct_importe)}</td>
                        <td className="n">{num(m.clientes)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td className="mes">Total</td>
                    <td className="n">{dec(k.bultos)}</td>
                    <td className="n destac">{pctTxt(k.pct_bultos)}</td>
                    <td className="n">{dec(k.hl)}</td>
                    <td className="n destac">{pctTxt(k.pct_hl)}</td>
                    <td className="n">{money(k.importe)}</td>
                    <td className="n destac">{pctTxt(k.pct_importe)}</td>
                    <td className="n">{num(k.clientes)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* ---------- Ranking de motivos ---------- */}
          <div className="panel">
            <div className="panel-head">
              <h2>Motivos del período · {U.label}</h2>
              <span className="panel-sub">clic para filtrar todo el resumen</span>
            </div>
            <div className="tabla-scroll">
              <table className="tabla-mensual">
                <thead>
                  <tr>
                    <th>Motivo</th>
                    <th className="n">Imputable a</th>
                    <th className="n">Rechazo</th>
                    <th className="n">% de lo {D.hint}</th>
                    <th className="n">Participación</th>
                    <th className="n">Eventos</th>
                    <th className="n">Clientes</th>
                  </tr>
                </thead>
                <tbody>
                  {motivosOrden.map((m) => {
                    const parte = Number(m[unidad]) || 0;
                    const total = Number(k[unidad]) || 0;
                    const share = total ? (parte * 100) / total : 0;
                    return (
                      <tr key={m.motivo}
                          className={filtros.motivo === m.motivo ? "sel" : ""}
                          onClick={() =>
                            setCampo("motivo", filtros.motivo === m.motivo ? "" : m.motivo)}>
                        <td>
                          <span className="leg-punto"
                                style={{ background: colorMotivo.get(m.motivo) || COLOR_OTROS }} />
                          {m.motivo}
                        </td>
                        <td className="n">
                          {/* Es la clasificación que usa el switch VENTAS /
                              DISTRIBUCIÓN del PBI, visible fila por fila. */}
                          <span className={m.imputable === "ventas" ? "tag-v" : "tag-d"}>
                            {m.imputable === "ventas" ? "Ventas" : "Distribución"}
                          </span>
                        </td>
                        <td className="n">{U.fmt(parte)}</td>
                        <td className="n destac">{pctTxt(m[`pct_${unidad}`])}</td>
                        <td className="n">
                          <span className="barra-mini">
                            <i style={{ width: `${Math.min(100, share)}%`,
                                        background: colorMotivo.get(m.motivo) || COLOR_OTROS }} />
                          </span>
                          {dec(share)}%
                        </td>
                        <td className="n">{num(m.lineas)}</td>
                        <td className="n">{num(m.clientes)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
