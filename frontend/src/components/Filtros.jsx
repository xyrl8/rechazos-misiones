import {
  hoyISO,
  isoMenosDias,
  rangoSemanaActual,
  rangoSemanaPasada,
  rangoMTD,
  rangoYTD,
} from "../lib/format.js";

// Días de visita: códigos de Chess (2=Lun … 7=Sáb; no se usa el domingo).
const DIAS_VISITA = [
  { cod: "2", txt: "Lun" },
  { cod: "3", txt: "Mar" },
  { cod: "4", txt: "Mié" },
  { cod: "5", txt: "Jue" },
  { cod: "6", txt: "Vie" },
  { cod: "7", txt: "Sáb" },
];

// Barra de filtros: rango de fechas + atajos + selectores de segmentacion.
function Selector({ label, campo, filtros, setCampo, opciones }) {
  return (
    <div className="field">
      <label>{label}</label>
      <select
        value={filtros[campo] || ""}
        onChange={(e) => setCampo(campo, e.target.value)}
      >
        <option value="">Todos</option>
        {(opciones || []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

// Días de visita: tildables de lunes a sábado. El filtro coincide si el
// cliente se visita en AL MENOS uno de los días marcados.
function DiasVisita({ valor, setCampo }) {
  const sel = new Set((valor || "").split(",").filter(Boolean));
  function toggle(cod) {
    const next = new Set(sel);
    next.has(cod) ? next.delete(cod) : next.add(cod);
    setCampo("dias_visita", [...next].sort().join(","));
  }
  return (
    <div className="field">
      <label>Días visita</label>
      <div className="dias-visita">
        {DIAS_VISITA.map((d) => (
          <button
            key={d.cod}
            type="button"
            className={sel.has(d.cod) ? "activo" : ""}
            onClick={() => toggle(d.cod)}
          >
            {d.txt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Filtros({ filtros, setCampo, setRango, limpiar, opciones }) {
  const atajos = [
    { txt: "Ayer", rango: () => [isoMenosDias(1), isoMenosDias(1)] },
    { txt: "Semana actual", rango: rangoSemanaActual },
    { txt: "Semana pasada", rango: rangoSemanaPasada },
    { txt: "MTD", rango: rangoMTD },
    { txt: "YTD", rango: rangoYTD },
  ];
  return (
    <div className="filtros">
      <div className="field">
        <label>Desde</label>
        <input
          type="date"
          value={filtros.fecha_desde || ""}
          max={hoyISO()}
          onChange={(e) => setCampo("fecha_desde", e.target.value)}
        />
      </div>
      <div className="field">
        <label>Hasta</label>
        <input
          type="date"
          value={filtros.fecha_hasta || ""}
          max={hoyISO()}
          onChange={(e) => setCampo("fecha_hasta", e.target.value)}
        />
      </div>
      <div className="field">
        <label>Atajos</label>
        <div className="quick">
          {atajos.map((a) => (
            <button key={a.txt} onClick={() => setRango(...a.rango())}>
              {a.txt}
            </button>
          ))}
        </div>
      </div>

      <Selector label="Supervisor" campo="supervisor" filtros={filtros}
        setCampo={setCampo} opciones={opciones.supervisor} />
      <Selector label="Promotor" campo="vendedor" filtros={filtros}
        setCampo={setCampo} opciones={opciones.vendedor} />
      <DiasVisita valor={filtros.dias_visita} setCampo={setCampo} />
      <Selector label="Cliente" campo="cliente" filtros={filtros}
        setCampo={setCampo} opciones={opciones.cliente} />
      <Selector label="Motivo" campo="motivo" filtros={filtros}
        setCampo={setCampo} opciones={opciones.motivo} />

      <div className="field">
        <label>&nbsp;</label>
        <button className="btn-clear" onClick={limpiar}>
          Limpiar filtros
        </button>
      </div>
    </div>
  );
}
