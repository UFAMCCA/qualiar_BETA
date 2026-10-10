/* Funções compartilhadas do QUALIAR-UFAM. */
const FUSO = "America/Manaus";
const fmtHora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtHH = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit" });
const fmtDiaSem = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, weekday: "short" });

function horaLocal(iso) { return iso ? fmtHora.format(new Date(iso)).replace(",", "") : "—"; }
function hh(iso) { return fmtHH.format(new Date(iso)) + "h"; }
function num(v, casas = 0, suf = "") {
  return v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + suf;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function carregarJSON(caminho) {
  const r = await fetch(caminho, { cache: "no-store" });
  if (!r.ok) throw new Error(`${caminho}: ${r.status}`);
  return r.json();
}
function cardeal(g) {
  if (g == null) return "—";
  return ["N", "NE", "L", "SE", "S", "SO", "O", "NO"][Math.floor(((g + 22.5) % 360) / 45)];
}

/* Classes: preenchidas a partir de qualiar.json */
let CLASSES = [];
function classe(id) { return CLASSES.find(c => c.id === id); }
function corClasse(id) { return id ? classe(id).cor : "#9aa39e"; }
/* amarelo e laranja pedem texto escuro; verde e vermelho pedem texto claro */
function tintaSobre(id) { return id === 2 || id === 3 ? "#1b1a12" : "#ffffff"; }
function seloClasse(id, extra = "") {
  if (!id) return `<span class="selo vazio">sem dado</span>`;
  const c = classe(id);
  return `<span class="selo" style="background:${c.cor};color:${tintaSobre(id)}">${c.id} · ${esc(c.nome)}${extra}</span>`;
}
