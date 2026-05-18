import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api.js";
import { isoMenosDias, hoyISO } from "../lib/format.js";
import BotonSync from "../components/BotonSync.jsx";
import MenuConfig from "../components/MenuConfig.jsx";
import Filtros from "../components/Filtros.jsx";
import KpiCards from "../components/KpiCards.jsx";
import PanelSegmento from "../components/PanelSegmento.jsx";
import TablaRechazos from "../components/TablaRechazos.jsx";
import ModalMapeo from "../components/ModalMapeo.jsx";

const FILTROS_INI = {
  fuente: "TODO",
  fecha_desde: isoMenosDias(30),
  fecha_hasta: hoyISO(),
  supervisor: "",
  vendedor: "",
  dias_visita: "",
  cliente: "",
  articulo: "",
  motivo: "",
};

export default function Dashboard() {
  const [filtros, setFiltros] = useState(FILTROS_INI);
  const [resumen, setResumen] = useState(null);
  const [detalle, setDetalle] = useState(null);
  const [opciones, setOpciones] = useState({});
  const [sync, setSync] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalMapeo, setModalMapeo] = useState(false);
  const [version, setVersion] = useState(0); // fuerza recarga tras un mapeo

  // --- Mutadores de filtros ---
  const setCampo = useCallback((campo, valor) => {
    setFiltros((f) => ({ ...f, [campo]: valor }));
  }, []);
  const setRango = useCallback((desde, hasta) => {
    setFiltros((f) => ({ ...f, fecha_desde: desde, fecha_hasta: hasta }));
  }, []);
  const setFuente = useCallback((fuente) => {
    // Las dimensiones (supervisor, promotor, ruta...) son propias de cada
    // fuente: al cambiar de fuente se limpian para no arrastrar un filtro
    // que la nueva fuente no puede cumplir (dejaria todo en 0).
    setFiltros((f) => ({
      ...f,
      fuente,
      supervisor: "",
      vendedor: "",
      dias_visita: "",
      cliente: "",
      articulo: "",
      motivo: "",
    }));
  }, []);
  const limpiar = useCallback(() => {
    setFiltros((f) => ({
      ...FILTROS_INI,
      fuente: f.fuente,
      fecha_desde: f.fecha_desde,
      fecha_hasta: f.fecha_hasta,
    }));
  }, []);

  // --- Carga de datos principal (resumen + detalle) ---
  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setError("");
    Promise.all([api.resumen(filtros), api.rechazos({ ...filtros, limit: 800 })])
      .then(([r, d]) => {
        if (cancel) return;
        setResumen(r);
        setDetalle(d);
      })
      .catch((e) => !cancel && setError(e.message))
      .finally(() => !cancel && setLoading(false));
    return () => {
      cancel = true;
    };
  }, [filtros, version]);

  // --- Opciones de los selectores (dependen de fuente + fechas) ---
  useEffect(() => {
    let cancel = false;
    api
      .filtros({
        fuente: filtros.fuente,
        fecha_desde: filtros.fecha_desde,
        fecha_hasta: filtros.fecha_hasta,
      })
      .then((o) => !cancel && setOpciones(o))
      .catch(() => !cancel && setOpciones({}));
    return () => {
      cancel = true;
    };
  }, [filtros.fuente, filtros.fecha_desde, filtros.fecha_hasta]);

  // --- Estado del sync (una vez) ---
  useEffect(() => {
    api.syncEstado().then(setSync).catch(() => {});
  }, []);

  // Tras un sync manual: recarga datos y refresca el estado de sync.
  const trasSync = useCallback(() => {
    setVersion((v) => v + 1);
    api.syncEstado().then(setSync).catch(() => {});
  }, []);

  const syncTxt = useMemo(() => {
    const fechas = (sync?.ultimas_corridas || [])
      .map((c) => c.ended_at)
      .filter(Boolean)
      .map((d) => new Date(d));
    if (!fechas.length) return "Sin sincronización registrada";
    const ultima = new Date(Math.max(...fechas));
    return `Última sincronización: ${ultima.toLocaleString("es-AR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })}`;
  }, [sync]);

  return (
    <div className="app">
      <div className="topbar">
        <div>
          <h1>Seguimientos de rechazos Misiones</h1>
          <div className="sub">Repaso de rutas y clientes críticos</div>
        </div>
        <div className="topbar-acciones">
          <BotonSync
            onDone={trasSync}
            periodo={{
              desde: filtros.fecha_desde,
              hasta: filtros.fecha_hasta,
            }}
          />
          <MenuConfig
            fuente={filtros.fuente}
            onFuente={setFuente}
            onMapeo={() => setModalMapeo(true)}
          />
        </div>
        <div className="sync-info">{syncTxt}</div>
      </div>

      <Filtros
        filtros={filtros}
        setCampo={setCampo}
        setRango={setRango}
        limpiar={limpiar}
        opciones={opciones}
      />

      {error && (
        <div className="banner err">
          No se pudieron cargar los datos: {error}
        </div>
      )}

      {loading && !resumen ? (
        <div className="loading">
          <div className="spinner" />
          Cargando rechazos…
        </div>
      ) : resumen ? (
        <>
          <KpiCards
            kpis={resumen.kpis}
            porMotivo={resumen.por_motivo}
            porLocalidad={resumen.por_localidad}
          />

          <TablaRechazos
            data={detalle}
            criticos={resumen.clientes_criticos}
            periodoCriticidad={resumen.clientes_criticos_periodo}
            seleccion={filtros.cliente}
            onSelectCliente={(v) => setCampo("cliente", v)}
          />

          <div className="grid">
            <PanelSegmento
              titulo="Por supervisor de ventas"
              data={resumen.por_supervisor}
              metrica="importe"
              seleccion={filtros.supervisor}
              onSelect={(v) => setCampo("supervisor", v)}
            />
            <PanelSegmento
              titulo="Por promotor"
              data={resumen.por_vendedor}
              metrica="importe"
              seleccion={filtros.vendedor}
              onSelect={(v) => setCampo("vendedor", v)}
            />
            <PanelSegmento
              titulo="Por motivo de rechazo"
              data={resumen.por_motivo}
              seleccion={filtros.motivo}
              onSelect={(v) => setCampo("motivo", v)}
            />
          </div>
        </>
      ) : null}

      <div className="foot">
        Mercosur Distribuciones · Misiones — Dashboard de Rechazos v1.0
      </div>

      {modalMapeo && (
        <ModalMapeo
          onClose={() => setModalMapeo(false)}
          onChange={() => setVersion((v) => v + 1)}
        />
      )}
    </div>
  );
}
