// Page-by-page review workflow: compare actual vs reconstructed, see lawnlord's
// score + note on top, then rate (good–bad range), note, and flag. Completing a
// page marks it human-reviewed. The point is the visible gap between lawnlord's
// score and the reviewer's rating.

type Review = {
	rating: number;
	notes: string;
	flag: boolean;
	reviewed: boolean;
} | null;

type Page = {
	id: string;
	image: string;
	page: number;
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

	app.innerHTML = `
    <section class="score-bar${p.review?.reviewed ? " done" : ""}">
      <span class="score">lawnlord score <b>${myScore}</b>/100</span>
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
