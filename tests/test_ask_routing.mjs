/* The browser loads web/ask.js with a plain <script> tag, so the file cannot
   use ESM or CJS syntax that a browser would choke on. The test evaluates it
   the same way the browser does: as a script, in a scope of its own. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "web", "ask.js"), "utf8");
const sandbox = {};
new Function("globalThis", "window", src).call(sandbox, sandbox, sandbox);
const { askIntent } = sandbox;

let pass = 0, fail = 0;
const is = (got, want, label) => {
  if (got === want) { pass++; return; }
  fail++;
  console.log(`FAIL ${label}\n     got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
};

// The bug this file exists for: the founder is the one raising.
is(askIntent("I'm raising a Series A for Gosta Labs").view, "founder", "raising -> founder");
is(askIntent("raising for Gosta Labs").view, "founder", "raising for X");
is(askIntent("Gosta Labs Series A").view, "founder", "company + stage");
is(askIntent("screen my investor list").view, "founder", "screen");
is(askIntent("who should I meet at Slush").view, "founder", "who should I meet");

// ...and it must not swallow the genuine investor-side questions.
is(askIntent("who are insiders doubling down on?").view, "investor", "doubling down");
is(askIntent("who is raising without announcing it?").view, "investor",
   "raising without announcing beats raising");
is(askIntent("insider conviction").view, "investor", "insider conviction");
is(askIntent("show me stealth rounds").view, "investor", "stealth");

// Map, but not on a stray "where".
is(askIntent("map the Slush 2026 floor").view, "map", "map the floor");
is(askIntent("show the map").view, "map", "show the map");
is(askIntent("where are the funds").view, "map", "where are");

// Lookup verbs carry a term.
is(askIntent("find Lifeline Ventures").view, "lookup", "find X");
is(askIntent("find Lifeline Ventures").term, "Lifeline Ventures", "term stripped of verb");
is(askIntent("find Lifeline Ventures").kind, null, "fund-ish name is not a person");
is(askIntent("who is Ilkka Paananen").kind, "people", "person-ish lookup");
is(askIntent("find").view, "founder", "a verb with no term is not a lookup");

// A bare name defaults to screening, and admits it is a default.
is(askIntent("Gosta Labs").view, "founder", "bare name");
is(askIntent("Gosta Labs").confident, false, "bare name is not a confident parse");
is(askIntent("").view, null, "empty");

// A sentence names a company and a stage; both used to be thrown away.
is(askIntent("I'm raising a Series A for Gosta Labs").term, "Gosta Labs", "company out of a sentence");
is(askIntent("I'm raising a Series A for Gosta Labs").stage, "series a", "stage out of a sentence");
is(askIntent("we are raising seed for Neko Health").term, "Neko Health", "we are raising seed");
is(askIntent("raising for Gosta Labs").term, "Gosta Labs", "short form");
is(askIntent("Gosta Labs Series A").term, "Gosta Labs", "company then stage");
is(askIntent("Gosta Labs Series A").stage, "series a", "stage after the name");
is(askIntent("Gosta Labs").term, "Gosta Labs", "bare name survives intact");
is(askIntent("Gosta Labs").stage, null, "no stage claimed when none given");
is(askIntent("screen my investor list").term, "screen my investor list", "nothing to extract");

console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
