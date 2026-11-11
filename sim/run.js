// bg-coach combat simulator runner (wraps Firestone's simulator; personal local use).
// stdin: one JSON battle per line ({"id":..., "battle": <BgsBattleInfo>})
// stdout: one JSON result per line ({"id":..., "win":..,"tie":..,"loss":..,"dmgWon":..,"dmgLost":..,"n":..})
// Card data is downloaded once and cached in ./cards_cache.json (refreshed after 3 days).
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const sim = require('@firestone-hs/simulate-bgs-battle');
const { AllCardsService } = require('@firestone-hs/reference-data');
const prepare = require('@firestone-hs/simulate-bgs-battle/dist/prepare-battle-cards-data');

const CACHE = path.join(__dirname, 'cards_cache.json');

async function loadCards() {
  const cards = new AllCardsService();
  let fresh = false;
  try {
    const st = fs.statSync(CACHE);
    fresh = Date.now() - st.mtimeMs < 3 * 24 * 3600 * 1000;
  } catch (_) { /* no cache yet */ }
  if (fresh) {
    cards.initializeCardsDbFromCards(JSON.parse(fs.readFileSync(CACHE, 'utf8')));
  } else {
    await cards.initializeCardsDb();
    fs.writeFileSync(CACHE, JSON.stringify(cards.getCards()));
  }
  sim.assignCards(cards);
  return cards;
}

function run(cards, battle) {
  const cardsData = prepare.prepareBattleCardsData(battle, cards);
  const it = sim.simulateBattle(battle, cards, cardsData);
  let r = it.next();
  while (!r.done) r = it.next();
  const v = r.value || {};
  return {
    win: v.wonPercent, tie: v.tiedPercent, loss: v.lostPercent,
    dmgWon: v.averageDamageWon, dmgLost: v.averageDamageLost, n: v.simulationsRun,
  };
}

(async () => {
  const origLog = console.log;
  console.log = (...a) => process.stderr.write(a.join(' ') + '\n'); // keep stdout clean
  console.time = () => {}; console.timeEnd = () => {};
  const cards = await loadCards();
  const rl = readline.createInterface({ input: process.stdin });
  for await (const line of rl) {
    if (!line.trim()) continue;
    let id = null;
    try {
      const msg = JSON.parse(line);
      id = msg.id;
      origLog(JSON.stringify({ id, ...run(cards, msg.battle) }));
    } catch (e) {
      origLog(JSON.stringify({ id, error: String(e && e.message || e) }));
    }
  }
})();
