import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { clienteLabel, fechaLarga, fechaHora } from "../lib/format.js";

const AUTOR_KEY = "rechazos.comentarios.autor";

// Hilo de comentarios de un evento de rechazo (fecha + fuente + cliente).
// Estilo HILO: los comentarios se agregan sobre los anteriores y NO se pueden
// borrar; a lo sumo el hilo se marca como resuelto (y se puede reabrir).
export default function ModalComentarios({ grupo, onClose, onChange }) {
  const [hilo, setHilo] = useState(undefined); // undefined = cargando
  const [texto, setTexto] = useState("");
  const [autor, setAutor] = useState(
    () => localStorage.getItem(AUTOR_KEY) || ""
  );
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargar = () => {
    api
      .hilo(grupo.thread_key)
      .then((r) => setHilo(r.hilo))
      .catch((e) => setError(e.message));
  };
  useEffect(cargar, [grupo.thread_key]);

  const recordarAutor = (v) => {
    setAutor(v);
    localStorage.setItem(AUTOR_KEY, v);
  };

  async function agregar() {
    setError("");
    if (!texto.trim()) {
      setError("Escribí un comentario.");
      return;
    }
    setGuardando(true);
    try {
      const r = await api.agregarComentario({
        fecha: grupo.fecha,
        fuente: grupo.fuente,
        id_cliente: grupo.id_cliente == null ? "" : String(grupo.id_cliente),
        cliente: grupo.cliente || "",
        comentario: texto.trim(),
        autor: autor.trim(),
      });
      setHilo(r.hilo);
      setTexto("");
      onChange && onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setGuardando(false);
    }
  }

  async function resolver(resuelto) {
    setError("");
    setGuardando(true);
    try {
      const r = await api.resolverHilo(grupo.thread_key, resuelto, autor.trim());
      setHilo(r.hilo);
      onChange && onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setGuardando(false);
    }
  }

  const comentarios = hilo?.comentarios || [];
  const resuelto = !!hilo?.resuelto;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Comentarios del rechazo</h2>
          <button className="modal-x" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div className="hilo-ctx">
            <b>{clienteLabel(grupo.id_cliente, grupo.cliente)}</b>
            <span className="hilo-ctx-meta">
              <span className={`tag ${grupo.fuente}`}>{grupo.fuente}</span>
              {fechaLarga(grupo.fecha)}
              {resuelto && <span className="hilo-estado ok">✓ Resuelto</span>}
            </span>
          </div>

          {hilo === undefined ? (
            <div className="loading">
              <div className="spinner" />
              Cargando…
            </div>
          ) : (
            <div className="hilo-lista">
              {comentarios.length === 0 ? (
                <div className="empty">
                  Todavía no hay comentarios. Escribí el primero abajo.
                </div>
              ) : (
                comentarios.map((c) => (
                  <div key={c.id} className="hilo-item">
                    <div className="hilo-item-head">
                      <span className="hilo-autor">{c.autor || "Anónimo"}</span>
                      <span className="hilo-fecha">{fechaHora(c.created_at)}</span>
                    </div>
                    <div className="hilo-texto">{c.comentario}</div>
                  </div>
                ))
              )}
            </div>
          )}

          {error && <div className="banner err">{error}</div>}

          {/* --- Nuevo comentario --- */}
          <div className="hilo-form">
            <div className="field">
              <label>Tu nombre (opcional)</label>
              <input
                value={autor}
                placeholder="Quién comenta"
                onChange={(e) => recordarAutor(e.target.value)}
              />
            </div>
            <div className="field">
              <label>Comentario</label>
              <textarea
                rows={3}
                value={texto}
                placeholder="Agregá un comentario al hilo…"
                onChange={(e) => setTexto(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) agregar();
                }}
              />
            </div>
            <div className="hilo-acciones">
              <button
                className="btn-primary"
                onClick={agregar}
                disabled={guardando || hilo === undefined}
              >
                {guardando ? "Guardando…" : "Agregar comentario"}
              </button>
              {hilo &&
                (resuelto ? (
                  <button
                    className="btn-secondary"
                    onClick={() => resolver(false)}
                    disabled={guardando}
                  >
                    Reabrir
                  </button>
                ) : (
                  <button
                    className="btn-secondary"
                    onClick={() => resolver(true)}
                    disabled={guardando}
                    title="Marca el hilo como resuelto (no borra los comentarios)"
                  >
                    Marcar como resuelto
                  </button>
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
