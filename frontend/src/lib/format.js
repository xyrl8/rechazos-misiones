// Helpers de formato (es-AR).
const nf0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });

export const num = (v) => nf0.format(Number(v) || 0);
export const dec = (v) => nf1.format(Number(v) || 0);

export const money = (v) =>
  "$ " +
  new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(
    Number(v) || 0
  );

export function moneyCompact(v) {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1_000_000) return "$ " + dec(n / 1_000_000) + " M";
  if (Math.abs(n) >= 1_000) return "$ " + num(n / 1_000) + " K";
  return "$ " + num(n);
}

// "2026-05-15" -> "15/05"
export function fechaCorta(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}/${m}`;
}

export function fechaLarga(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

// Días de visita: el campo `diasVisita` de Chess viene como "2,5" — códigos
// de día de la semana (1=Dom, 2=Lun … 7=Sáb). Se muestra con nombres cortos.
const DIA_SEMANA = {
  "1": "Dom",
  "2": "Lun",
  "3": "Mar",
  "4": "Mié",
  "5": "Jue",
  "6": "Vie",
  "7": "Sáb",
};

export function diasVisitaLabel(raw) {
  if (!raw) return "";
  return String(raw)
    .split(",")
    .map((d) => DIA_SEMANA[d.trim()] || d.trim())
    .filter(Boolean)
    .join(", ");
}

// Cliente en formato "código - razón social" (el código es el de Chess).
export function clienteLabel(idCliente, nombre) {
  const id = (idCliente ?? "").toString().trim();
  return id ? `${id} - ${nombre}` : nombre;
}

export function hoyISO() {
  return new Date().toISOString().slice(0, 10);
}

export function isoMenosDias(dias) {
  const d = new Date();
  d.setDate(d.getDate() - dias);
  return d.toISOString().slice(0, 10);
}

const iso = (d) => d.toISOString().slice(0, 10);

// Semana calendario actual (lunes a hoy).
export function rangoSemanaActual() {
  const hoy = new Date();
  const dow = (hoy.getDay() + 6) % 7; // lunes = 0
  const lunes = new Date(hoy);
  lunes.setDate(hoy.getDate() - dow);
  return [iso(lunes), hoyISO()];
}

// Semana calendario pasada (lunes a domingo).
export function rangoSemanaPasada() {
  const hoy = new Date();
  const dow = (hoy.getDay() + 6) % 7; // lunes = 0
  const lunesEsta = new Date(hoy);
  lunesEsta.setDate(hoy.getDate() - dow);
  const lunesPasada = new Date(lunesEsta);
  lunesPasada.setDate(lunesEsta.getDate() - 7);
  const domingoPasada = new Date(lunesEsta);
  domingoPasada.setDate(lunesEsta.getDate() - 1);
  return [iso(lunesPasada), iso(domingoPasada)];
}

// MTD: del 1 del mes en curso a hoy.
export function rangoMTD() {
  const hoy = new Date();
  const m = String(hoy.getMonth() + 1).padStart(2, "0");
  return [`${hoy.getFullYear()}-${m}-01`, hoyISO()];
}

// YTD: del 1 de enero del año en curso a hoy.
export function rangoYTD() {
  return [`${new Date().getFullYear()}-01-01`, hoyISO()];
}
