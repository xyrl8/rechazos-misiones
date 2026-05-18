// Lógica de criticidad de clientes, compartida por el resumen compacto y la
// tabla de detalle fusionada.
//
// "veces" = cantidad de DÍAS distintos en que el cliente rechazó dentro de la
// ventana de criticidad. La ventana es de mínimo 15 días: si el período del
// filtro es más corto, la criticidad igual se mide sobre los últimos 15 días
// (es una métrica por cliente, distinta del período del detalle).

// Umbrales relativos a la longitud de la ventana de criticidad.
// Base: 15 días -> crítico 3, recurrente 2. A partir de 30 días se suma 1 a
// cada umbral, y 1 más por cada mes (30 días) adicional.
export function umbrales(periodo) {
  let dias = 15;
  if (periodo?.desde && periodo?.hasta) {
    const ms = new Date(periodo.hasta) - new Date(periodo.desde);
    dias = Math.max(15, Math.round(ms / 86400000));
  }
  const extra = Math.floor(dias / 30); // 15-29d -> 0, 30-59d -> 1, 60-89d -> 2...
  return {
    dias,
    critico: 3 + extra,
    recurrente: 2 + extra,
  };
}

// Nivel de criticidad según cuántos DÍAS distintos rechazó en el período.
// `rango` permite ordenar (Crítico > Recurrente > Ocasional > Sin dato).
export function nivelDe(veces, u) {
  if (veces == null) return { txt: "—", cls: "ocasional", rango: 0 };
  if (veces >= u.critico) return { txt: "Crítico", cls: "critico", rango: 3 };
  if (veces >= u.recurrente)
    return { txt: "Recurrente", cls: "recurrente", rango: 2 };
  return { txt: "Ocasional", cls: "ocasional", rango: 1 };
}

// Construye un índice id_cliente -> { veces } a partir de `clientes_criticos`.
// La tabla de detalle lo consulta para enriquecer cada grupo de rechazos.
export function indiceCriticidad(clientesCriticos) {
  const map = new Map();
  for (const c of clientesCriticos || []) {
    map.set(String(c.id_cliente ?? ""), c);
  }
  return map;
}
