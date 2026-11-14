# Flipside

**Sijoittajat tekevät sinusta taustaselvityksen ennen sijoitusta. Flipside tekee sinulle saman sijoittajista.**

Liidaako se oikeasti? Pysyykö se mukana seuraavalla kierroksella? Onko se jo
rahoittanut kilpailijasi? Onko sillä rahaa juuri nyt? Jokainen luku lasketaan
Calan tietograafista — ei kielimallin arvio.

Junction 2026 · Cala "Make Unicorns Real"

---

## Miksi tätä ei voi googlata

Jokainen mittari on aggregaatti *yhteyksien yli*: sijoittaja → kierrokset →
yhtiöt → seuraavat kierrokset → yhteissijoittajat. Verkkohaku palauttaa
artikkeleita, ei osuuksia. Siksi tämä on rakennettu Calan graafin varaan.

## Mittarit

| | Mitä | Kynnykset |
|---|---|---|
| **M1** Liidausosuus | Osuus kierroksista, jotka sijoittaja **liidasi** | 🟢 ≥40 % · 🟡 15–40 % · 🔴 <15 % |
| **M2** Follow-on | Osallistuuko portfolioyhtiön *seuraavaan* kierrokseen | 🟢 ≥60 % · 🟡 35–60 % · 🔴 <35 % |
| **M2b** Portfolion eteneminen | Osuus, joka nosti seuraavan kierroksen 24 kk:ssa | 🟢 ≥55 % · 🟡 35–55 % |
| **M3** Konflikti | Onko Calan nimeämä kilpailijasi portfoliossa | 🔴 suora · 🟡 läheinen ala · 🟢 puhdas |
| **M4** Sijoitustahti | Uudet sijoitukset 6 kk vs. aiempi tahti | 🟢 ≥1,0 · 🟡 0,5–1,0 · 🔴 <0,5 |

M2 ottaa mukaan vain yhtiöt, joiden sisääntulokierros on vähintään 18 kk vanha:
nuoremmilla ei ole ollut aikaa nostaa seuraavaa.

## Kolme sääntöä, joista ei jousteta

**Tuntematon ei ole nolla.** ⚪ tarkoittaa ettei dataa ole. 🔴 on väite
sijoittajasta, ⚪ on väite omasta datastamme. Niiden sekoittaminen olisi valhe.

**Alle 3 kierrosta → ei rankata.** Sijoittaja, josta ei ole dataa, ei saa
näyttää keskinkertaiselta. Se näkyy erikseen merkinnällä "ei tarpeeksi dataa".

**Säännöt päättävät, malli vain kirjoittaa.** `numbercheck.py` hylkää
kielimallin tekstin, jossa on luku jota ei löydy lasketuista mittareista.

## Mikä on live, mikä esilaskettu

| Osa | Tila |
|---|---|
| M1, M2, M4 | **Laskettu** Calan datasta, esilaskettu cacheen |
| M3 konfliktit | **Laskettu** Calan kilpailija- ja portfoliodatasta |
| Kierros- ja portfoliodata | **Esilaskettu** — Calan kyselyt kestävät 20–60 s, joten demo ei voi tehdä niitä lennossa |
| Lähteistys per väite | **Osittain** — `query` ei palauta rivitason lähteitä, `search` palauttaa |
| M5 lämmin reitti | **Suunniteltu** — Calassa on työsuhteet päivämäärineen |
| Slush-tila | **Suunniteltu** — Slush 2026 on Calassa tapahtuma osallistujineen |

Demo ajetaan `CALA_CACHE_ONLY=1`, jolloin cache-miss raportoidaan rehellisesti
puuttuvana datana eikä peitetä nollana.

## Mitä Calan rajapinnasta opimme

**Cala QL on kielimallin tulkitsema, eikä se ole deterministinen skeemaltaan.**
Sama kysely palautti eri kenttärakenteen eri sijoittajille:

```
funding_rounds.investors="Index Ventures"  -> {company, round, amount, date, role}
funding_rounds.investors="Lifeline Ventures" -> {company, round_type, amount, notes}   ei päivämäärää
funding_rounds.investors="Northzone"       -> {company, sector}                        ei kierroksia
```

Korjaus: **nimeä kentät kyselyssä eksplisiittisesti** luonnollisella kielellä.
Silloin skeema vakautuu. Tämä nosti kattavuuden 3/8 → 28/30 sijoittajaa.

Sama koski yhtiökyselyä: `return(round,date,amount,investors)` tiivisti
siemenkierrokset muotoon `"Angel investors"` ja hukkasi juuri siemenrahastot.
Eksplisiittinen kysely antoi samoista kierroksista Lifelinen ja Inventuren nimeltä.

Jäljelle jäävä vaihtelu, jota jäsennin sietää: liidikenttä on milloin
`role: "Lead"`, milloin `led_by_lifeline: true`, milloin `northzone_led: "Yes"`.

## Ajaminen

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
echo "CALA_API_KEY=..." > .env

.venv/bin/python recon.py                              # API-kartoitus
.venv/bin/python precompute.py investors.txt           # täytä cache (~35 min)
.venv/bin/python precompute_portfolios.py 2            # portfoliot M3:lle

CALA_CACHE_ONLY=1 .venv/bin/python -m uvicorn app.api:app --port 8077
```

`http://localhost:8077` — käyttöliittymä on yksi tiedosto ilman build-vaihetta
ja ilman CDN-riippuvuuksia, joten demo toimii myös ilman verkkoa.

## Testit

```bash
.venv/bin/python -m pytest tests/ -q
```

Testit eivät kutsu Calaa. Jokaiselle löydetylle bugille on regressiotesti —
muun muassa nimien normalisoinnille (`Index Ventures` ≠ `Index Ventures LLP`
kaatoi aiemmin jokaisen mittarin hiljaa nollaan) ja skeemavaihtelulle.
