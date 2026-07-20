import { useState, useRef, useEffect, useMemo } from "react";
import {
  hoyISO,
  isoMenosDias,
  rangoSemanaActual,
  rangoSemanaPasada,
  rangoMTD,
  rangoYTD,
  limpiarEtiqueta,
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
            {limpiarEtiqueta(o)}
          </option>
        ))}
      </select>
    </div>
  );
}

// Selector con búsqueda incremental: para listas largas como la de clientes.
// Un input filtra las opciones a medida que se escribe; al elegir una se cierra.
function SelectorBuscable({ label, campo, filtros, setCampo, opciones }) {
  const valor = filtros[campo] || "";
  const [abierto, setAbierto] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  const ref = useRef(null);

  // Cierra el desplegable al hacer clic fuera del componente.
  useEffect(() => {
    if (!abierto) return;
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setAbierto(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [abierto]);

  const lista = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    const ops = opciones || [];
    return q ? ops.filter((o) => o.toLowerCase().includes(q)) : ops;
  }, [opciones, busqueda]);

  function elegir(v) {
    setCampo(campo, v);
    setAbierto(false);
    setBusqueda("");
  }

  return (
    <div className="field" ref={ref}>
      <label>{label}</label>
      <div className="combo">
        <input
          type="text"
          value={abierto ? busqueda : valor}
          placeholder={abierto ? "Escribí para buscar…" : "Todos"}
          onFocus={() => {
            setAbierto(true);
            setBusqueda("");
          }}
          onChange={(e) => {
            setBusqueda(e.target.value);
            setAbierto(true);
          }}
        />
        {valor && !abierto && (
          <button
            type="button"
            className="combo-clear"
            onClick={() => elegir("")}
            title="Quitar filtro"
          >
            ×
          </button>
        )}
        {abierto && (
          <div className="combo-pop">
            <div
              className={`combo-opt${valor === "" ? " sel" : ""}`}
              onClick={() => elegir("")}
            >
              Todos
            </div>
            {lista.length === 0 ? (
              <div className="combo-vacio">Sin coincidencias</div>
            ) : (
              lista.slice(0, 150).map((o) => (
                <div
                  key={o}
                  className={`combo-opt${o === valor ? " sel" : ""}`}
                  onClick={() => elegir(o)}
                  title={o}
                >
                  {o}
                </div>
              ))
            )}
            {lista.length > 150 && (
              <div className="combo-vacio">
                +{lista.length - 150} más — refiná la búsqueda
              </div>
            )}
          </div>
        )}
      </div>
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
          {atajos.map((a) => {
            const [d, h] = a.rango();
            const activo =
              filtros.fecha_desde === d && filtros.fecha_hasta === h;
            return (
              <button
                key={a.txt}
                className={activo ? "activo" : ""}
                onClick={() => setRango(d, h)}
              >
                {a.txt}
              </button>
            );
          })}
        </div>
      </div>

      <Selector label="Supervisor" campo="supervisor" filtros={filtros}
        setCampo={setCampo} opciones={opciones.supervisor} />
      <Selector label="Promotor" campo="vendedor" filtros={filtros}
        setCampo={setCampo} opciones={opciones.vendedor} />
      <DiasVisita valor={filtros.dias_visita} setCampo={setCampo} />
      <SelectorBuscable label="Cliente" campo="cliente" filtros={filtros}
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
