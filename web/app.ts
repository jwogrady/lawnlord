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

// Exploded lens — images → documents → pages, with transcription beside each page.
type ExPage = { pageNumber: number; png: string; text: string | null; fidelity: number | null };
type ExDoc = { title: string; pageCount: number | null; pages: ExPage[] };
type ExImage = { imageId: string; title: string; filename: string; documents: ExDoc[] };
type Exploded = { images: ExImage[] };

const app = document.getElementById("app") as HTMLElement;
const headerEl = document.getElementById("caseheader") as HTMLElement;
const lensesEl = document.getElementById("lenses") as HTMLElement;

let data: Payload;
let exploded: Exploded | null = null; // lazily fetched on first switch to the Exploded lens
let exImageId = ""; // the image selected in the Exploded lens
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
	if (!exImageId || !images.some((i) => i.imageId === exImageId)) {
		exImageId = images[0].imageId;
	}
	const cur = images.find((i) => i.imageId === exImageId) as ExImage;

	const rail = images
		.map(
			(i) =>
				`<button class="docitem${i.imageId === exImageId ? " cur" : ""}" data-img="${esc(i.imageId)}">
        <span class="doctitle">${esc(i.title || i.filename)}</span>
        <span class="docmeta muted">${i.documents.reduce((n, d) => n + d.pages.length, 0)} pp</span>
      </button>`,
		)
		.join("");

	const docs = cur.documents
		.map((d) => {
			const pages = d.pages
				.map(
					(p) => `<div class="exrow">
            <figure class="exfig">
              <figcaption>p.${p.pageNumber}</figcaption>
              <img loading="lazy" src="/png/${p.png.split("/").map(encodeURIComponent).join("/")}" alt="page ${p.pageNumber}" />
            </figure>
            <div class="extext">
              ${
								p.text
									? `<div class="exmeta muted">transcription${p.fidelity != null ? ` · fidelity ${p.fidelity.toFixed(2)}` : ""}</div><pre>${esc(p.text)}</pre>`
									: '<div class="exmeta muted">no transcription yet — run <code>lawnlord transcribe</code></div>'
							}
            </div>
          </div>`,
				)
				.join("");
			return `<section class="exdoc"><h3>${esc(d.title)}</h3>${pages}</section>`;
		})
		.join("");

	app.innerHTML = `
    <aside class="docs"><div class="docs-h">Filed images — ${esc(data.case.number)}</div>${rail}</aside>
    <section class="exploded">${docs}</section>`;

	for (const b of app.querySelectorAll(".docitem")) {
		(b as HTMLButtonElement).onclick = () => {
			exImageId = (b as HTMLElement).dataset.img as string;
			renderExploded();
		};
	}
}

function render(): void {
	renderHeader();
	renderLensToggle();
	if (lens === "snapshot") renderSnapshot();
	else if (lens === "exploded") void renderExploded();
	else renderRegister();
}

load();
