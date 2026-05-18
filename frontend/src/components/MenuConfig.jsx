import { useEffect, useRef, useState } from "react";

const FUENTES = ["CHESS", "GESCOM", "TODO"];

// Menu de configuracion (icono de tuerca). Agrupa la fuente de datos y el
// acceso al mapeo de supervisores.
export default function MenuConfig({ fuente, onFuente, onMapeo }) {
  const [abierto, setAbierto] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!abierto) return;
    function fuera(e) {
      if (ref.current && !ref.current.contains(e.target)) setAbierto(false);
    }
    document.addEventListener("mousedown", fuera);
    return () => document.removeEventListener("mousedown", fuera);
  }, [abierto]);

  return (
    <div className="config" ref={ref}>
      <button
        className={`btn-config ${abierto ? "activo" : ""}`}
        onClick={() => setAbierto((v) => !v)}
        title="Configuración"
        aria-label="Configuración"
      >
        ⚙
      </button>
      {abierto && (
        <div className="config-menu">
          <div className="config-titulo">Fuente de datos</div>
          {FUENTES.map((f) => (
            <label key={f} className="config-opt">
              <input
                type="radio"
                name="cfg-fuente"
                checked={fuente === f}
                onChange={() => onFuente(f)}
              />
              <span>{f}</span>
            </label>
          ))}
          <div className="config-sep" />
          <button
            className="config-accion"
            onClick={() => {
              setAbierto(false);
              onMapeo();
            }}
          >
            Mapeo de supervisores
          </button>
        </div>
      )}
    </div>
  );
}
