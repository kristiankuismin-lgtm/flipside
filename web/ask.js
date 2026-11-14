/* What did the user actually ask for?
 *
 * The first version matched keywords in a fixed order, so the first pattern
 * to fire won. "I'm raising a Series A for Gosta Labs" contains "raising",
 * which was on the investor list, and the most common query in the product
 * routed to the wrong view. "Where should I raise?" hit "where" and opened
 * the map.
 *
 * This scores every intent and takes the strongest, so one incidental word
 * cannot outvote a phrase. It is a pure function with no DOM, so it is
 * tested directly.
 */
(function (root) {
  "use strict";

  // Phrases are worth more than words: "doubling down" is a request for the
  // conviction view, "down" is not.
  const RULES = [
    ["map", [
      [/\b(?:on|open|show|see)\s+the\s+map\b/, 6],
      [/\bmap\b/, 4],
      [/\b(?:slush\s+)?floor\b/, 3],
      [/\bwhere\s+(?:are|is)\b/, 3],
      [/\b(?:geograph|atlas|nearby|near me)\w*/, 3],
    ]],
    ["investor", [
      [/\binsider\s+conviction\b/, 7],
      [/\b(?:doubling|double)\s+down\b/, 6],
      [/\bwithout\s+announcing\b/, 6],
      [/\b(?:unannounced|stealth|quietly|silently)\b/, 5],
      [/\bconviction\b/, 4],
      [/\binsiders?\b/, 3],
      [/\borphan\w*/, 3],
      [/\bdeal\s?flow\b/, 3],
    ]],
    ["lookup", [
      [/^(?:find|open|look\s+up|search\s+for|show\s+me)\s+\S/, 6],
      [/^(?:who|what)\s+(?:is|are)\s+\S/, 5],
      [/^tell\s+me\s+about\s+\S/, 5],
    ]],
    ["founder", [
      [/\b(?:screen|shortlist|target\s+list|who\s+should\s+(?:i|we)\s+(?:meet|pitch|talk))\b/, 6],
      // The founder is the one raising. This word used to send them away.
      [/\b(?:raising|raise|round|series\s+[a-d]\b|seed\b|pre-?seed\b)/, 4],
      [/\b(?:investors?|funds?|vcs?)\b/, 2],
    ]],
  ];

  const VERB = /^(?:find|open|look\s+up|search\s+for|show\s+me|who\s+is|who\s+are|what\s+is|tell\s+me\s+about)\s+/i;
  const PERSONISH = /\b(?:founder|ceo|cto|partner|person|people|who\s+is)\b/i;
  const FUNDISH = /\b(?:ventures?|capital|partners?|fund|invest|equity|vc)\b/i;

  function score(q) {
    const low = (q || "").toLowerCase();
    const out = {};
    for (const [view, pats] of RULES) {
      let s = 0, hit = null;
      for (const [rx, w] of pats) {
        if (rx.test(low) && w > s) { s = w; hit = rx; }
      }
      out[view] = { score: s, matched: hit && String(hit) };
    }
    return out;
  }

  function askIntent(q) {
    const text = (q || "").trim();
    if (!text) return { view: null, term: "", why: "empty" };

    const s = score(text);
    let view = "founder", best = 0;
    for (const k of Object.keys(s)) {
      if (s[k].score > best) { best = s[k].score; view = k; }
    }

    // A bare name is the commonest input of all and matches nothing. Screening
    // it is the right default, but say so rather than pretending we parsed it.
    if (best === 0) {
      return { view: "founder", term: text, confident: false,
               why: `read as a company to screen investors for` };
    }

    if (view === "lookup") {
      const term = text.replace(VERB, "").trim();
      // "show me stealth rounds" opens with a lookup verb but is not a
      // lookup. Score what follows the verb: if it names a view, that wins.
      const rest = score(term);
      let restView = null, restBest = 0;
      for (const k of Object.keys(rest)) {
        if (k !== "lookup" && rest[k].score > restBest) {
          restBest = rest[k].score; restView = k;
        }
      }
      if (restView && restBest >= 4) {
        return { view: restView, term: text, confident: true,
                 why: { map: "showing the map",
                        investor: "reading the graph from the investor side",
                        founder: "screening investors" }[restView] };
      }
      if (term.length < 2) {
        return { view: "founder", term: text, confident: false,
                 why: "nothing to look up after the verb" };
      }
      return {
        view: "lookup", term, confident: true,
        kind: PERSONISH.test(text) && !FUNDISH.test(term) ? "people" : null,
        why: `looking up "${term}"`,
      };
    }

    const why = {
      map: "showing the map",
      investor: "reading the graph from the investor side",
      founder: "screening investors",
    }[view];
    return { view, term: text, confident: best >= 4, why };
  }

  root.askIntent = askIntent;
  root.askScore = score;
  if (typeof module !== "undefined" && module.exports) module.exports = { askIntent, askScore: score };
})(typeof globalThis !== "undefined" ? globalThis : this);
