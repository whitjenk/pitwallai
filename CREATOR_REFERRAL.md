# Creator referral path — product & technical spec

**Status:** Spec only (not implemented)  
**Goal:** Attribute WhatsApp subscribers to creators (e.g. [F1 Fantasy Pole Position](https://www.youtube.com/@f1fantasypoleposition)) without competing with their advice — PitWallAI is the **personalized execution layer** after their content.

---

## 1. Problem

Today every subscriber enters via plain `SUBSCRIBE`. There is no way to know:

- Which creator drove a signup
- Whether a collab drove retained users vs one-week churn
- Which prefill link (`wa.me`) was used

We already have `wa_me_link(prefill)` on `/results` and `SHARE` cards. Referrals extend that pattern with **stable codes**, **DB attribution**, and **creator-facing metrics**.

---

## 2. User experience

### 2.1 Subscriber (WhatsApp)

| User sends | System behaviour |
|------------|------------------|
| `SUBSCRIBE` | Same as today; `referral_code = null` (organic) |
| `SUBSCRIBE POLE` | Subscribe + store `referral_code = "pole"` |
| `SUBSCRIBE pole` | Normalized to `pole` (case-insensitive) |
| `SUBSCRIBE POLEPOSITION` | Maps via alias table → `pole` |
| Already subscribed + `SUBSCRIBE POLE` | “Already subscribed.” Optional: update referral only if currently null (policy choice — see §5) |

**First message after attributed subscribe** (one extra line, ≤160 chars total with existing copy):

> Subscribed via *F1 Fantasy Pole Position*. Send a My Team screenshot or text TEAM when ready.

Unknown codes: subscribe normally, log `referral_code = "unknown:<token>"` for analytics, **no** creator name in reply (avoid endorsing typos).

### 2.2 Creator (Euan / others)

**Outreach kit** (static, no app):

1. **Click-to-chat:** `https://wa.me/<number>?text=SUBSCRIBE%20POLE`
2. **Manual:** “Text **SUBSCRIBE POLE** to &lt;display number&gt;”
3. **YouTube description block** (template in §8)
4. **Optional landing:** `https://pitwallai.app/r/pole` → 302 to `wa.me` with prefill (§4)

**Creator dashboard (phase 2):** read-only page or weekly email:

- Signups this week / season (count)
- Active after 14 days (%)
- Races with TEAM completed (%)
- PitWallAI GP hit rate (global + “your cohort” once N≥30)

No per-user phone numbers — aggregates only.

### 2.3 Positioning (copy rules)

- “Tool featured by …” not “Official partner of F1 Fantasy”
- “Personalized picks for **your** team” not “better picks than &lt;creator&gt;”
- Always link [DISCLAIMER.md](DISCLAIMER.md) on web surfaces

---

## 3. Referral code registry

### 3.1 Built-in codes (seed data)

| Code | Aliases | Display name | Notes |
|------|---------|--------------|-------|
| `pole` | `poleposition`, `f1fpp`, `euan` | F1 Fantasy Pole Position | Primary target collab |
| `organic` | — | *(internal)* | Reserved; do not expose |

Creators added via DB/admin script, not deploy for each new name.

### 3.2 Table: `referral_sources`

```text
code            VARCHAR(32)  PK   -- normalized lowercase, [a-z0-9_]
display_name    VARCHAR(128) NOT NULL
aliases         JSONB        DEFAULT []   -- extra tokens that map to code
active          BOOLEAN      DEFAULT true
created_at      TIMESTAMPTZ
notes           TEXT         NULL       -- internal: contact, deal, video URL
```

### 3.3 Subscriber attribution

Add to `subscribers`:

```text
referral_code       VARCHAR(32)  NULL  FK → referral_sources.code ON DELETE SET NULL
referral_recorded_at TIMESTAMPTZ NULL  -- first attribution time
```

**Rules:**

- Set on **first successful** `handle_subscribe` (new row or reactivation from inactive).
- **Never overwrite** an existing non-null `referral_code` on later messages (first touch wins).
- `DELETE` erases subscriber row; referral counts are historical aggregates in `referral_signups` (§3.4) if you need post-DELETE reporting — optional phase 2.

### 3.4 Optional aggregate table (phase 2, privacy-friendly)

```text
referral_daily_stats
  date, referral_code, signups, activations, team_completed, races_scored
```

Populated by nightly job from SQL aggregates — no PII.

---

## 4. Web landing (`/r/{code}`)

**Route:** `GET /r/{code}` on FastAPI (`api/server.py`)

| Step | Behaviour |
|------|-----------|
| 1 | Normalize `code`; lookup `referral_sources` (or static map in v1) |
| 2 | Unknown → `302` to `/results` or generic `wa.me?text=SUBSCRIBE` |
| 3 | Known → HTML micro-page (or immediate `302`) with creator name + CTA button |
| 4 | CTA `href` = `wa_me_link(f"SUBSCRIBE {code.upper()}")` — use uppercase in prefill for readability |

**Micro-page content:**

- Headline: “Personalized F1 Fantasy picks on WhatsApp”
- Sub: “Featured by {display_name}. Not affiliated with F1 Fantasy.”
- Button: “Open WhatsApp”
- Footer: link to `/results`, `PRIVACY.md`, `DISCLAIMER.md`

**UTM (optional, web analytics only):**  
`/r/pole?utm_source=youtube&utm_medium=description` — log in access logs; do not store UTM on subscriber row in v1.

---

## 5. Parsing & routing

### 5.1 Inbound text (authoritative)

Parse in `whatsapp/inbound.py` before `handle_subscribe`:

```python
# SUBSCRIBE [CODE]
# SUBSCRIBE CODE-with-dashes → normalize to alphanum
```

**Algorithm:**

1. Strip, uppercase for command detection.
2. If starts with `SUBSCRIBE`:
   - Tokenize `raw_text`; tokens[1:] joined → referral token (max 32 chars).
   - Normalize: lower, alphanumeric only (drop punctuation).
   - Resolve: exact `code` → else scan `aliases` → else `unknown:<token>`.
3. Call `handle_subscribe(phone, referral_code=resolved)`.

Command router path (`whatsapp/commands/subscribe.py`) must accept the same if `SUBSCRIBE` is ever routed there — today subscribe is handled in `inbound.py` only; keep single parse function in `whatsapp/referral.py`.

### 5.2 `wa.me` prefill

| Surface | Prefill |
|---------|---------|
| Generic `/results` | `SUBSCRIBE` |
| Creator `/r/pole` | `SUBSCRIBE POLE` |
| Share card footer (optional) | `SUBSCRIBE` (keep generic) or `SUBSCRIBE POLE` when `?ref=pole` on share URL — phase 2 |

Extend `wa_me_link(prefill)` — already supports arbitrary prefill.

---

## 6. Implementation map

| Piece | File(s) | Effort |
|-------|---------|--------|
| `parse_subscribe_referral(raw_text)` | `whatsapp/referral.py` (new) | S |
| `resolve_referral_code(token)` | `whatsapp/referral.py` + DB or static dict v1 | S |
| `handle_subscribe(phone, referral_code=None)` | `whatsapp/subscribe_flow.py` | S |
| Inbound branch | `whatsapp/inbound.py` | S |
| Model + migration | `db/models.py`, `db/migrate.py` | S |
| Seed `pole` | `scripts/seed_referral_sources.py` or SQL | S |
| `/r/{code}` route | `api/server.py`, `api/static/referral.html` template | M |
| Results CTA `?ref=` | `scripts/generate_results_page.py` | S |
| Creator stats query | `intelligence/repository.py` | M |
| Tests | `tests/test_referral.py` | M |

**v1 scope (ship first):** parse + DB column + seed `pole` + inbound + subscribe + tests.  
**v2:** `/r/{code}` page + weekly creator email.  
**v3:** cohort hit rate + optional FULL cadence flag per code.

---

## 7. Analytics & success metrics

**Creator-facing (weekly):**

- `signups` — count where `referral_code = pole`
- `activation_rate` — % with `fantasy_teams.driver_1` set within 7 days
- `retention` — % still `active` after 3 races
- `pitwall_gp_hit_rate` — global public stat (from `/results`); cohort stat when N ≥ 30

**Internal:**

- Organic vs referred mix
- Top unknown tokens (typo discovery → new aliases)

**Logging:** `logger.bind(referral_code=code, phone=mask_phone(phone)).info("Subscriber activated via referral")`

---

## 8. Creator kit — F1 Fantasy Pole Position (`pole`)

### YouTube description (block)

```text
── PitWallAI (personalized WhatsApp picks) ──
After quali: get picks for YOUR team & budget, not generic tier lists.
Text SUBSCRIBE POLE to [number] or tap: [wa.me link]
Free · open source · not affiliated with F1 Fantasy
```

### Suggested segment (60–90s)

1. Euan explains his take (unchanged).
2. “If you want this applied to your actual squad — budget, transfers — I’ve been testing PitWallAI on WhatsApp.”
3. Screen record: `SUBSCRIBE POLE` → screenshot TEAM → `PICKS` / one driver card.
4. Disclaimer: independent tool, you still decide, link in description.

### Pole Sitters perk (optional policy)

- Members who use `SUBSCRIBE POLE` get `cadence_preference = FULL` by default (Friday delta + Saturday picks).
- Implement via `referral_sources.default_cadence` column — only if Euan wants it.

---

## 9. Privacy & compliance

- Referral code is **not** PII; phone remains PII — same `mask_phone()` rules.
- `PRIVACY.md` addendum: “We store an optional referral tag (e.g. which creator link you used) to measure outreach. It is not sold.”
- `erase_subscriber_data` already deletes subscriber row; document whether aggregates retain counts without phones (yes, if using daily stats table).
- No F1 / F1 Fantasy logos on `/r/pole` page.
- Paid sponsorship requires #ad in creator video per their platform rules — outside product scope.

---

## 10. Edge cases

| Case | Policy |
|------|--------|
| Resubscribe after UNSUBSCRIBE | Keep original `referral_code` if row was soft-deleted only; if row deleted, new code allowed |
| Resubscribe after DELETE | New row; new referral allowed |
| `SUBSCRIBE POLE` mid-season | Attribution + normal onboarding |
| Invalid code `SUBSCRIBE FOO` | Subscribe; store `unknown:foo`; no creator shout-out |
| Command router `subscribe` handler | Delegate to shared parser (avoid drift) |
| Rehearsal / `whatsapp_chat.py` | Support `SUBSCRIBE POLE` in simulator for demos |

---

## 11. Open questions (decide before build)

1. **Overwrite policy:** Can a later `SUBSCRIBE OTHER` change attribution? **Recommend: no.**
2. **Unknown codes:** Silent vs “Unknown code, subscribed anyway”? **Recommend: silent.**
3. **Creator payout:** None in v1 (goodwill / content collab only).
4. **Multi-level:** `SUBSCRIBE POLE YOUTUBE` — ignore extras in v1 or use last token only.

---

## 12. Acceptance criteria (v1)

- [ ] `SUBSCRIBE POLE` creates subscriber with `referral_code = 'pole'`
- [ ] `SUBSCRIBE` leaves `referral_code` null
- [ ] Second subscribe with different code does not change stored code
- [ ] Unknown code still subscribes; logs `unknown:*`
- [ ] `wa_me_link("SUBSCRIBE POLE")` matches inbound parser output
- [ ] DELETE removes subscriber; referral_code not leaked in logs
- [ ] SQL count: `SELECT COUNT(*) FROM subscribers WHERE referral_code = 'pole'`

---

## 13. Example flow (Euan audience)

```text
Viewer watches quali reaction video
  → taps wa.me/?text=SUBSCRIBE%20POLE
  → sends message
  → PitWallAI: data note + subscribed + (optional) “via F1 Fantasy Pole Position”
  → sends My Team screenshot
  → Saturday (or PICKS): personalized picks vs Euan’s generic T1/T2/T3
  → post-race: SHARE card in league WhatsApp with generic or POLE prefill
```

This completes the loop: **creator teaches → referral tags → product personalizes → share card acquires league mates.**
