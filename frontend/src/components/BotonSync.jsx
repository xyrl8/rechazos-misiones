import { useState, useRef, useEffect } from "react";
import { api } from "../lib/api.js";
import { fechaCorta } from "../lib/format.js";

// Botón de la cabecera. El click principal sincroniza los últimos 7 días
// (refresco para la matinal); el menú permite sincronizar el período elegido
// en los filtros.
export default function BotonSync({ onDone, periodo }) {
  const [estado, setEstado] = useState("idle"); // idle | sync | ok | err
  const [msg, setMsg] = useState("");
  const [menu, setMenu] = useState(false);
  const ref = useRef(null);

  // Cierra el menú al hacer clic afuera.
  useEffect(() => {
    if (!menu) return;
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setMenu(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menu]);

  async function sincronizar(params) {
    if (estado === "sync") return;
    setMenu(false);
    setEstado("sync");
    setMsg("");
    try {
      const r = await api.refrescarSync(params);
      const total = Object.values(r.rechazos || {}).reduce(
        (a, b) => a + (Number(b) || 0),
        0
      );
      setEstado("ok");
      setMsg(`${total} rechazos`);
      onDone && onDone();
      setTimeout(() => setEstado("idle"), 4000);
    } catch (e) {
      setEstado("err");
      setMsg(e.message || "Error");
      setTimeout(() => setEstado("idle"), 6000);
    }
  }

  const texto =
    estado === "sync"
      ? "Sincronizando…"
      : estado === "ok"
      ? `Listo · ${msg}`
      : estado === "err"
      ? `Error · ${msg}`
      : "Sincronizar";

  const hayPeriodo = periodo && periodo.desde && periodo.hasta;

  return (
    <div className="btn-sync-wrap" ref={ref}>
      <button
        className={`btn-sync ${estado}`}
        onClick={() => sincronizar({ dias: 7 })}
        disabled={estado === "sync"}
        title="Sincronizar rechazos de los últimos 7 días"
      >
        <span className={`sync-ico ${estado === "sync" ? "girando" : ""}`}>
          ⟳
        </span>
        {texto}
      </button>
      <button
        className={`btn-sync-caret ${estado}`}
        onClick={() => setMenu((v) => !v)}
        disabled={estado === "sync"}
        title="Más opciones de sincronización"
      >
        ▾
      </button>
      {menu && (
        <div className="sync-menu">
          <div className="sync-menu-opt" onClick={() => sincronizar({ dias: 7 })}>
            Últimos 7 días
          </div>
          <div
            className={`sync-menu-opt${hayPeriodo ? "" : " disabled"}`}
            onClick={() =>
              hayPeriodo &&
              sincronizar({ desde: periodo.desde, hasta: periodo.hasta })
            }
          >
            Período del filtro
            {hayPeriodo && (
              <span className="sync-menu-rango">
                {fechaCorta(periodo.desde)} → {fechaCorta(periodo.hasta)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
