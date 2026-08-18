# AI-Based Multilingual SMS Scam Detection System for Kathmandu

Final Year BSc (Hons) Ethical Hacking and Cybersecurity thesis project.
A hybrid Machine Learning + Explainable AI system that classifies SMS
messages (English, Nepali Unicode, Roman Nepali) as **Scam** or **Legit**,
and for Scam messages predicts the **scam type**, **risk level**, and a
**confidence score**, with a human-readable explanation of *why*.

The project is scoped to SMS scams targeting users in Kathmandu — the
dataset, problem statement, and evaluation are centred on that case study,
though the pipeline itself works on any of the three supported languages.

---

## 1. Architecture

```
Incoming SMS
     │
     ▼
Text Preprocessing            (utils/preprocessing.py)
     │
     ▼
TF-IDF Vectorization          (word, 1-2 grams, 8000 features, per task)
     │
     ▼
Cybersecurity Feature         (utils/security_features.py — 17 numeric
Extraction                     features: URLs, phones, OTP patterns,
     │                         urgency/reward/refund-context scores, ...)
     ▼
Feature Fusion                 scipy.sparse.hstack([TF-IDF | security feats])
     │
     ▼
ML Classification              Logistic Regression (GridSearchCV-tuned) vs.
                                Multinomial Naive Bayes — best model kept
                                by F1 score, per task
     │
     ▼
Confidence Score               calibrated probability + asymmetric decision
                                threshold (compensates for class imbalance)
     │
     ▼
Explainable AI                 utils/explain.py — keyword-category reasons +
                                signed security-feature breakdown + top
                                signed TF-IDF word contributions
     │
     ▼
Streamlit Dashboard             app.py + ui/ (styling, threat score, pattern
                                badges, PDF export, history, feedback)
```

The `ui/` package (added in the v5 dashboard redesign, restyled again in
v6 as an enterprise-dashboard layout) is presentation-only — it renders and
re-packages the pipeline's existing outputs (probability, security
features, explanation) and never calls into the model itself. See
`ENGINEERING_REVIEW.md` for the full account of both redesign passes.

Three independent models share this pipeline:

| Task | Type | Classes |
|---|---|---|
| Scam Detection | binary | Legit / Scam |
| Scam Type Classification | multiclass (Scam rows only) | Banking, OTP, Lottery, Loan, Promotion |
| Risk Level Prediction | multiclass | Low, Medium, High |

## 2. Why classical ML + engineered features (not deep learning)

TF-IDF captures statistical word/phrase associations; it does not encode
sentence-level semantics. This is a deliberate, documented trade-off for an
undergraduate cybersecurity thesis: the 17 engineered cybersecurity features
(URL/shortener/phone/OTP-pattern detection, urgency/reward/financial-request
keyword-density scores, and — the key false-positive fix — a
`refund_complaint_score` / `normal_context_score` pair that pulls routine
Nepali/Roman-Nepali money conversations back toward Legit) recover much of
the context TF-IDF alone would miss, while keeping every decision boundary
inspectable (logistic regression coefficients, not opaque embeddings) — this
is what makes the Explainable AI panel possible.

## 3. Project structure

```
sms-scam-detector/
├── app.py                        Streamlit dashboard orchestrator (run this to demo)
├── ui/
│   ├── styles.py                  theme CSS (palette-driven: light + dark)
│   ├── theme.py                     light/dark colour palettes + toggle helper
│   ├── navbar.py                    top navigation bar (brand, Help, About, theme toggle, Guest/Login)
│   ├── about.py                     About page content (research contribution, tech stack, model info)
│   ├── entities.py                  regex-based entity extraction (URLs, phones, OTPs, ...)
│   ├── threat_intel.py              rule-based Threat Intelligence pattern matching
│   ├── icons.py                     hand-authored monochrome SVG icon set (used only inside
│   │                                 st.markdown cards — never as a widget label, see §12)
│   ├── gauge.py                     semicircular SVG threat-score gauge (0-100)
│   ├── validation.py               input validation (empty/emoji-only/too long/short)
│   ├── language.py                 language detection + confidence for display
│   ├── scoring.py                  Threat Score (0-100) — blends model + patterns
│   ├── patterns.py                 indicator badges + multi-colour highlighting
│   ├── knowledge.py                 recommendations + offline Kathmandu knowledge base
│   ├── pdf_report.py                offline PDF report export (fpdf2)
│   ├── constants.py                 single source of truth: version, project name, author,
│   │                                 university, algorithm
│   ├── database.py                  SQLite schema (users, analysis_history, feedback,
│   │                                 saved_reports) + connection helper — single source of
│   │                                 truth for the schema, see §12
│   ├── auth.py                      bcrypt auth — register/login/logout/session/roles,
│   │                                 Login+Register page, admin auto-seed (§12)
│   ├── history.py                   persistent (SQLite) saved-analysis History page —
│   │                                 search, favourite, view, delete (§12)
│   ├── dashboard.py                 personal Dashboard page — totals, averages, recent
│   │                                 activity, favourite scam types (§12)
│   ├── export.py                    Export page — PDF/CSV/TXT of saved analyses (§12)
│   ├── profile.py                   Profile page — account details + password change (§12)
│   ├── admin.py                     Admin Dashboard, role-gated (admin only), Plotly (§12)
│   └── components.py                all render functions (header, cards, gauge, history,
│                                     Settings page, Premium page, ...)
├── requirements.txt
├── README.md                      (this file)
├── DATASET_METHODOLOGY.md         dataset expansion methodology + citations
├── ENGINEERING_REVIEW.md          full self-review across every redesign pass (Examiner/
│                                   Engineer/Cybersecurity/UX perspectives, known limitations)
├── data/
│   ├── sms_dataset.csv            working dataset used by training (608 rows)
│   ├── sms_dataset_v3_original.csv  the original 138 real-labelled rows, preserved
│   └── app.db                     local SQLite DB — users, analysis_history, feedback,
│                                    saved_reports; created automatically on first run,
│                                    safe to delete (a fresh one is recreated, admin account
│                                    included, the next time the app starts)
├── data_generation/
│   ├── templates.py                grounded scam/legit SMS template bank
│   ├── generate_dataset.py         merges templates + real data -> sms_dataset.csv
│   └── report.txt                  class-balance report (generated)
├── model/
│   ├── train_model.py              full training + evaluation pipeline
│   ├── *.pkl                       trained models, vectorizers, label encoders
│   └── plot_*.png                  confusion matrix / ROC / PR / learning-curve /
│                                    feature-importance plots per task
├── utils/
│   ├── preprocessing.py            multilingual text cleaning + tokenization
│   ├── security_features.py        17 cybersecurity feature extractors
│   └── explain.py                  explainability / keyword-highlighting logic
└── logs/
    └── predictions.log             CSV log of predictions made via the app
```

## 4. Setup

```bash
cd sms-scam-detector
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

## 5. Usage

**Rebuild the dataset** (only needed if you change `data_generation/templates.py`
or want to regenerate from the original 138-row seed):

```bash
python data_generation/generate_dataset.py
```

**Train all three models** (writes `.pkl` files and evaluation plots to `model/`):

```bash
python model/train_model.py
```

**Run the dashboard:**

```bash
streamlit run app.py
```

## 6. Dataset

- 608 rows total: 315 Legit / 293 Scam, across English / Nepali (Devanagari) /
  Roman Nepali.
- Expanded from an original 138 real-labelled rows (preserved unmodified in
  `data/sms_dataset_v3_original.csv`) using template-based synthetic
  generation grounded in real reported Kathmandu SMS-scam patterns (Nepal
  Telecom advisories, Nepal Police Cyber Bureau warnings, and cybersecurity
  press coverage — full source list in `DATASET_METHODOLOGY.md`).
- Every row carries a `template_id` and `source` (`real`/`synthetic`) column.
  Rows generated from the same template are lexically similar (same wording,
  different bank/amount/phone slot), so the training pipeline splits and
  cross-validates at the **template group** level (`StratifiedGroupKFold`,
  see `model/train_model.py`) rather than the row level — this prevents
  near-duplicate synthetic variants from leaking between train and test and
  silently inflating the reported metrics. See `DATASET_METHODOLOGY.md` §5
  for the full rationale.

## 7. Current model performance

(Measured on the group-aware, leakage-safe split — see §6. Re-running
`train_model.py` will vary these slightly since template groups are
reshuffled per run.)

| Task | Test Accuracy | Test F1 | 5-Fold CV F1 (group-aware) |
|---|---|---|---|
| Scam Detection (binary) | ~0.98 | ~0.97 | ~0.95 ± 0.03–0.05 |
| Scam Type Classification (5-class) | ~0.79 | ~0.74 | ~0.53–0.55 ± 0.20 |
| Risk Level Prediction (3-class) | ~0.95 | ~0.95 | ~0.81 ± 0.20 |

The Scam Type task's lower, noisier CV score is a genuine finding, not a
bug: the confusion is concentrated between **Loan** and **Lottery**
templates, which share reward/urgency vocabulary ("claim now", "call
immediately", large sums). This is flagged in `DATASET_METHODOLOGY.md` as a
natural next step (richer n-grams, an SVM/Random Forest comparison, or
disambiguating features).

## 8. Explainable AI

For every prediction, the app shows the reasoning as distinct, individually
labelled cards (not one long block) — per the v6 layout brief, "Explainable
AI" is a dedicated section with its own cards rather than a nested
expander:

- **Summary** — plain-language verdict statement.
- **Reasoning** — the keyword-category reasons (urgency, financial-request,
  reward, refund/complaint, normal-context) with the actual matched words.
- **Detected Indicators** — badges for the 12 pattern indicators (urgency,
  pressure/fear language, financial request, reward, OTP pattern, personal
  info request, suspicious link, phone number, bank/loan/lottery scam type).
- **Probability** — a bar per class (Scam / Legit) with the model's own
  predicted probability.
- **Detected Patterns** — a signed breakdown of which of the 17 security
  features pushed the verdict toward Scam (red) or Legit (green), e.g.
  `refund_complaint_score`, `normal_context_score`.
- **Message Preview** — the original SMS with matched phrases
  colour-highlighted by category.
- **Model Confidence** — the top TF-IDF words by signed contribution
  (word × its logistic regression coefficient).
- **Recommendation** — scam-type-specific advice (different for Banking,
  OTP, Lottery, Loan, Promotion) from `ui/knowledge.py`.

## 9. Dashboard features (current build)

The **Analyse SMS** page (`app.py`'s default view) follows the same
top-to-bottom flow every pass since v6: **Navbar → SMS Input card →
Analyse → Demo Mode → Model Info → How AI Works (collapsed) → Result →
Explainable AI → Analyst Report → Session History → Footer.** A
full-width input card is the visual focus, with Analyse / Clear / Paste
Example / Copy Input actions; **Demo Mode** offers eight one-click
example buttons for a fast viva walkthrough; language detection is shown
live as you type; a semicircular 0-100 Threat Score gauge sits beside the
result metrics; the 8-card Explainable AI breakdown (§8) and the
**Analyst Report** section (§11, extracted entities + rule-based Threat
Intelligence) are available to every user, Guest included — nothing about
viewing a prediction or its explanation requires an account.

Logging in unlocks the rest of the app (Phase 2, §12): **Dashboard**
(personal stats), **History** (persistent, searchable, favouritable saved
analyses), **Export** (PDF/CSV/TXT), **Premium** (model statistics + your
feedback history), **Settings**, and **Profile** (via the navbar badge),
plus **Admin Dashboard** for the one seeded admin account. The sidebar
itself changes shape based on who's looking at it — see §12 for the exact
Guest vs Premium vs Admin nav lists.

The whole UI is restricted to a six-colour palette (white, dark blue/navy,
grey/slate, green, orange, red — both light and dark variants) with no
gradients, glow, or glassmorphism — modelled on plain, dense, no-nonsense
dashboards (GitHub, Linear, Microsoft's first-party tools) rather than a
"futuristic AI" look. Every icon used inside a card is a hand-authored,
dependency-free SVG (`ui/icons.py`); every icon used as a widget label
(button/popover/expander) is plain emoji instead, because Streamlit
widget labels don't render raw HTML/SVG — see `ENGINEERING_REVIEW.md` §9
for the full account of that bug and fix. Phase 2 (§12, `ENGINEERING_REVIEW.md`
§11) deliberately left this visual layer alone — it's new pages and a
real backend, not a restyle. See `ENGINEERING_REVIEW.md` §§7–11 for the
full design rationale across every pass, examiner-style critiques, and
known limitations.

## 10. Known limitations (stated for academic transparency)

- No public, labelled corpus of real Nepali SMS scams exists, so dataset
  expansion is template-generated rather than scraped from real user
  reports — real-world wording variety, spelling errors, and code-mixing
  will be higher than in this dataset.
- Loan and Promotion scam templates are grounded in the *general*
  advance-fee/credential-phishing pattern documented for Nepal rather than
  one specific press-reported incident (unlike Banking/OTP/Lottery, which
  quote or closely mirror documented cases). See `DATASET_METHODOLOGY.md`.
- TF-IDF still only captures statistical word associations, not full
  sentence semantics — the engineered security features are the primary
  mitigation, not a complete substitute.
- The Scam Type and Risk Level test sets, while larger than the original
  138-row dataset allowed, are still modest per class (dozens of rows) —
  report confidence intervals rather than point estimates when writing up
  results.
- The PDF report export degrades Nepali Unicode (Devanagari) text to `?`
  placeholders, because `fpdf2`'s built-in fonts only support Latin-1 and
  no Devanagari-capable TTF is bundled — English and Roman Nepali messages
  are unaffected. Full detail and the fix path in `ENGINEERING_REVIEW.md` §3.
- The Threat Score (`ui/scoring.py`) is a documented, transparent heuristic
  blend of the model's own probability and the security features — not a
  fourth trained/validated model. Present it as such in the viva.
- The Threat Intelligence "tactics" patterns (`ui/threat_intel.py`) are
  simple, documented boolean combinations of existing security features —
  a rule-based heuristic layer, not an independently validated model.

## 11. Analyst Report — entity extraction and Threat Intelligence

Every analysis includes an **Analyst Report** section with two parts:

- **Extracted Entities** (`ui/entities.py`) — a regex-based table of URLs,
  phone numbers, emails, money amounts, bank/service names, reference
  numbers, account numbers, coupon codes, and OTP codes found in the
  message. Reuses the same URL/phone/currency regexes the model itself
  uses as features (`utils/security_features.py`), so the entities shown
  can never disagree with what the model actually saw.
- **Threat Intelligence** (`ui/threat_intel.py`) — two groups of
  rule-based pattern cards: five that mirror the trained scam-type
  classifier's own five classes (Banking, OTP, Lottery, Loan, Promotion),
  and five independent "tactic" patterns (Credential Phishing, Advance-Fee
  Fraud, OTP/Identity Hijack, Suspicious Link/Domain Spoofing, Urgency &
  Pressure Tactics) derived from the same security features, each with a
  plain-language rationale for why it matched or didn't.

**Deliberately not included:** pattern cards for scam categories the
trained classifier was never trained on (e.g. "Investment Scam",
"Government Scam", "Delivery Scam"). The scam-type model has exactly five
classes — see §1 — and a pattern card implying detection of a sixth would
overstate the system's actual, evaluated capability. See
`ENGINEERING_REVIEW.md` §8.1 for the full reasoning.

## 12. Accounts, roles, and role-based navigation (Phase 2)

Phase 2 replaced the Phase 1 auth stub with a real local system: bcrypt
password hashing, an `email` + `role` column, dedicated Login/Register
pages, and a sidebar that changes shape depending on who's logged in.
Everything below is SQLite (`data/app.db`) — no cloud database, no
network call, works fully offline. See `ENGINEERING_REVIEW.md` §11 for
the full write-up (schema, design decisions, and what was interpreted
where the brief left something implicit).

**Guest** needs no account. Guests can Analyse SMS, view the full
Explainable AI breakdown, and use example messages. Guests cannot save
history, export reports, or access the Dashboard/Admin Dashboard — the
sidebar simply doesn't offer those pages until logged in.

**Premium** is any self-registered account (Register page, top-right
👤 badge → "Log in"). There's no payment tier; "Premium" means "has an
account," matching the brief's framing for a thesis demo. Logging in
unlocks: **Save Analysis** on any result (persists to `analysis_history`,
on top of — not instead of — the existing session-only history everyone
already had), **History** (search, ⭐ favourite, view, delete),
**Export** (PDF/CSV/TXT), a personal **Dashboard** (totals, averages,
recent activity, favourite scam types), a **Premium** page (model
statistics + your own feedback history), **Settings**, and **Profile**
(account details + password change). The top-right badge shows
`👤 Username ⭐ Premium`.

**Admin** is a single seeded account — **username `admin`, password
`admin123`**, created automatically on first run (`ui.auth.ensure_admin_seed`),
for local demonstration only. Logging in as admin shows the same Premium
sidebar plus an **Admin Dashboard** entry, a real role-gated page (not a
hidden URL, unlike Phase 1's `?admin=1` route) with Plotly charts: total
analyses, Scam vs Legitimate split, scam-type distribution, average
confidence, average threat score, registered/Premium user counts, 👍/👎
feedback agreement rate, and a recent-analyses table — all read from
`logs/predictions.log` (every analysis, Guest included — the broadest,
most representative sample) and `data/app.db`.

Passwords are hashed with `bcrypt` (auto-salted per call — no separate
salt column needed). Feedback (👍/👎, from every result card, Guest
included) now writes to the SQLite `feedback` table instead of
`feedback.csv`. Every PDF/CSV/TXT export a Premium/Admin user generates
is also logged to a `saved_reports` table — an audit trail proving
exports actually happened, not just a claimed feature.

**Sidebar navigation, exactly as specified:**

| Guest | Premium / Admin |
|---|---|
| Analyse SMS, About, Settings, Login/Register | Dashboard, Analyse SMS, History, Export, Premium, Settings, About, Logout — **Admin Dashboard** appended for the admin role only |

**Stated scope limits, not hidden:** one shared local database, no email
verification, no password-reset-by-email flow, no session tokens beyond
Streamlit's own `session_state`, and a single shared admin passcode
rather than per-admin credentials. Correct for a single-machine academic
demo; would need real session tokens, rate limiting, and probably
Argon2/bcrypt-with-tuning before touching a real multi-user deployment.
