import { useEffect, useRef, useState } from "react";

// Menu de configuracion (icono de tuerca): acceso al mapeo de supervisores.
export default function MenuConfig({ onMapeo }) {
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
