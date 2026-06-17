// Document/exhibit review workflow (#69): the case is grouped into its filed
// documents and exhibits (Motion, Exhibit B, the Affidavit) — the unit you
// litigate at. Pick one in the sidebar, then page through it comparing actual
// vs reconstructed: see lawnlord's score + note, rate (good–bad), note, flag.
// Completing a page marks it human-reviewed; the gap vs lawnlord's score is the
// point.

type Review = {
	rating: number;
	notes: string;
	flag: boolean;
	reviewed: boolean;
} | null;

type Doc = {
	id: string;
	title: string;
	family: string;
	pageStart: number | null;
	pageEnd: number | null;
};

type Page = {
	id: string;
	image: string;
	page: number;
	document: Doc;
	actual: string;
	reconstructed: string;
	score: number; // lawnlord confidence, 0..1
	note: string;
	review: Review;
};

type Data = { case: string; pages: Page[] };

const app = document.getElementById("app") as HTMLElement;
const progressEl = document.getElementById("progress") as HTMLElement;

let data: Data;
let idx = 0;

function esc(s: string): string {
	return (s ?? "").replace(
		/[&<>"]/g,
		(c) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
	);
}

function reviewedCount(): number {
	return data.pages.filter((p) => p.review?.reviewed).length;
}

type DocGroup = {
	doc: Doc;
	first: number;
	total: number;
	reviewed: number;
	idxs: number[];
};

function docGroups(): DocGroup[] {
	const out: DocGroup[] = [];
	const at = new Map<string, number>();
	data.pages.forEach((p, i) => {
		if (!at.has(p.document.id)) {
			at.set(p.document.id, out.length);
			out.push({ doc: p.document, first: i, total: 0, reviewed: 0, idxs: [] });
		}
		const g = out[at.get(p.document.id) as number];
		g.total++;
		g.idxs.push(i);
		if (p.review?.reviewed) g.reviewed++;
	});
	return out;
}

async function load(): Promise<void> {
	data = await (await fetch("/api/pages")).json();
	idx = data.pages.findIndex((p) => !p.review?.reviewed);
	if (idx < 0) idx = 0;
	render();
}

function render(): void {
	const p = data.pages[idx];
	const myScore = Math.round(p.score * 100);
	const rating = p.review ? p.review.rating : myScore; // default to lawnlord's
	progressEl.textContent = `${reviewedCount()} / ${data.pages.length} reviewed · ${data.case}`;

	// The left rail is the case's table of contents: every filed document in
	// docket order, the current one expanded into its pages so you can jump to
	// any page and see its review status at a glance.
	const sidebar = docGroups()
		.map((g, n) => {
			const isCur = g.doc.id === p.document.id;
			const cur = isCur ? " cur" : "";
			const done = g.reviewed === g.total ? " done" : "";
			const fam = g.doc.family
				? `<span class="fam">${esc(g.doc.family)}</span>`
				: "";
			const range = g.doc.pageStart
				? `p.${g.doc.pageStart}–${g.doc.pageEnd}`
				: "";
			const pages = isCur
				? `<div class="pages">${g.idxs
						.map((gi) => {
							const pp = data.pages[gi];
							const st =
								gi === idx
									? " cur"
									: pp.review?.flag
										? " flag"
										: pp.review?.reviewed
											? " done"
											: "";
							const mk = pp.review?.flag ? "⚑" : pp.review?.reviewed ? "✓" : "";
							return `<button class="pageitem${st}" data-idx="${gi}">p.${pp.page}<span class="mk">${mk}</span></button>`;
						})
						.join("")}</div>`
				: "";
			return `<button class="docitem${cur}${done}" data-first="${g.first}">
        <span class="doctitle"><span class="docn">${n + 1}.</span> ${esc(g.doc.title)}</span>
        <span class="docmeta">${fam}${range} · ${g.reviewed}/${g.total}</span>
      </button>${pages}`;
		})
		.join("");

	const famBadge = p.document.family
		? `<span class="fam">${esc(p.document.family)}</span>`
		: "";
	app.innerHTML = `
    <aside class="docs">
      <div class="docs-h">Case contents — ${esc(data.case)}</div>
      ${sidebar}
    </aside>
    <section class="pane">
      <section class="score-bar${p.review?.reviewed ? " done" : ""}">
        <span class="doc">${esc(p.document.title)} ${famBadge}</span>
        <span class="score">lawnlord <b>${myScore}</b>/100</span>
        <span class="note">${esc(p.note)}</span>
        <span class="pageid">${esc(p.image)} · p.${p.page}${p.review?.reviewed ? " · ✓ reviewed" : ""}</span>
      </section>
      <section class="compare">
        <figure><figcaption>ACTUAL — original filing</figcaption><img src="${p.actual}" alt="actual page" /></figure>
        <figure><figcaption>RECONSTRUCTED — from the data</figcaption><img src="${p.reconstructed}" alt="reconstructed page" /></figure>
      </section>
      <section class="review">
        <label class="rng">
          <span class="bad">bad</span>
          <input id="rating" type="range" min="0" max="100" value="${rating}" />
          <span class="good">good</span>
          <output id="rval">${rating}</output>
        </label>
        <div class="gap">gap vs lawnlord: <b id="gap">${rating - myScore}</b></div>
        <textarea id="notes" placeholder="specific feedback / notes">${p.review ? esc(p.review.notes) : ""}</textarea>
        <label class="flag"><input id="flag" type="checkbox"${p.review?.flag ? " checked" : ""} /> flag this page</label>
        <div class="actions">
          <button id="prev"${idx === 0 ? " disabled" : ""}>‹ prev</button>
          <button id="save" class="primary">mark reviewed &amp; next ›</button>
          <button id="next"${idx === data.pages.length - 1 ? " disabled" : ""}>skip ›</button>
        </div>
      </section>
    </section>`;
	wire(p, myScore);
}

function wire(p: Page, myScore: number): void {
	const ratingEl = document.getElementById("rating") as HTMLInputElement;
	const rval = document.getElementById("rval") as HTMLElement;
	const gap = document.getElementById("gap") as HTMLElement;
	ratingEl.oninput = () => {
		rval.textContent = ratingEl.value;
		gap.textContent = String(Number(ratingEl.value) - myScore);
	};
	for (const el of document.querySelectorAll(".docitem")) {
		(el as HTMLButtonElement).onclick = () => {
			idx = Number((el as HTMLElement).dataset.first);
			render();
		};
	}
	for (const el of document.querySelectorAll(".pageitem")) {
		(el as HTMLButtonElement).onclick = () => {
			idx = Number((el as HTMLElement).dataset.idx);
			render();
		};
	}
	document.querySelector(".pageitem.cur")?.scrollIntoView({ block: "nearest" });
	(document.getElementById("prev") as HTMLButtonElement).onclick = () => {
		if (idx > 0) idx--;
		render();
	};
	(document.getElementById("next") as HTMLButtonElement).onclick = () => {
		if (idx < data.pages.length - 1) idx++;
		render();
	};
	(document.getElementById("save") as HTMLButtonElement).onclick = async () => {
		const notes = (document.getElementById("notes") as HTMLTextAreaElement)
			.value;
		const flag = (document.getElementById("flag") as HTMLInputElement).checked;
		const rating = Number(ratingEl.value);
		await fetch("/api/review", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ id: p.id, rating, notes, flag }),
		});
		p.review = { rating, notes, flag, reviewed: true };
		if (idx < data.pages.length - 1) idx++;
		render();
	};
}

load();
