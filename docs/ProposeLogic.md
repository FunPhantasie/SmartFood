# Propose-Logik – Formeln & Sanity-Checks

Referenz für die Vorschlagslogik in [Tools/ProposeLogic.py](../Tools/ProposeLogic.py).
Jede Formel steht hier so, wie sie im Code umgesetzt ist, damit Code und Idee später gegeneinander geprüft werden können.

> Status: **IN Arbeit** Umgesetzt:
- DateScore

---

#  Overview I

1. Lade Alle Daten (Könnte Ineffizient sein) \
     1.1 Rezepte \
     1.2 History \
     1.3 Rezepte Zutaten 
2. Aus History berechne DateScore
   - Messe Abstände in **dates** array[date]
   - Mess Abstand letztes mal Today **last_date** date
   - Use WiederholungsScore  **repeat_rating** int
3. Aus History berechne Abschätzung Arbeit Gegen Result 
   - d
# Methods II
## 1.  def repeatScore() => return date_score
     take dates
     if dates.size <=1  faktor=1 without today
     calc average distance between days floor down to Days **avg_dist**
     calc distance to last_date and today floor down to Days **dist_last**
     faktor = max(1,4-avg_dist/14) 14 Repeat Still Good Rescaling
     ToDo Later Calibrated with Vielzahl/Number of Recipes 
     faktor => g(fakor :exp) => (0,1)  
     Entschiede zwischen 1-exp(-x) oder exp(-1/x)
     Nehme 1-exp(-x) besser zu manipulieren predikten
     date_score = 10/5 * repeat_rating * exp (-faktor*dist_last/8)
     Result:= date_score => 0 to 10
## 2. def dopaminscore() => reward_score
      taste_rating
## 2. def damping_score() => damp_score, last_supper
     load all of last 3 Cooked Meals **last_supper** array[ids]
     ignore if longer than 4 days 
     load incredients of recipe_incredients for **last_supper**
     createfilter list 
          - SIDEDISH
          - Meat

## X. filter_score FinalList
     load all Variants **last_supper**
     filter all repeatance of variants and original (last_supper)  out

# Generation List 
> Uses : date_score | reward_score | never_cooked | wishlist \
> Calc Score and Choose Top 5  

> Swapping out Recipes
- X: Gericht wird vorgeschlagen („Proposed“)
- ¬X: Gericht wird nie gekocht („Never Cooked“)
-  Y = Number of  X with tries n = 5, Y ~ Bin(5, p).
- **Gegeben:** P(Y = 5) = p⁵ = 0,8
- P(¬X) = 1 − p ≈ 0,044 = w

For Each Propose Choose to Swap with Propability 1-p \
Skip if on Wishlist 
#  Gemessene Variablen / Größen IV

Pro Rezept gibt es genau **einen** history-Eintrag. Die Arrays darin rotieren (max. 20 Werte, siehe `RatingLogic.HISTORY_ARRAY_MAX`).

| Feld | Quelle | Typ | Bedeutung | Default / fehlt |
|---|---|---|---|---|
| `dates` | history | Liste ISO-Datum | Tage, an denen bewertet (gekocht) wurde | `[]` |
| `last_date` | history | ISO-Datum | zuletzt gekocht (auch über „Einmal gekocht“) | fehlt → nie gekocht |
| `repeat_rating` | history | Liste int 1–5 | Wiederholungs-Lust | `3`; Seed ungekochter Rezepte: `[1]` |
| `taste_rating` | history | Liste int 1–5 | Geschmack | – |
| `effort_rating` | history | Liste int 1–5 | Aufwand | – |
| `prep_minutes` / `cook_minutes` | recipe | int | Zeiten | – |
| `season` | recipe | str | Saison | `always` |

#  DateBase Structure V
## Recipes
Season: All , Frühling Sommer....

Recipe Typ: Main Dish, Nachspeise, Dip, Würzmischun,g Sidedish, Snack, Vorspeise

Recipe Specs: Soup, Salad,Auflauf, Rest?,

Zubereitungart: Ofen Pfanne Grill Roh

Herkunft Asia Oriatnalisch Mecxaikanisch Haussamn Mediteran (Can be Specrum Multiple)

Main INcredient (When not specified) Check only when Created Titel match Ingredients 
    -Can be speciefied to also NoneSpecific

## Incredients

ingredient_id, name ,   unit,  veg_type, laktose_free,glutenfree,specs_incredient

specs_incredient: side_dish, gewürz, basics (eg. Water,Flour..)

### 3.1 `date_score` – Wiederholung / Abstand ✅

Code: `repeatScore(entry, today)` und `calcAvgDistanceScore(avg_dist)`

**Formel**

```
avg_dist       = Mittelwert der Tagesabstände zwischen aufeinanderfolgenden (dates + heute)
s(avg_dist)    = max(0, 3 − 10 / avg_dist)          (0, falls avg_dist = 0)
WDH_Lust       = Mittelwert(repeat_rating)
d_last         = Tage seit last_date

date_score     = 10 · WDH_Lust/5 · exp( −8 · s / d_last )
```

**Variablen**

| Symbol | Bereich | Wirkung |
|---|---|---|
| `WDH_Lust/5` | 0.2 – 1 | skaliert den Maximalwert → date_score ∈ [0, 10] |
| `s` | 0 – 3 | wie stark „kürzlich gekocht“ bestraft wird; `s = 0` für `avg_dist ≤ 3.33` Tage |
| `exp(…)` | 0 – 1 | → 1, je länger `last_date` her ist |

**Randfälle**

| Fall | Behandlung |
|---|---|
| keine `dates` | `avg_dist = 1` → `s = 0` → keine Strafe |
| kein `last_date` (nie gekocht) | `d_last = ∞` → Faktor 1 → `date_score = 2 · WDH_Lust` |
| `d_last = 0` (heute gekocht) | wird auf 1 Tag gesetzt (keine Division durch 0) |
| leeres `repeat_rating` | `WDH_Lust = 3` |

**Rechenbeispiele** (heute = 2026-09-23, mit dem echten Code berechnet)

| # | Situation | avg_dist | s | d_last | WDH_Lust | date_score |
|---|---|---|---|---|---|---|
| A | nie gekocht (Seed) | – | 0 | ∞ | 1 | **2.00** |
| B | 1× gekocht, heute | 0 | 0 | 1 | 4 | **8.00** ⚠️ |
| C | Rezept 52: 1×, vor 7 Tagen | 7 | 1.57 | 7 | 3 | **1.00** |
| D | alle 20 Tage, zuletzt vor 13 | 17.7 | 2.43 | 13 | 4 | **1.79** |
| E | alle ~90 Tage, zuletzt vor 90 | 90 | 2.89 | 90 | 5 | **7.74** |
| F | alle 3 Tage, zuletzt vor 3 | 3 | 0 | 3 | 5 | **10.00** ⚠️ |

### 3.2 `dopamin_score` – Geschmack vs. Aufwand 🚧

Code: `dopaminscore(...)` (in Arbeit, wird noch nicht aufgerufen)

```
zeit       = cook_time + prep_time
kochscore  = softmax(zeit / 7.5)        # 7.5 min als Einheit – TODO: Definition festlegen
dopamin    = f(geschmack, aufwand, kochscore)   # TODO
```

| Symbol | Bereich | Wirkung |
|---|---|---|
| TODO | | |

### 3.3 Weitere Scores ⬜

- Saison (`season` vs. aktueller Monat)
- Wunschliste (`wishlist.yaml`) → Bonus?
- include/exclude von Zutaten (eher Filter als Score?)

## 4. Gesamtscore ⬜

```
score = w_date · date_score + w_dopamin · dopamin_score + …     # TODO: Gewichte / Kombination
```

Danach eine gewichtete Zufallsauswahl (heute: `RatingLogic.weighted_shuffle`).

## 5. Sanity-Checks

Erwartetes Verhalten. Jede Zeile sollte zu einem Beispiel oben (oder einem Test) passen.

| Situation | Erwartung | Aktuell (date_score) | OK? |
|---|---|---|---|
| gerade eben gekocht | sehr niedrig (~0) | B: 8.00 | ❌ |
| sehr oft gekocht, zuletzt vor kurzem | niedrig | F: 10.00 | ❌ |
| selten gekocht, lange her | hoch (~2·Lust) | E: 7.74 von max. 10 | ✅ |
| normaler Rhythmus, mittendrin | mittel | D: 1.79 | ❓ |
| nie gekocht | neutral-niedrig (Seed-Lust 1) | A: 2.00 | ✅ |
| höhere Lust ⇒ höherer Score (sonst gleich) | monoton steigend | linear in WDH_Lust | ✅ |
| länger her ⇒ höherer Score (sonst gleich) | monoton steigend | ja, solange s > 0 | ✅ |

## 6. Offene Fragen

1. **Häufig gekochte Rezepte werden nicht bestraft (B, F).** `s = max(0, 3 − 10/avg_dist)` ist 0 für kleine Abstände. Die Strafe greift also gerade bei oft gekochten Rezepten *nicht*. Ist das so gewollt, oder soll die Strafe mit kleinerem `avg_dist` *steigen*?
2. `today` wird an `dates` angehängt. Dadurch zählt die aktuelle Pause mit in `avg_dist`. Gewollt?
3. Wie soll `d_last = 0` behandelt werden (derzeit = 1 Tag)?
4. Default `avg_dist = 1` ohne `dates` bedeutet keine Strafe. Passt das zu Rezepten, die nur per „Einmal gekocht“ ein `last_date` haben?
5. Soll `date_score` auf 0–1 normiert werden, damit er sich mit anderen Scores kombinieren lässt?

## Changelog

- 2026-09-23 – Entwurf angelegt, `date_score` umgesetzt und dokumentiert.
