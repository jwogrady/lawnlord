// Actual lens — the court's record, reproduced from the DuckDB mirror. The
// register of actions is sortable/filterable; each filing opens as its native
// PDF (real paging, selectable text — not a render). The "Odyssey snapshot"
// lens renders the captured pages/*.html verbatim for side-by-side verification.
// This lens ends at the image.

type Doc = {
	title: string;
	filename: string;
	intakePath: string;
	declaredPageCount: number | null;
};
type RegEntry = {
	date: string;
	event: string;
	party: string;
	section: string;
	documents: Doc[];
};
type Party = { role: string; name: string; representation: string; location: string };
type CaseInfo = {
	number: string;
	title?: string;
	court?: string;
	caseType?: string;
	status?: string;
	dateFiled?: string;
	judicialOfficer?: string;
};
type Payload = {
	case: CaseInfo;
	parties: Party[];
	registerOfActions: RegEntry[];
	documents: Doc[];
};

// Exploded lens — case → filing → image → document → page, with *every*
// transcription variation compared side by side beside each page image so the
// corpus can be QA'd (issue #125). Shapes mirror `lawnlord export-exploded`.
// A changed token span vs the canonical anchor (ADR-0008, computed in the export
// layer). `variation.start`/`.end` are token-index ranges into THIS reading's
// whitespace-split tokens; the viewer highlights them without re-diffing (#126).
type DivSpan = {
	op: "replace" | "delete" | "insert";
	anchor: { start: number; end: number; tokens: string[] };
	variation: { start: number; end: number; tokens: string[] };
};
type Variation = {
	source: string; // "pdf_text" = the record's own text layer; "ai" = a vision model
	model: string | null; // vision model name; null for pdf_text
	rev: number;
	createdAt: string;
	fidelity: number | null;
	text: string | null; // null = no reading captured; "" = an empty reading (shown explicitly)
	agreement: number; // 0–1 similarity to the page's canonical anchor
	divergence: DivSpan[]; // changed spans vs the anchor; empty for the anchor (#126)
	flagged: boolean; // export-decided review signal: low agreement or low fidelity
};
type ExPage = { id: string; pageNumber: number; png: string; transcriptions: Variation[] };
type ExDoc = { id: string; title: string; pageCount: number | null; pages: ExPage[] };
type Filing = { id: string; date: string; event: string; section: string };
type ExImage = {
	imageId: string;
	title: string;
	filename: string;
	filings: Filing[];
	documents: ExDoc[];
};
type Exploded = { images: ExImage[] };
type ColKey = { source: string; model: string | null };

// A spatial-anchor region (ADR-0009, from `export-regions`): a normalized 0..1
// top-left box for one token of a page's canonical text, addressed by spanIndex
// (the token ordinal). The reusable on-image highlight renderer (#129) overlays
// these and links them to the text bidirectionally.
type Region = {
	id: string;
	anchorId: string;
	anchorKind: string;
	spanIndex: number;
	charStart: number | null;
	charEnd: number | null;
	x0: number;
	y0: number;
	x1: number;
	y1: number;
	origin: string;
	confidence: number | null;
};
type PageRegions = { pageId: string; regions: Region[] };

const app = document.getElementById("app") as HTMLElement;
const headerEl = document.getElementById("caseheader") as HTMLElement;
const lensesEl = document.getElementById("lenses") as HTMLElement;

let data: Payload;
let exploded: Exploded | null = null; // lazily fetched on first switch to the Exploded lens
// Exploded-lens drill-down focus; the deepest non-empty id is the active level
// (case → filing → image → document → page). Cleared from the breadcrumb.
let exFiling = ""; // focused filing = an event id (or the UNFILED sentinel)
let exImageId = "";
let exDocId = "";
let exPageId = "";
let lens: "register" | "snapshot" | "exploded" = "register";
let sortKey: "date" | "event" | "party" | "section" = "date";
let sortDir: 1 | -1 = 1;
let filterText = "";
let filterSection = "";
let openDoc = ""; // intakePath of the filing shown in the PDF pane
let openPage = 1;

function esc(s: string): string {
	return (s ?? "").replace(
		/[&<>"]/g,
		(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
	);
}

async function load(): Promise<void> {
	data = (await (await fetch("/api/case")).json()) as Payload;
	render();
}

function renderHeader(): void {
	const c = data.case;
	const bits = [c.caseType, c.court, c.dateFiled && `filed ${c.dateFiled}`, c.status]
		.filter(Boolean)
		.map((b) => `<span>${esc(String(b))}</span>`)
		.join("");
	headerEl.innerHTML = `<h1>${esc(c.title || c.number)}</h1><div class="meta">${bits}</div>`;
}

function renderLensToggle(): void {
	for (const el of lensesEl.querySelectorAll(".lensbtn")) {
		const b = el as HTMLButtonElement;
		b.classList.toggle("on", b.dataset.lens === lens);
		b.onclick = () => {
			lens = b.dataset.lens as typeof lens;
			render();
		};
	}
}

function sections(): string[] {
	return [...new Set(data.registerOfActions.map((e) => e.section).filter(Boolean))];
}

function visibleEntries(): RegEntry[] {
	const q = filterText.toLowerCase();
	const rows = data.registerOfActions.filter((e) => {
		if (filterSection && e.section !== filterSection) return false;
		if (!q) return true;
		return (
			e.event.toLowerCase().includes(q) ||
			e.party.toLowerCase().includes(q) ||
			e.documents.some((d) => d.title.toLowerCase().includes(q))
		);
	});
	return rows.sort((a, b) => {
		const av = (a[sortKey] ?? "").toString();
		const bv = (b[sortKey] ?? "").toString();
		return av < bv ? -sortDir : av > bv ? sortDir : 0;
	});
}

function renderRegister(): void {
	const parties = data.parties
		.map(
			(p) =>
				`<li><b>${esc(p.role)}</b> ${esc(p.name)}${p.representation ? ` — ${esc(p.representation)}` : ""}${p.location ? ` <span class="muted">(${esc(p.location)})</span>` : ""}</li>`,
		)
		.join("");

	const arrow = (k: string) => (sortKey === k ? (sortDir === 1 ? " ▲" : " ▼") : "");
	const head = (["date", "event", "party", "section"] as const)
		.map((k) => `<th data-sort="${k}">${k[0].toUpperCase() + k.slice(1)}${arrow(k)}</th>`)
		.join("");

	const rows = visibleEntries()
		.map((e) => {
			const docs = e.documents
				.map(
					(d) =>
						`<button class="doclink" data-path="${esc(d.intakePath)}" title="${esc(d.title)}">${esc(d.title)}${d.declaredPageCount ? ` · ${d.declaredPageCount}pp` : ""}</button>`,
				)
				.join("");
			return `<tr>
        <td class="nowrap">${esc(e.date)}</td>
        <td>${esc(e.event)}</td>
        <td>${esc(e.party)}</td>
        <td class="muted">${esc(e.section)}</td>
        <td class="docs">${docs || '<span class="muted">—</span>'}</td>
      </tr>`;
		})
		.join("");

	const opts = ['<option value="">all sections</option>']
		.concat(
			sections().map(
				(s) => `<option value="${esc(s)}"${s === filterSection ? " selected" : ""}>${esc(s)}</option>`,
			),
		)
		.join("");

	const pdf = openDoc
		? `<section class="pdfpane">
        <div class="pdfbar">Filed document — <code>${esc(openDoc)}</code>
          <button id="closepdf">close ✕</button></div>
        <iframe class="pdf" src="/${openDoc.split("/").map(encodeURIComponent).join("/")}#page=${openPage}&view=FitH"></iframe>
      </section>`
		: "";

	app.innerHTML = `
    <aside class="parties"><h2>Parties</h2><ul>${parties}</ul></aside>
    <section class="register">
      <div class="controls">
        <input id="q" type="search" placeholder="filter events, parties, documents…" value="${esc(filterText)}" />
        <select id="section">${opts}</select>
        <span class="count">${visibleEntries().length} / ${data.registerOfActions.length}</span>
      </div>
      <table class="roa"><thead><tr>${head}<th>Documents</th></tr></thead><tbody>${rows}</tbody></table>
      ${pdf}
    </section>`;

	(app.querySelector("#q") as HTMLInputElement).oninput = (ev) => {
		filterText = (ev.target as HTMLInputElement).value;
		renderRegister();
	};
	(app.querySelector("#section") as HTMLSelectElement).onchange = (ev) => {
		filterSection = (ev.target as HTMLSelectElement).value;
		renderRegister();
	};
	for (const th of app.querySelectorAll("th[data-sort]")) {
		(th as HTMLElement).onclick = () => {
			const k = (th as HTMLElement).dataset.sort as typeof sortKey;
			if (k === sortKey) sortDir = sortDir === 1 ? -1 : 1;
			else {
				sortKey = k;
				sortDir = 1;
			}
			renderRegister();
		};
	}
	for (const b of app.querySelectorAll(".doclink")) {
		(b as HTMLButtonElement).onclick = () => {
			openDoc = (b as HTMLElement).dataset.path as string;
			openPage = 1;
			renderRegister();
		};
	}
	const close = app.querySelector("#closepdf") as HTMLButtonElement | null;
	if (close) close.onclick = () => {
		openDoc = "";
		renderRegister();
	};
}

function renderSnapshot(): void {
	// The captured Odyssey page, verbatim — the verification artifact.
	app.innerHTML = `<section class="snapshot">
    <p class="muted">Captured Odyssey page (verbatim) — verify the register above matches this.</p>
    <iframe class="snap" src="/pages/CaseDetail.html"></iframe>
  </section>`;
}

// Images with no filing still belong to the case — gather them under one bucket
// so nothing is hidden from navigation.
const UNFILED = " unfiled";

type Bucket = { id: string; date: string; event: string; section: string; images: ExImage[] };

// Group images by the filings that filed them (an image may appear under several
// filings, and unfiled images fall into the UNFILED bucket). Preserves the
// export's deterministic image/filing order.
function filingBuckets(images: ExImage[]): Bucket[] {
	const order: string[] = [];
	const map = new Map<string, Bucket>();
	for (const img of images) {
		const fs: Filing[] = img.filings.length
			? img.filings
			: [{ id: UNFILED, date: "", event: "Unfiled documents", section: "" }];
		for (const f of fs) {
			let b = map.get(f.id);
			if (!b) {
				b = { id: f.id, date: f.date, event: f.event, section: f.section, images: [] };
				map.set(f.id, b);
				order.push(f.id);
			}
			b.images.push(img);
		}
	}
	return order.map((id) => map.get(id) as Bucket);
}

function exLevel(): "case" | "filing" | "image" | "document" | "page" {
	if (exPageId) return "page";
	if (exDocId) return "document";
	if (exImageId) return "image";
	if (exFiling) return "filing";
	return "case";
}

// The variation columns across a set of pages: the union of (source, model)
// keys present, canonical (pdf_text) first, then AI by model. Rendering every
// key for every page makes a reading missing on one page show up explicitly.
function colKeys(pages: ExPage[]): ColKey[] {
	const seen = new Map<string, ColKey>();
	for (const p of pages)
		for (const v of p.transcriptions) {
			const k = `${v.source}::${v.model ?? ""}`;
			if (!seen.has(k)) seen.set(k, { source: v.source, model: v.model });
		}
	return [...seen.values()].sort(
		(a, b) =>
			(a.source === "pdf_text" ? 0 : 1) - (b.source === "pdf_text" ? 0 : 1) ||
			a.source.localeCompare(b.source) ||
			(a.model ?? "").localeCompare(b.model ?? ""),
	);
}

function colTitle(k: ColKey): string {
	return k.source === "pdf_text"
		? "PDF text layer"
		: `AI${k.model ? ` · ${esc(k.model)}` : ""}`;
}

// Token indices in THIS reading that diverge from the anchor — the variation
// side of each replace/insert span (a delete span has an empty variation range,
// so it marks nothing in this column's text). Diffs come from the export layer.
function divergentTokens(spans: DivSpan[]): Set<number> {
	const marked = new Set<number>();
	for (const s of spans) for (let i = s.variation.start; i < s.variation.end; i++) marked.add(i);
	return marked;
}

// Render text with the divergent tokens wrapped in <mark>, preserving the
// original whitespace. The i-th run of non-whitespace is token i — the same unit
// the export split on (`str.split()`) — so no re-diffing happens client-side.
function highlightText(text: string, marked: Set<number>): string {
	let i = 0;
	return text.replace(/\s+|\S+/g, (run) => {
		if (/^\s/.test(run)) return esc(run);
		const idx = i++;
		const e = esc(run);
		return marked.has(idx) ? `<mark class="diff">${e}</mark>` : e;
	});
}

// A reading's body, distinguishing "no reading captured" (null) from an
// explicitly empty reading ("") so an empty string never reads as untranscribed.
// Divergent tokens are highlighted against the canonical anchor (#126).
function readingBody(v: Variation): string {
	if (v.text == null) return '<div class="cmp-empty">no reading captured</div>';
	if (v.text === "") return '<div class="cmp-empty">empty reading — the model returned no text</div>';
	const marked = divergentTokens(v.divergence);
	const body = marked.size ? highlightText(v.text, marked) : esc(v.text);
	return `<pre class="cmp-text">${body}</pre>`;
}

// One comparison cell. Canonical truth (the PDF text layer) is styled as the
// record; AI readings are styled as derived and can never pass as the record.
function cmpCell(v: Variation | undefined, k: ColKey): string {
	if (!v)
		return `<div class="cmp-cell missing"><div class="cmp-head"><span class="badge badge-missing">${colTitle(k)}</span></div><div class="cmp-empty">— not run for this page</div></div>`;
	const canonical = v.source === "pdf_text";
	const flag = v.flagged
		? '<span class="badge badge-flag" title="flagged for review: low agreement or low fidelity">⚑ flagged</span>'
		: "";
	const head = canonical
		? `<span class="badge badge-record">THE RECORD · PDF text layer</span><span class="cmp-meta muted">exact text from the filed PDF</span>`
		: `<span class="badge badge-ai">AI${v.model ? ` · ${esc(v.model)}` : ""}</span>${flag}<span class="cmp-meta muted">${
				v.fidelity != null ? `fidelity ${v.fidelity.toFixed(2)} · ` : ""
			}agreement ${(v.agreement * 100).toFixed(0)}%</span>`;
	return `<div class="cmp-cell ${canonical ? "record" : "derived"}${v.flagged ? " flagged" : ""}"><div class="cmp-head">${head}</div>${readingBody(v)}</div>`;
}

function cmpRow(p: ExPage, keys: ColKey[]): string {
	const focusable = exLevel() !== "page";
	const cells =
		keys
			.map((k) =>
				cmpCell(
					p.transcriptions.find((v) => v.source === k.source && (v.model ?? "") === (k.model ?? "")),
					k,
				),
			)
			.join("") ||
		'<div class="cmp-empty">no transcription yet — run <code>lawnlord transcribe</code></div>';
	return `<div class="cmp-row">
      <figure class="cmp-img">
        <figcaption>p.${p.pageNumber}${focusable ? ` · <button class="exlink" data-page="${esc(p.id)}">focus ↗</button>` : ""}</figcaption>
        <img loading="lazy" src="/png/${p.png.split("/").map(encodeURIComponent).join("/")}" alt="page ${p.pageNumber}" />
      </figure>
      <div class="cmp-cells">${cells}</div>
    </div>`;
}

// Per-page regions, fetched lazily on first focus (keyed by page id).
const regionsCache = new Map<string, Region[]>();

// The record (pdf_text) reading at page focus, with each token wrapped in a
// clickable span addressed by its ordinal — the same index the regions use, so
// token ↔ box linking is a direct lookup. Whitespace is preserved verbatim.
function interactiveRecordBody(v: Variation): string {
	if (v.text == null) return '<div class="cmp-empty">no reading captured</div>';
	if (v.text === "") return '<div class="cmp-empty">empty reading — the model returned no text</div>';
	let i = 0;
	const body = v.text.replace(/\s+|\S+/g, (run) => {
		if (/^\s/.test(run)) return esc(run);
		return `<span class="tok" data-span="${i++}">${esc(run)}</span>`;
	});
	return `<pre class="cmp-text">${body}</pre>`;
}

// THE reusable on-image highlight renderer (#129, a layer:platform primitive):
// given the element wrapping a page image and the page's anchored regions, paint
// one box per region and expose highlight/mark/clear + a click hook. Boxes are
// positioned by the regions' normalized 0..1 coords, so they track the image at
// any size. Future consumers (citations/claims/defenses; #38/#118) drive the
// same renderer with their own anchored regions — only spanIndex addressing is
// assumed, nothing transcription-specific.
type RegionOverlay = {
	highlight(spanIndices: number[]): void; // exclusive "active" set (highlight([]) clears)
	mark(spanIndices: number[], cls: string): void; // additive class (e.g. "diverged")
	onPick(cb: (spanIndex: number) => void): void;
};
function mountRegionOverlay(wrap: HTMLElement, regions: Region[]): RegionOverlay {
	const layer = document.createElement("div");
	layer.className = "region-layer";
	const boxes = new Map<number, HTMLElement>();
	let pick: (spanIndex: number) => void = () => {};
	for (const r of regions) {
		const box = document.createElement("div");
		box.className = "region-box";
		box.style.left = `${r.x0 * 100}%`;
		box.style.top = `${r.y0 * 100}%`;
		box.style.width = `${(r.x1 - r.x0) * 100}%`;
		box.style.height = `${(r.y1 - r.y0) * 100}%`;
		box.dataset.span = String(r.spanIndex);
		box.onclick = () => pick(r.spanIndex);
		layer.appendChild(box);
		boxes.set(r.spanIndex, box);
	}
	wrap.appendChild(layer);
	return {
		highlight(spanIndices) {
			for (const b of boxes.values()) b.classList.remove("active");
			for (const i of spanIndices) boxes.get(i)?.classList.add("active");
		},
		mark(spanIndices, cls) {
			for (const i of spanIndices) boxes.get(i)?.classList.add(cls);
		},
		onPick(cb) {
			pick = cb;
		},
	};
}

// Mount the overlay and wire token ↔ box bidirectionally for the focused page.
// Divergence is the first consumer: the record tokens any AI reading replaced or
// dropped (from the export's divergence spans) are pre-marked on the image, so
// disagreement shows without a click. No regions (a scanned page) → text-only.
async function wireFocusPage(page: ExPage): Promise<void> {
	const wrap = app.querySelector(".cmp-imgwrap") as HTMLElement | null;
	if (!wrap) return;
	let regions = regionsCache.get(page.id);
	if (regions === undefined) {
		// Only a successful read is cached; a transient failure (a 500 or a
		// network error) is left uncached so the next focus on this page retries
		// rather than being stuck text-only for the session.
		try {
			const res = await fetch(`/api/regions?page=${encodeURIComponent(page.id)}`);
			if (!res.ok) return;
			const pr = (await res.json()) as PageRegions;
			regions = pr.regions.filter((r) => r.origin === "pdf_text");
		} catch {
			return;
		}
		regionsCache.set(page.id, regions);
	}
	// The fetch may have resolved after the user navigated away: only mount if
	// this page is still the focused one and its wrapper is still in the live DOM.
	if (exPageId !== page.id || !wrap.isConnected) return;
	if (!regions.length) return; // graceful text-only fallback
	const overlay = mountRegionOverlay(wrap, regions);

	// Record tokens indexed by ordinal for O(1) lookup (mirrors the box map).
	const tokBySpan = new Map<number, HTMLElement>();
	for (const el of app.querySelectorAll("[data-record] .tok")) {
		const t = el as HTMLElement;
		tokBySpan.set(Number(t.dataset.span), t);
	}

	// Diverged record tokens = the anchor-side of every AI reading's divergence
	// spans (token-index ranges from the export — never re-diffed here).
	const diverged = new Set<number>();
	for (const v of page.transcriptions) {
		if (v.source === "pdf_text") continue;
		for (const s of v.divergence)
			for (let i = s.anchor.start; i < s.anchor.end; i++) diverged.add(i);
	}
	overlay.mark([...diverged], "diverged");
	for (const i of diverged) tokBySpan.get(i)?.classList.add("diverged");

	// One selection routine drives both directions, so clicking a word and
	// clicking its box behave identically: highlight the box, activate the token,
	// and reveal both (cheap — touches only the previously- and newly-active one).
	let active: HTMLElement | null = null;
	const select = (span: number) => {
		overlay.highlight([span]);
		active?.classList.remove("active");
		active = tokBySpan.get(span) ?? null;
		active?.classList.add("active");
		active?.scrollIntoView({ block: "nearest" });
		wrap.querySelector<HTMLElement>(`.region-box[data-span="${span}"]`)?.scrollIntoView({ block: "nearest" });
	};
	overlay.onPick(select);
	for (const [span, t] of tokBySpan) t.onclick = () => select(span);
}

// The focused single page: the image with its region overlay beside the record
// (interactive tokens) and the other readings (normal comparison cells).
function focusPageHtml(page: ExPage): string {
	const keys = colKeys([page]);
	const cells =
		keys
			.map((k) => {
				const v = page.transcriptions.find(
					(t) => t.source === k.source && (t.model ?? "") === (k.model ?? ""),
				);
				if (v && v.source === "pdf_text")
					return `<div class="cmp-cell record" data-record="1"><div class="cmp-head"><span class="badge badge-record">THE RECORD · PDF text layer</span><span class="cmp-meta muted">click a word to locate it on the page</span></div>${interactiveRecordBody(v)}</div>`;
				return cmpCell(v, k);
			})
			.join("") ||
		'<div class="cmp-empty">no transcription yet — run <code>lawnlord transcribe</code></div>';
	return `<div class="cmp-row">
      <figure class="cmp-img"><figcaption>p.${page.pageNumber}</figcaption>
        <div class="cmp-imgwrap"><img src="/png/${page.png.split("/").map(encodeURIComponent).join("/")}" alt="page ${page.pageNumber}" /></div>
      </figure>
      <div class="cmp-cells">${cells}</div>
    </div>`;
}

// The breadcrumb across the five levels; each set crumb is clickable to pop the
// focus back up to that level (clearing the deeper ones). The filing label is
// resolved from the buckets (always populated) so it reads correctly even at the
// filing level, before any image is selected.
function exBreadcrumb(
	filingLabel: string,
	cur: ExImage | null,
	doc: ExDoc | null,
	page: ExPage | null,
): string {
	const crumbs: string[] = [`<button class="crumb" data-lvl="case">Case ${esc(data.case.number)}</button>`];
	if (exFiling) crumbs.push(`<button class="crumb" data-lvl="filing">${esc(filingLabel)}</button>`);
	if (cur) crumbs.push(`<button class="crumb" data-lvl="image">${esc(cur.title || cur.filename)}</button>`);
	if (doc) crumbs.push(`<button class="crumb" data-lvl="document">${esc(doc.title)}</button>`);
	if (page) crumbs.push(`<button class="crumb" data-lvl="page">p.${page.pageNumber}</button>`);
	return `<nav class="crumbs">${crumbs.join('<span class="sep">›</span>')}</nav>`;
}

async function renderExploded(): Promise<void> {
	if (exploded === null) {
		app.innerHTML = '<p class="muted">Loading exploded pages…</p>';
		exploded = (await (await fetch("/api/exploded")).json()) as Exploded;
	}
	const images = exploded.images;
	if (!images.length) {
		app.innerHTML =
			'<p class="muted">No exploded pages yet. Run <code>lawnlord explode</code> (and <code>transcribe</code>) first.</p>';
		return;
	}

	// Resolve the focus path, dropping any stale ids so the breadcrumb is honest.
	const cur = exImageId ? (images.find((i) => i.imageId === exImageId) ?? null) : null;
	if (exImageId && !cur) exImageId = exDocId = exPageId = "";
	const doc = cur && exDocId ? (cur.documents.find((d) => d.id === exDocId) ?? null) : null;
	if (exDocId && !doc) exDocId = exPageId = "";
	const allPages = (cur ?? { documents: [] as ExDoc[] }).documents.flatMap((d) => d.pages);
	const page = exPageId ? (allPages.find((p) => p.id === exPageId) ?? null) : null;
	if (exPageId && !page) exPageId = "";

	const buckets = filingBuckets(images);
	const filingLabel = exFiling
		? exFiling === UNFILED
			? "Unfiled"
			: (buckets.find((b) => b.id === exFiling)?.event ?? "Filing")
		: "";

	const level = exLevel();
	let body = "";
	if (level === "case") {
		body = `<div class="navgrid">${buckets
			.map((b) => {
				const pp = b.images.reduce((n, i) => n + i.documents.reduce((m, d) => m + d.pages.length, 0), 0);
				return `<button class="navcard" data-filing="${esc(b.id)}">
            <span class="navtitle">${esc(b.event || "Filing")}</span>
            <span class="navmeta muted">${b.date ? `${esc(b.date)} · ` : ""}${esc(b.section || "")}</span>
            <span class="navmeta muted">${b.images.length} image${b.images.length === 1 ? "" : "s"} · ${pp} pp</span>
          </button>`;
			})
			.join("")}</div>`;
	} else if (level === "filing") {
		const bucket = buckets.find((b) => b.id === exFiling);
		const imgs = bucket ? bucket.images : [];
		body = `<div class="navgrid">${imgs
			.map((i) => {
				const pp = i.documents.reduce((n, d) => n + d.pages.length, 0);
				return `<button class="navcard" data-img="${esc(i.imageId)}">
            <span class="navtitle">${esc(i.title || i.filename)}</span>
            <span class="navmeta muted">${i.documents.length} document${i.documents.length === 1 ? "" : "s"} · ${pp} pp</span>
          </button>`;
			})
			.join("")}</div>`;
	} else if (level === "image" && cur) {
		// Each document as a section, with its pages already laid out as comparison grids.
		body = cur.documents
			.map((d) => {
				const keys = colKeys(d.pages);
				return `<section class="cmp-doc">
            <h3><button class="exlink" data-doc="${esc(d.id)}">${esc(d.title)} ↗</button>
              <span class="muted">${d.pages.length} pp</span></h3>
            ${d.pages.map((p) => cmpRow(p, keys)).join("")}
          </section>`;
			})
			.join("");
	} else if (level === "document" && doc) {
		const keys = colKeys(doc.pages);
		body = `<section class="cmp-doc"><h3>${esc(doc.title)} <span class="muted">${doc.pages.length} pp</span></h3>
        ${doc.pages.map((p) => cmpRow(p, keys)).join("")}</section>`;
	} else if (level === "page" && page) {
		body = `<section class="cmp-doc cmp-focus">${focusPageHtml(page)}</section>`;
	}

	app.innerHTML = `<section class="qa">${exBreadcrumb(filingLabel, cur, doc, page)}${body}</section>`;

	for (const el of app.querySelectorAll(".crumb")) {
		(el as HTMLButtonElement).onclick = () => {
			const lvl = (el as HTMLElement).dataset.lvl;
			if (lvl === "case") {
				exFiling = exImageId = exDocId = exPageId = "";
			} else if (lvl === "filing") {
				exImageId = exDocId = exPageId = "";
			} else if (lvl === "image") {
				exDocId = exPageId = "";
			} else if (lvl === "document") {
				exPageId = "";
			}
			renderExploded();
		};
	}
	for (const el of app.querySelectorAll("[data-filing]"))
		(el as HTMLButtonElement).onclick = () => {
			exFiling = (el as HTMLElement).dataset.filing as string;
			renderExploded();
		};
	for (const el of app.querySelectorAll("[data-img]"))
		(el as HTMLButtonElement).onclick = () => {
			exImageId = (el as HTMLElement).dataset.img as string;
			renderExploded();
		};
	for (const el of app.querySelectorAll("[data-doc]"))
		(el as HTMLButtonElement).onclick = () => {
			exDocId = (el as HTMLElement).dataset.doc as string;
			renderExploded();
		};
	for (const el of app.querySelectorAll("[data-page]"))
		(el as HTMLButtonElement).onclick = () => {
			exPageId = (el as HTMLElement).dataset.page as string;
			renderExploded();
		};

	// On the focused page, mount the on-image highlight overlay and wire it to
	// the record tokens (async: regions are fetched lazily).
	if (level === "page" && page) void wireFocusPage(page);
}

function render(): void {
	renderHeader();
	renderLensToggle();
	if (lens === "snapshot") renderSnapshot();
	else if (lens === "exploded") void renderExploded();
	else renderRegister();
}

load();
