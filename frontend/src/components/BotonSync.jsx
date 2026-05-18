import { useState } from "react";
import { api } from "../lib/api.js";

// Boton de la cabecera: dispara un sync de los ultimos 7 dias y recarga.
export default function BotonSync({ onDone }) {
  const [estado, setEstado] = useState("idle"); // idle | sync | ok | err
  const [msg, setMsg] = useState("");

  async function sincronizar() {
    if (estado === "sync") return;
    setEstado("sync");
    setMsg("");
    try {
      const r = await api.refrescarSync(7);
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
      ? "Error al sincronizar"
      : "Sincronizar";

  return (
    <button
      className={`btn-sync ${estado}`}
      onClick={sincronizar}
      disabled={estado === "sync"}
      title="Sincronizar rechazos de los últimos 7 días"
    >
      <span className={`sync-ico ${estado === "sync" ? "girando" : ""}`}>
        ⟳
      </span>
      {texto}
    </button>
  );
}
