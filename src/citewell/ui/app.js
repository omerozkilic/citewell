// Citewell web UI: a read-only search page. No build step, no external assets.
// Text from documents is untrusted: it is only ever inserted with textContent / createTextNode.
"use strict";

const STRINGS = {
  en: {
    skip: "Skip to results", tagline: "Search your documents and get cited passages.",
    query: "Question or keywords", collection: "Collection", mode: "Mode", count: "Results",
    rerank: "Rerank", search: "Search", tokenTitle: "Access token",
    tokenHelp: "This server asks for a bearer token. It is kept for this browser tab only.",
    token: "Token", tokenSave: "Use token",
    footer: "Read-only. Passages are shown as plain text from your documents. Press / to jump to the search box.",
    all: "All collections", docs: "docs", chunks: "chunks", searching: "Searching…",
    found: (n, ms, conf) => `${n} result${n === 1 ? "" : "s"} in ${ms} ms · confidence ${conf}`,
    none: "No matching passages. Try other keywords or another collection.",
    weak: "Weak match: the documents probably do not answer this question. Read the passages critically.",
    needToken: "This server needs an access token. Enter it above.",
    forbidden: "This token may not access that collection.",
    failed: "The request failed", showFull: "Full passage", page: "p.", pdfPage: "PDF p.", chunk: "chunk",
  },
  tr: {
    skip: "Sonuçlara geç", tagline: "Belgelerinizde arayın, kaynaklı pasajlar alın.",
    query: "Soru veya anahtar kelimeler", collection: "Koleksiyon", mode: "Mod", count: "Sonuç sayısı",
    rerank: "Yeniden sırala", search: "Ara", tokenTitle: "Erişim anahtarı",
    tokenHelp: "Bu sunucu bir bearer token istiyor. Yalnızca bu tarayıcı sekmesinde saklanır.",
    token: "Token", tokenSave: "Tokenı kullan",
    footer: "Salt okunur. Pasajlar belgelerinizden düz metin olarak gösterilir. Arama kutusuna gitmek için / tuşuna basın.",
    all: "Tüm koleksiyonlar", docs: "belge", chunks: "parça", searching: "Aranıyor…",
    found: (n, ms, conf) => `${n} sonuç, ${ms} ms · güven ${conf}`,
    none: "Eşleşen pasaj yok. Başka kelimeler veya başka bir koleksiyon deneyin.",
    weak: "Zayıf eşleşme: belgeler bu soruyu büyük olasılıkla yanıtlamıyor. Pasajlara eleştirel bakın.",
    needToken: "Bu sunucu erişim anahtarı istiyor. Yukarıya girin.",
    forbidden: "Bu token o koleksiyona erişemez.",
    failed: "İstek başarısız oldu", showFull: "Tam pasaj", page: "s.", pdfPage: "PDF s.", chunk: "parça",
  },
};
const lang = (navigator.language || "en").toLowerCase().startsWith("tr") ? "tr" : "en";
const S = STRINGS[lang];
document.documentElement.lang = lang;

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "citewell-token";

function getToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
function setToken(value) {
  try { value ? sessionStorage.setItem(TOKEN_KEY, value) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers, credentials: "omit" });
  if (res.status === 401) {
    $("token-box").hidden = false;
    $("token-box").open = true;
    throw new Error(S.needToken);
  }
  if (res.status === 403) throw new Error(S.forbidden);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    throw new Error(`${S.failed} (${res.status})${typeof detail === "string" && detail ? `: ${detail}` : ""}`);
  }
  return res.json();
}

function showError(message) {
  const el = $("error");
  el.textContent = message || "";
  el.hidden = !message;
}

async function loadCollections() {
  const select = $("collection");
  let collections;
  try {
    collections = await api("/v1/collections");
  } catch (err) {
    showError(err.message);
    return;
  }
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "*";
  all.textContent = S.all;
  select.append(all);
  for (const c of collections) {
    const option = document.createElement("option");
    option.value = c.name;
    option.textContent = `${c.name} (${c.document_count} ${S.docs}, ${c.chunk_count} ${S.chunks})`;
    select.append(option);
  }
  const preferred = collections.find((c) => c.name === "default") || null;
  select.value = preferred ? preferred.name : "*";
  showError("");
}

// Highlight words that start like a query word (5-letter stems, so "izinleri" matches "izin").
function stems(query) {
  const out = new Set();
  for (const word of query.toLocaleLowerCase(lang).match(/[\p{L}\p{N}]+/gu) || []) {
    if (word.length >= 3) out.add(word.slice(0, 5));
  }
  return out;
}

function highlighted(text, query) {
  const wanted = stems(query);
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const m of text.matchAll(/[\p{L}\p{N}]+/gu)) {
    const word = m[0].toLocaleLowerCase(lang);
    if (word.length >= 3 && wanted.has(word.slice(0, 5))) {
      if (m.index > last) frag.append(document.createTextNode(text.slice(last, m.index)));
      const mark = document.createElement("mark");
      mark.textContent = m[0];
      frag.append(mark);
      last = m.index + m[0].length;
    }
  }
  if (last < text.length) frag.append(document.createTextNode(text.slice(last)));
  return frag;
}

function pageLabel(hit) {
  if (hit.page != null) {
    if (hit.page_label && hit.page_label !== String(hit.page)) {
      return `${S.page} ${hit.page_label} (${S.pdfPage} ${hit.page})`;
    }
    return `${S.page} ${hit.page}`;
  }
  return hit.section ? `§ ${hit.section}` : "";
}

function renderHit(hit, query) {
  const li = document.createElement("li");
  li.className = "hit";
  const h2 = document.createElement("h2");
  const loc = pageLabel(hit);
  h2.textContent = `[${hit.rank}] ${hit.title || hit.source}${loc ? ` — ${loc}` : ""}`;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${hit.source} · ${hit.collection} · ${S.chunk} ${hit.chunk_id} · ${hit.score}`;
  const quote = document.createElement("blockquote");
  quote.append(highlighted(hit.quote, query));
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = S.showFull;
  const pre = document.createElement("pre");
  pre.append(highlighted(hit.text, query));
  details.append(summary, pre);
  li.append(h2, meta, quote, details);
  return li;
}

async function runSearch(event) {
  event.preventDefault();
  const query = $("q").value.trim();
  if (!query) return;
  const button = $("go");
  button.disabled = true;
  showError("");
  $("banner").hidden = true;
  $("status").textContent = S.searching;
  try {
    const body = {
      query,
      top_k: Math.max(1, Math.min(50, Number($("k").value) || 5)),
      mode: $("mode").value,
      collections: [$("collection").value || "*"],
      rerank: $("rerank").checked ? true : null,
    };
    const data = await api("/v1/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const list = $("results");
    list.replaceChildren(...data.hits.map((hit) => renderHit(hit, query)));
    if (!data.hits.length) {
      $("status").textContent = S.none;
    } else {
      $("status").textContent = S.found(data.hits.length, Math.round(data.took_ms), data.confidence.toFixed(2));
      if (!data.answerable) {
        $("banner").textContent = S.weak;
        $("banner").hidden = false;
      }
    }
  } catch (err) {
    $("status").textContent = "";
    $("results").replaceChildren();
    showError(err.message);
  } finally {
    button.disabled = false;
  }
}

function init() {
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const value = S[el.dataset.i18n];
    if (typeof value === "string") el.textContent = value;
  }
  $("search-form").addEventListener("submit", runSearch);
  $("token-save").addEventListener("click", async () => {
    setToken($("token").value.trim());
    $("token").value = "";
    await loadCollections();
  });
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || "");
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      $("q").focus();
    }
  });
  loadCollections();
}

init();
