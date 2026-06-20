# Brainfuck Tetris — Tervdokumentum (spec)

- **Dátum:** 2026-06-19
- **Állapot:** Jóváhagyásra vár (brainstorming → spec)
- **Cél:** Valós idejű, terminálos Tetris, amit egy *tiszta Brainfuck* program (`tetris.bf`) hajt, BF-tematikus „fúziós" csavarral.
- **Siker fő mércéje (a felhasználó választása):** *technikai bravúr* — korrekt, valódi, futó Brainfuck; a „wow, ez tényleg BF" a fő érték.

> **A terv verifikált.** A kulcs-feltevéseket egy 6-ágenses kutató + adverzariális kritikai workflow ellenőrizte, több rutint a célgépen (Python 3.12.10, Windows 10) ténylegesen lefuttatva. A verdikt: **MEGVALÓSÍTHATÓ**. A hivatkozások a dokumentum végén.
>
> **A legnehezebb rész is bizonyított.** A futásidejű elem-alrendszert (scan-locate + relatív ütközés + feltételes mozgás + lock/spawn + sentinel-resync, többframe-es ciklus) valódi BF-fel **23/23 teszt** igazolta a 20×40-es kúton (~**37 450 lépés/frame** elem-logika). A tesztelt referencia-implementáció: `docs/superpowers/research/kernel-proofs/runtime-subsystem/` (`tetris.py`, `scan.py`, `layout.py`, `shapes.py`, `test_bcde.py`, `test_a_scan.py`, `test_frame_budget.py`). A 6. szekció erre épül.

---

## 1. Áttekintés és célok

Egy **20×40-es** (20 oszlop × 40 sor = **800 cella**), valós idejű Tetris fut egy **mellékelt host interpreterben** (`bf_run.py`), de a játéklogikát egy **tiszta `tetris.bf`** tartalmazza. A `tetris.bf`-et **nem kézzel** írjuk, hanem egy kis **DSL → Brainfuck fordító** (`build.py`) generálja — ez a bevett, bizonyított módja annak, hogy ekkora BF-et hibátlanul lehessen előállítani (lásd ELVM/elvi, ami egy teljes `vi` klónt fordít tiszta BF-re).

> **Miért 20×40 és miért fontos:** ekkora kútnál (800 cella) az abszolút indexelés O(n²)-es költsége elviselhetetlen lenne, ezért az elem-mozgás/ütközés **relatív-mutatós** modellt használ (a mutató a kúton „lovagol", a geometriát az anchortól fix relatív offszeten lévő „shadow" cellák hordozzák) — ez **mérettől független** (mozgás O(1), peek olcsó, elem-megtalálás lineáris). Lásd 6. szekció.

**Scope (core Tetris):** 7 tetromino, 4 forgásállás, 7-bag spawn, sortörlés (1–4), pontszám, szint/sebesség-rámpa, `next` előnézet. **Pálya: 20×40.**

**A csavar (fúzió, részletek a 2. szekcióban):** (A) a kút **maga a BF memóriaszalag** egy régiója; (B) az elemek **BF-parancs glyph-ek**, a sortörlések egy **futtatható BF-programmá** állnak össze, ami a finálében **ténylegesen lefut**.

**Non-goals (kifejezetten kimarad):** SRS forgórendszer és kick-táblák; hold-queue; többszintű next-előnézet (egy `next` elég); hálózati/leaderboard; nem-Windows finomhangolás (a host Windows-ra van szabva, de a `.bf` szabványos BF).

**Kész-definíció:** `run.cmd` → valós időben játszható core Tetris fut tiszta `tetris.bf`-ből; a kút láthatóan a BF-szalag; a sortörlések valódi BF-programot építenek; game over-kor ez + egy szerzői coda **ténylegesen lefut** és kiírja a pontszámot — minden a Brainfuckból. A fordító- és szubrutin-tesztek zöldek; egy scriptelt input-szekvencia determinisztikusan reprodukálható (CI smoke-teszt).

---

## 2. A csavar — pontos, őszinte megfogalmazás

**(A) A kút MAGA a memóriaszalag _(valódi)_.**
A 20×40 = 800 cellás játékteret a `tetris.bf` egy **összefüggő, 800 cellás szalagrégiója** tárolja. **+1 bias** kódolás: `1` = üres, `2..8` = lerakott elemkódok, `9` = aktív elem teste, `10` = aktív elem anchora; a `0` strukturálisan fenntartott (sentinel a well két szélén, a `[<]`/`[>]` resync-hez). A renderelés közvetlenül ezekből a cellákból rajzol (érték − bias). Ez nem dísz: a pálya szó szerint a BF-memória egy ablaka. Ezt a modellt létező pure-BF játékmotor is használja (brainfuck-game-engine: a képernyő az első cellákból).

**(B) Az elemek BF-parancsok, amik futtatható programmá állnak össze _(valódi + kontrollált)_.**
A 7 tetromino egy-egy BF-parancs glyph-et kap, és minden cellájában azt rajzolja. A leképezés:

| elem | I | O | T | S | Z | J | L |
|---|---|---|---|---|---|---|---|
| glyph | `>` | `<` | `+` | `-` | `.` | `[` | `]` |

A `,`-t szándékosan kihagyjuk (a felépített programnak nincs szüksége bemenetre — lásd 13).
Sortörléskor a kitörölt cellák parancs-karakterei egy **„Assembled program" pufferbe** fűződnek.

**Érvényesség-garancia (zárójel-balanszírozás):** glyph-hozzáfűzéskor a puffer karbantart egy mélység-számlálót: a `depth==0`-nál érkező `]`-t **eldobja**, a végén a nyitva maradt `[`-ekhez **pótol** annyi `]`-t. Ez bizonyítottan érvényes, elemezhető programot ad.

**Őszinte kitétel:** a balanszírozás **újrarendezhet/eldobhat** glyph-eket (pl. `][+[` → `[+[]]`), ezért a felépített dolog **„a sortörléseidből származtatott, garantáltan érvényes BF program", nem szó szerinti átirat.** A technikai-bravúr narratíva ettől sértetlen, de a UI/README ezt így fogalmazza.

**A finálé (13. szekció):** game over-kor a host a (balanszírozott) assembled programot **lefuttatja a saját VM-én, homokozóban** (külön szalagrégió, lépés-limit, dp-clamp, output-cap), megmutatja a forrását és kimenetét, majd egy rövid **szerzői, tiszta-BF coda** kiírja a `GAME OVER`-t és a pontszámot (BCD-ből). Minden, amit látsz, Brainfuckból jön.

> **Megkülönböztetés:** a puffer *gyarapodása* **emergens** (a valódi sortörléseidből), a pontszám-kiírás **szerzői** (hogy garantáltan olvasható legyen). Mindkettő 100% Brainfuck.

---

## 3. Architektúra — három réteg

### ① `build.py` — DSL → Brainfuck fordító *(build-idő, nem fut a játékban)*
Magas szintű, olvasható forrásból (nevesített cellák/„változók" + makrók) **tiszta `tetris.bf`-et** generál. A fordító és a generált `.bf` is a repóba kerül.

### ② `bf_run.py` — host VM / „mellékelt interpreter" *(futásidő)*
Brainfuck VM: 8-bites körbeforduló cellák, ≥32 768 cellás `bytearray` szalag, **előfordított utasításlista** (run-length `+ - < >`, előre kiszámolt zárójel-ugrások, `[-]` clear-opt). Méréssel ~2,6–2,7M op/mp a célgépen — bőven elég. Továbbá: nem-blokkoló billentyűzet (`msvcrt`), Windows VT-engedélyezés, frame-ütemezés, és a finálé homokozott futtatása.

### ③ `tetris.bf` — a játék *(②-ből generálva, tiszta BF)*
A teljes játéklogika + a render (ANSI) + a csavar. **Maga rajzol** ANSI escape-ekkel; a host csak bájtokat továbbít.

**Adatfolyam:** `build.py` → `tetris.bf` (build-idő). Futáskor: `run.cmd` → `bf_run.py` betölti a `.bf`-et → BF fő ciklus (egy iteráció = egy frame: input-poll → gravitáció → ütközés/lock → sortörlés+puffer → render) → game over: puffer + pontszám → host futtatja a finálét.

---

## 4. Tape-memóriatérkép (kötelező, fix abszolút címek)

A `build.py` allokátora **fix abszolút cella-indexet** ad minden régiónak/változónak. **Két régió sem fedhet át.** A kritikus szabályok (a kutatás + a verifikált alrendszer igazolta):

- A **decimális-kiíró / divmod rutinok 8 cellát fogyasztanak a vizsgált cellától JOBBRA, és nullázzák azokat.** Ezért **minden** szám-kiíró helynek kell egy **≥8 nullázott cellás jobb-scratch zóna**, és ez **soha nem eshet a well régióra** vagy más adatra.
- A well **+1 bias**-szal van kódolva (üres=1, lerakott=2..8, aktív test=9, anchor=10), a `0` strukturálisan fenntartott: a well **közvetlen bal szomszédja `LEFT_SENT` (mindig 0)**, jobb oldalon `RIGHT_SENT` (mindig 0). Így a `[<]` a well bármely cellájáról **garantáltan a `LEFT_SENT`-re** áll meg (resync abszolút cellára), és nincs „legitim 0 az adatban" csapda.

**Régiók (a verifikált `layout.py` alapján; sorrend rögzített):**

| Régió | Méret (cella) | Megjegyzés |
|---|---|---|
| regiszterek + scratch | ~0..29 | abszolút elérhető: `R_PX,R_PY,R_ROT,R_PIECE,R_NEXT,R_COLLIDE`, `score_bcd`, `lines_bcd`, `level`, `gravity_tick`, `drop_period`, `rng_state(2)`, `frame_ctr`, `input_last`, `print_scratch(≥8 jobbra null)`, `ansi_scratch(1–2)`, `tmp0..tmp7` |
| `LEFT_SENT` | 1 | mindig `0` — a `[<]` resync célja |
| `well` | **800** | 20×40, **+1 bias** (1=üres, 2..8=lerakott, 9=aktív test, 10=anchor). Összefüggő. `cell(x,y)=WELL_BASE+y*20+x` |
| `RIGHT_SENT` | 1 | mindig `0` — a `[>]` resync célja |
| **shadow-cellák** | — | `R_PX/R_PY/R_ROT` az anchor**hoz képest fix relatív offszeten** is jelen vannak (a geometria az anchorral utazik); így minden ütközés/mozgás **fordítási-idejű relatív** címzéssel megy, futásidejű abszolút indexelés nélkül |
| `asm_buf` | N (pl. 256) | összeállított program puffer + `asm_depth` mélység-számláló |

**Nincs `shape_table`:** az alakzatokat **fordítási-idejű branch-dispatch**-csel kérjük le (7×4 ág, mindegyik beégeti a 4 elemcella-offszetet/maszkot) — nincs futásidejű táblaindexelés. Verifikált (C megközelítés, ~3,5k lépés worst). Lásd `kernel-proofs/runtime-subsystem/shapes.py` és a kernel-kör `emit_shape.py`-ja.

A `build.py` egy **memória-térkép artefaktumot** (`tests/memory_map.txt`) is kiír, és assertálja az átfedés-mentességet build-időben.

---

## 5. A fordító fegyelme és a verifikált BF-idiómák

**Goto-emitter (kötelező):** minden változó fix abszolút index; egy globális `cursor` egész követi a mutatópozíciót; `goto(name)` pontosan `abs(target-cursor)` darab `>`/`<`-t emittál és frissíti a `cursor`-t. **Tilos kézzel számolni a `>`/`<`-t** az idiómákon belül — a kutatás bizonyította, hogy a kézi számolás az #1 csendes hibaforrás (az egyenlőség-idióma kézzel elromlott, goto-emitterrel átment).

**Pointer-neutralitás:** minden makró vagy pointer-neutrális, vagy dokumentált belépő/kilépő cellája van, és **minden makró után cursor-assertet** teszünk.

**Build-idejű Python BF-oracle:** a `build.py` egy beépített ~25 soros referencia-VM-mel **önteszteli minden emittált idiómát** a teljes `tetris.bf` összeállítása előtt. Így a hibák build-időben buknak ki.

**Verifikált idiómák (8-bites wrapping; mind lefuttatva a kutatásban) — ezek a `build.py` primitívjei:**
- `clear`: `[-]`
- `set N`: plusz-sor, nagy konstansra szorzó-hurok (`+++[>+++++++++<-]>` ≈ 27 az ESC-hez)
- `move x→y`: `x[y+x-]`
- `copy x→y (tmp t)`: `t[-] x[y+t+x-] t[x+t-]`
- `add x+=y`, `sub x-=y` (tmp-vel, lásd idiómalista)
- `mul x*=y` (tmp0,tmp1) — **csak setup/score, sosem a hot pathon** (O(érték) lépés)
- `eq x=(x==y)`, `neq`, `gt z=(x>y)` (ais523, wrapping-függő, destruktív — operandust előbb másolni)
- `if(x){...}`, `if-else` (Jeffry Johnston, tmp0/tmp1), `while`, `do-while`
- **decimális kiírás (0–255, forrást megőrzi)** — az esolangs `itchyny` rutin verbatim; 8 cellát fogyaszt jobbra
- **érték-scan** (`-N [ +N > -N ]` minta a unikális marker-cellára) + **relatív szekció** + **`[<]` sentinel-resync** — a futásidejű elem-alrendszer alapkövei (6. szekció, verifikálva). *(A korábbi „move pointer N cells / computed-offset" megközelítést elvetettük: O(n²).)*

A `build.py` codegen-mintái az esolangs „Brainfuck code generation/constants" oldalakat követik (hatékony konstans-emittálás szorzó-hurokkal, copy/move temp-pel). Opcionális peephole-pass (futáshűségelt run-collapse, `[-]` felismerés) a méret/sebesség csökkentésére — nem feltétel a korrektséghez.

---

## 6. A futásidejű elem-alrendszer — relatív-mutatós modell *(a projekt legnehezebb darabja — VERIFIKÁLVA, 23/23)*

> A korábbi terv abszolút computed-offset indexelést tételezett; a kutatás mérte, hogy az **O(n²)** (800 cellánál elviselhetetlen). Ezt **lecseréltük** a lent leírt **relatív-mutatós** modellre, amit valódi BF-fel **23/23 teszt** igazolt. Referencia: `docs/superpowers/research/kernel-proofs/runtime-subsystem/`.

**Kulcs-ötlet:** a data pointer **a kúton lovagol** (fizikailag az aktív elem **anchor** celláján áll), és a geometriát (px, py, rot) az anchor**hoz képest fix relatív offszeten** lévő **„shadow" cellák** hordozzák. Így minden ütközés/mozgás/peek **fordítási-idejű relatív** címzéssel megy (`dy*20+dx` konstans az anchortól) — **nincs futásidejű abszolút indexelés**, a költség mérettől független.

**A frame elem-fázisa (mind verifikált):**
- **(A) scan-locate** — `WELL_BASE`-ről egy **érték-scan** a unikális `10` (anchor) cellára áll; nem-destruktív, **O(cella)** (~278 lépés fent, ~19,5k lent a 39. sorban). A pointer „felszáll" az anchorra, a fordító **relatív szekcióba** lép (lokál offszet 0 = anchor).
- **(B) ütközés** — a falak/padló **futásidejű (px,py) összehasonlítással** (olcsó eq/gt a regiszterekből); a lerakott cellákkal **relatív peek**-kel (a 4 elemcella az anchortól fix offszeten). Nem-destruktív a wellre. (Tipikus blokkolt teszt ~22–74k lépés.)
- **(C) feltételes mozgás** — ha nincs ütközés: a régi markerek törlése, az újak beírása, a shadow (px/py/rot) frissítése, a pointer az **új anchorra** kerül. (Tipikus engedett mozgás ~36k lépés.)
- **(D) lock & spawn** — lefelé-ütközéskor az aktív markerek lerakott azonosítóvá válnak; majd új elem markerei a tetején, shadow reset. (~19,9k lépés.)
- **(E) resync** — `[<]` a `LEFT_SENT`-re (ismert abszolút cella), így a render/HUD-fázis **statikus offszetekkel** futhat; a következő frame scan-locate-je újra megtalálja a (közben elmozdult) elemet. **A ciklus zár** (≥2 frame igazolva, ~37 450 lépés/frame).

**Alakzatok (forgatás):** a 7×4 állás **fordítási-idejű branch-dispatch**-csel (nincs tábla, nincs futásidejű indexelés; C megközelítés, ~3,5k lépés worst). Forgatás + **egyszerű wall-kick**: ha az új állás ütközik, próba 1 balra, majd 1 jobbra; ha úgy is ütközik, a forgatás elmarad. (Nincs SRS.)

**Implementációs irány:** a `tetris.bf` ezen alrendszerét a **verifikált referencia portolásával** építjük (`runtime-subsystem/tetris.py, scan.py, layout.py, shapes.py`), **nem** újra-levezetéssel; a `build.py` Python-oracle-je minden portolt makrót újra-leigazol.

---

## 7. Pontszám, szint, sorok — BCD

A pontszám meghaladhatja a 255-öt, a cellák 8-bitesek → **BCD** (a kutatás igazolta, hogy ez a helyes út; a multi-cell bináris→decimális osztás BF-ben kerülendő).

- `score_bcd`: 6 decimális számjegy-cella (MSD balra) + carry/temp. Növelés **ripple-carry** primitívvel (a kutatásban kimerítően tesztelve: `digit += carry; if digit==10 → 0, carry tovább`).
- Kiírás: minden számjegyhez `+48`, output, **vezető-nulla elnyomással** (a kiíró rutin flag-trükkje).
- `lines_bcd` és `level` ugyanígy (kis BCD/egy cella, ugyanaz a carry-primitív).
- Pontozás: 1/2/3/4 sor → pl. 40/100/300/1200 × (szint+1), klasszikus. Szint: minden 10 sor után +1; `drop_period` csökken.

---

## 8. Megjelenítés — ANSI a Brainfuckból + host output

**A `tetris.bf` rajzol**, ANSI escape-bájtokkal (ESC=27 majd `[` …). Precedens: Bosman mandelbrot.b teljes ASCII-képet rajzol pure BF-ből.
- **Frame-elv:** `ESC[H` (kurzor home) a frame elején, majd **soronként streamelt** sorok (NEM cellánkénti `ESC[y;xH` — az sokkal több bájt). Színváltáskor `ESC[3<szín>m`, reset `ESC[0m`.
- **Glyph-render (a csavar lényege):** a 20×40 = 800 well-cellát soronként rajzoljuk; minden kitöltött cella az elem **literál BF-glyph-jét** mutatja (`> < + - . [ ]`), elemenként színezve (7 szín). Üres = halvány `.`. A cella **biased** (érték − 1 a logikai elemkód; üres = bias `1`); az aktív elem (9/10) saját glyph-ekkel jelenik meg.
- **Méret-megjegyzés:** 800 cella/frame több kimenet, mint egy 10×20-as pálya — ezért a host egy `write/flush`/frame, az SGR-churn minimalizálás és (ha kell) a 30→20 fps hangolás itt fontos.
- **ANSI bájt-építés:** dedikált `ansi_scratch` cellá(k)ban, **delta-kódolással** (csak az előző bájttól való különbséget add/von), a scratch ismert (0) értéken marad. A scratch **adattól távol**.

**Host output-kezelés (a valós perf-változó az output-mennyiség, nem a compute):**
- a `tetris.bf` a **teljes frame-et** építi; a host **minden relézett bájtot pufferel és frame-enként EGY `write()+flush`-t** ad (`sys.stdout.buffer`),
- **SGR-churn minimalizálás** (színkód csak színváltáskor),
- start: `ESC[?25l` (kurzor elrejt); kilépés: `ESC[?25h`,
- opcionális synchronized-output `ESC[?2026h/l`, ha a terminál tudja.

---

## 9. Bemenet-szerződés (`,`)

A host a `,`-t így valósítja meg: minden `,` végrehajtáskor `msvcrt.kbhit()`-tel őrzött `msvcrt.getwch()`; ha van billentyű, visszaadja (kisbetűs ASCII) és eltárolja `input_last`-ként; ha nincs, **`0`-t** ad (spec-szankcionált no-input érték).

- **Billentyűk:** `A`/`D` mozgás, `W` forgatás (CW), `S` soft-drop, `SPACE` hard-drop, `P` pause, `Q` kilépés, (opcionális `I` = tape-hexdump overlay, lásd 14).
- **KÖTELEZŐ desync-védelem:** ha a `getwch()` `'\x00'` vagy `'\xe0'` prefixet ad (funkció/nyíl-billentyű), **azonnal olvass be és dobj el** még egy `getwch()`-t, különben a maradék scan-kód a következő pollnál hamis mozgásként jelentkezik. (A játék csak ASCII-t használ, de a védelem kötelező.)
- **Egyértelműsítés:** definiált, mi történik, ha egy tickben SPACE (hard-drop) és S (soft-drop) is érkezik (hard-drop nyer); a `,` a legutóbbi billentyűt adja.

---

## 10. Időzítés és host frame-budget

- **Ütemezés:** fix ~30 fps, **abszolút-határidős** ciklussal (`next_tick += period; sleep(max(0, next_tick-perf_counter()))`) → drift-mentes. Python 3.11+ magas felbontású `time.sleep` (Windows waitable timer, 100 ns) — **a futtató ≥3.11 legyen** (3.12 a cél).
- **Gravitáció ≠ poll-ütem:** poll/render fix ~30 fps; az elem `drop_period` tickenként esik, `drop_period` a szinttel csökken → determinisztikus rámpa.
- **Mért budget (20×40, a verifikált alrendszerből):** az **elem-logika ~37 450 lépés/frame** (tipikus), worst ~74k (kút alja). Egy lépés ~0,46 µs (naiv interp, 2,17M/mp; a host előfordított VM-je gyorsabb a run-collapse miatt). A **render** (800 cella + ANSI) ezt kiegészíti — együtt reálisan **~20–30 fps** tartható; a fps cél hangolható (a `drop_period` ettől függetlenül determinisztikus).
- A **hot path increment/carry/relatív-peek** (tábla-mentes, abszolút-index-mentes); szorzás/osztás csak setup/score. **A generált `tetris.bf`-et kell profilozni** a worst-case-en (4 soros törlés + teljes redraw), nem csak a VM-et.

---

## 11. Windows konzol be- és kikapcsolás

- **VT engedélyezés** indításkor `ctypes`-szal: `h=GetStdHandle(-11); GetConsoleMode(h,&m); SetConsoleMode(h, m | 0x0004)` (a flaget az **eredeti módba ORozva**, az eredetit elmentve). Ha nem engedélyezhető → **tiszta hibaüzenettel ne induljon** (különben az ESC-bájtok szemétként jelennek meg).
- **Non-tty detektálás:** `sys.stdin.isatty()` → figyelmeztetés („valódi conhost/Windows Terminal ablakban futtasd"; IDE-beágyazott konzolban az `msvcrt`/SetConsoleMode rosszul viselkedhet).
- **Teardown (KÖTELEZŐ `try/finally`):** eredeti konzol-mód visszaállítása, kurzor vissza (`ESC[?25h`), `KeyboardInterrupt` elkapása (a Ctrl-C láthatatlan az `msvcrt`-nek) — a terminál sosem maradhat tört állapotban. Teszt: játék közbeni kilövés.

---

## 12. Véletlenszerűség (7-bag entrópia)

A pure BF determinisztikus → kell entrópiaforrás. **Választott megoldás (tiszta BF, dumb host):** egy `frame_ctr` szabadon fut (frame-enként +1); az **első billentyűlenyomás pillanatában** ennek értéke **beveti** a `rng_state` LFSR-t (16-bites xorshift/LFSR két cellában). A 7-bag ebből húz. Mellékhatás: az első néhány elem az első leütésig determinisztikus — elfogadható.
*(Alternatíva, ha mégis kérnéd: a host bájtokat injektál — de ez sérti a „dumb host + bájt-relé" tisztaságot. Lásd 19. nyitott döntések.)*

---

## 13. Az „assembled program" csavar + homokozó + finálé

**Összeállítás (élő):** sortörléskor a kitörölt cellák glyph-jei az `asm_buf`-ba fűződnek (balról jobbra, felső sor előbb). **Inkrementális balanszírozás** (a kutatás igazolta a helyességét): `depth` számláló; `depth==0`-nál a `]` eldobva; a végén `depth` darab `]` pótolva. Így a puffer **mindig futtatható**.

**Finálé (host-futtatott homokozó — NEM dbfi):** a kutatás egyértelműen ezt ajánlja (a dbfi self-interpreter ~400 BF-karakter, de lassú marker-szkenneléssel működik, ÉS ugyanúgy kell balanszírozás+lépés-limit). A homokozó három garanciája (mind standard, igazolt):
1. **bracket-balance** (már a pufferben),
2. **kemény lépés-limit** (sub-másodperces worst-case; eléréskor csendben leáll) — a *bounded halting* eldönthető,
3. **dp-clamp** `[0, tape_size)`-ra (igazolt: a `<` kezdetű puffer dp-alulcsordulást vált ki; védelem nélkül a Python negatív-indexszel az élő szalagba írna).

További: **izolált szalagrégió** (a score-celláktól külön), **output-cap** (a `.` ne árassza el a képernyőt), majd **`ESC[2J ESC[H`** a coda előtt.

**Bemutatás (hogy feat legyen, ne „szemét"):** a finálé először **megmutatja az (balanszírozott) assembled forrást** a panelen („A sortörléseidből fordított program — futtatás:"), lefuttatja (kimenet egy határolt mezőben), majd a **szerzői, tiszta-BF coda** törli a képernyőt és kiírja a `GAME OVER`-t + a pontszámot (BCD-ből, `+48`/output). A coda a `score_bcd`-t olvassa; futás előtt a dp ismert cellára áll.

**Opcionális „authenticity mode" (alapból KI):** a `<dbfi-forrás><assembled>!<input>` ugyanazon a host-VM-en, lépés-limit alatt — „BF futtat BF-et" flourish. Csak apró programra, mert lassú.

**Glyph-megjegyzés:** a `,` kimarad → az assembled program sosem olvas bemenetet (a tape-állapot mellett determinisztikus).

---

## 14. Tape inspector (feloldott terv)

A „watch BF think" élményt **olcsón és őszintén** adjuk (a kutatás megmutatta: 800 bájtérték frame-enkénti kiírása budget-robbantó, és a well összefüggősége ütközik a kiíró rutinnal):

- **A well maga már az egész 800 cellás régiót vizualizálja** (glyph-ekként) — ez a headline-igazság, ingyen.
- **A panel frame-enként, olcsón** mutat: a **„logikai fókusz" mutató** (a `R_PX/R_PY` regiszterekből származtatott, *külön követett* érték — őszinte és stabil, nem a valós dp, ami minden op-nál ugrálna; világosan így címkézve), és néhány **„regiszter" decimálisan**: pontszám (már BCD-számjegyek, olcsó), szint, sorok, aktuális/next elemkód, és a **fókusz-cella nyers bájtértéke** (egyetlen cellát `print_scratch`-be másolva, ott kiírva — sosem a wellben in-place).
- **Opcionális `I` overlay (szünetben):** teljes 800-cellás hex-dump; mivel a játék áll, **lehet lassú**.

---

## 15. Tesztelés

- **Fordító unit-tesztek:** minden makró (set/copy/add/mul/eq/if/while/print…) DSL→BF, majd a Python-oracle-en lefuttatva szalag-assert.
- **BF-szubrutin golden-tesztek:** alrendszerenként izolált VM-futtatás ismert szalag-állapotból → cella-assertek: **alakzat-dispatch minden (piece,rotation)-ra**, **scan-locate** (több pozíció, nem-destruktív, resync), **relatív ütközés** (fal/alj/halom, üres/teli/vegyes well), **feltételes mozgás + lock/spawn + többframe-ciklus** (a referencia `test_bcde.py`/`test_a_scan.py` portolása), sor-detektálás+lecsúsztatás, RNG-eloszlás, BCD ripple-carry + kiírás, balanszírozás, dp-clamp/lépés-limit a homokozóban.
- **Memória-térkép assert:** build-időben átfedés-mentesség + minden szám-kiíró hely jobb-scratch zónája tiszta.
- **CI smoke / önjáró teszt:** rögzített RNG-maggal scriptelt billentyű-szekvenciát futtatunk `bf_run.py`-on a generált `tetris.bf` ellen, és **assertáljuk a bájtfolyamban a konkrét ANSI-frame-eket** (pl. `ESC[H`, ismert pálya-állapot, pontszám-számjegyek). Ez a legerősebb „tényleg kész és játszható" bizonyíték (a korábbi „BF Tetris" próbálkozás befejezetlen maradt).

---

## 16. Inkrementális építési sorrend

Minden mérföldkő önállóan demózható és tesztelt — sosem ülünk egy 30 000 utasításos fekete dobozon.

1. **Fordító-mag + VM** — DSL alapmakrók + Python-oracle önteszt; host VM (optimalizált); „hello + ANSI-keret"; non-blocking input echo; VT be/teardown.
2. **Statikus render** — a 800 cellás (20×40) well kirajzolása a tape-ből (biased → glyph) + HUD-keret; logikai-fókusz mutató mozog.
3. **Egy elem, gravitáció, input** — egy elem esik, `A/D/W/S`, fal/alj-ütközés, lock; abszolút-határidős frame-loop.
4. **Teljes készlet + forgatás** — alakzat-**branch-dispatch** (tábla nélkül) + a **relatív elem-alrendszer portolása** (`runtime-subsystem/`: scan-locate, ütközés, mozgás, lock/spawn) profilozva, mind a 7 elem, 4 forgás, wall-kick, 7-bag, RNG (input-seed), `next`.
5. **Sortörlés + pontozás + sebesség** — 1–4 sor + lecsúsztatás, BCD pontszám/szint/sorok, rámpa, game-over.
6. **A csavar** — glyph-elemek, `asm_buf` élő gyarapodás + inkrementális balanszírozás, hard-drop, tape inspector regiszterei.
7. **Finálé** — homokozó (balance+limit+clamp+izoláció+output-cap), assembled forrás+kimenet, szerzői coda.
8. **Csiszolás** — színek, `--no-color` fallback, `I` overlay, sortörlés-villanás, README, CI smoke.

---

## 17. Kockázatok és őszinte kitételek

- **Méret/komplexitás:** nagy projekt; a fordító-réteggel megoldható és korrekt, de több lépcsős, tesztvezérelt munka — nem egy délután.
- **Hordozhatósági kitétel:** a `tetris.bf` *tiszta BF*, de a **valós idejű viselkedés host-kötött** (non-blocking `,` + ANSI-képes terminál). Sztenderd blokkoló/sor-pufferelt interpreterben nem lesz valós idejű (ez minden létező valós idejű BF-játék közös kitétele).
- **Computed-offset indexelés** a legkényesebb BF — kötelező oracle-önteszt + op-budget log.
- **Pointer-pozíció tracking** a `build.py`-ban globális állapot; egyetlen elcsúszó makró mindent ront → per-makró cursor-assert + VM round-trip.
- **Balanszírozás újrarendez** → „származtatott érvényes program", nem átirat (UI/README őszinte).
- **8-bit wrapping** minden cellaírásnál `&0xFF`; a `gt` idióma destruktív és wrapping-függő (operandust másolni).
- **Output-flooding/flicker** mitigáció: egy `write/flush` per frame, kurzor-elrejtés, SGR-minimalizálás, opc. synchronized-output.

---

## 18. Repó-elrendezés

```
brainfuck-tetris/
├─ src/                # a DSL-forrás (a játéklogika magas szinten)
├─ build.py            # DSL → tetris.bf fordító (goto-emitter + Python BF-oracle önteszt)
├─ tetris.bf           # GENERÁLT, tiszta Brainfuck (commitolva)
├─ bf_run.py           # host VM: opt. interpreter, raw input, VT, frame-ütem, homokozott finálé
├─ run.cmd / run.ps1   # Windows indító: python bf_run.py tetris.bf
├─ tests/              # fordító-unit + BF-szubrutin golden + memória-térkép + CI smoke
│  └─ memory_map.txt   # generált cellatérkép (átfedés-assert)
└─ README.md           # hogyan játszd, a csavar őszintén elmagyarázva, hogyan épül
```

---

## 19. Nyitott döntések (a spec-review-ra) — alapértékkel

Ezeket *megvalósítható alapértékkel* rögzítettem; a review-n felülbírálhatod:

1. **7-bag entrópia:** *input-időzítés-vetett PRNG (tiszta BF)* — vagy host-injektált bájtok (kevésbé tiszta)? **Alap: input-seed.**
2. **Tape inspector hatóköre:** *logikai-fókusz mutató + regiszterek + 1 fókusz-bájt frame-enként, `I`-overlay szünetben* — vagy több? **Alap: a leírt olcsó változat.**
3. **Mutató-indikátor:** *külön követett „logikai" érték* (stabil, őszintén címkézve) — vagy a valós dp (ugrál)? **Alap: logikai.**
4. **Forgórendszer:** *naiv 4 állás + egyszerű wall-kick (bal/jobb próba)* — vagy SRS+kick-táblák (sokkal több)? **Alap: naiv.**
5. **Host nyelv:** *Python 3.12* — vagy Node a sebességért (a `.bf` változatlan)? **Alap: Python.**
6. **„Authenticity mode" (dbfi, BF-futtat-BF):** *alapból KI*, opcionális flourish. **Alap: KI.**

---

## Hivatkozások (a kutatás verifikálta)

- Esolang **Brainfuck** spec (cellaméret, wrapping, no-input=0): https://esolangs.org/wiki/Brainfuck
- Esolang **Brainfuck algorithms** (idiómák, divmod, decimális kiírás, indexelés): https://esolangs.org/wiki/Brainfuck_algorithms
- Esolang **Brainfuck constants / code generation** (konstans- és kód-emittálás): https://esolangs.org/wiki/Brainfuck_constants , https://esolangs.org/wiki/Brainfuck_code_generation
- **ELVM** (C→BF) és **elvi** (interaktív `vi` klón tiszta BF-ben): https://github.com/shinh/elvm , https://github.com/irori/elvi
- **brainfuck-game-engine** (a képernyő = az első cellák; load+update; non-blocking `,`): https://github.com/MatheusAvellar/brainfuck-game-engine
- **Brainfuckconsole74** (valós idejű pure-BF játékok, 25 fps host-sync): https://esolangs.org/wiki/Brainfuckconsole74
- **dbfi** self-interpreter + „A Very Short Self-Interpreter": https://esolangs.org/wiki/Dbfi , https://arxiv.org/html/cs/0311032
- **msvcrt** (non-blocking input, prefix-bájtok): https://docs.python.org/3/library/msvcrt.html
- **Windows VT** (`ENABLE_VIRTUAL_TERMINAL_PROCESSING`): https://learn.microsoft.com/en-us/answers/questions/1356591/
- **Magas felbontású `time.sleep`** (Python 3.11+): https://docs.python.org/3/whatsnew/3.11.html
- **bfi** (optimalizált pure-Python BF interpreter, nagyságrend): https://github.com/eriknyquist/bfi
