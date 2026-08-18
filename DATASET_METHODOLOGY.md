# Dataset Expansion Methodology (v3 → v4)

This note documents how `data/sms_dataset.csv` was expanded from 138 to 608
rows, and the corresponding change to the train/test splitting strategy in
`model/train_model.py`. It is written to be pasted (and trimmed/adapted) into
the thesis methodology chapter.

## 1. Motivation

The original dataset had two structural weaknesses that would not survive
close examination in a viva:

- **Size**: 138 rows total, with the `scam_type` subclasses at 8–14 samples
  each and `risk_level = Medium` at only 4 samples across the whole dataset.
  A single stratified 80/20 split left some classes with 2–3 test samples,
  meaning any reported precision/recall for those classes was really a
  statement about 2–3 messages, not a generalizable estimate.
- **Coverage**: the dataset did not include some of the specific SMS-scam
  patterns most frequently reported in Kathmandu over the past year (fake
  ConnectIPS/bank "account locked" alerts, OTP phone-call harvesting, fake
  telecom data-bonus phishing), which are the patterns the system's real
  users are most likely to encounter.

## 2. Real-world grounding

Because no public, labelled corpus of real Nepali SMS scams exists, the
expansion uses **template-based synthetic generation**, where every scam
template is grounded in a documented Nepal-specific attack pattern rather
than an invented one. Sources consulted:

- Nepal Telecom public advisory on bank-account-draining SMS alert links,
  quoting the exact wording *"Dear valued customer, your Connect IPS account
  has been locked. Please verify to login and secure it."* — TechPana,
  ["Bank Accounts Drained via SMS Alert Links, Nepal Telecom Warns
  Public"](https://techpana.com/2025/152593/bank-accounts-drained-via-sms-alert-links-nepal-telecom-warns-public).
- Nepal Police Cyber Bureau warnings on phishing SMS impersonating banks and
  digital wallets (Nabil, NIC Asia, Global IME, eSewa, Khalti) via spoofed
  sender IDs such as "AT_Alert"/"THE_Alert" — Kathmandu Post, ["Cyber bureau
  warns of phishing scams targeting bank and digital wallet
  users"](https://kathmandupost.com/national/2025/06/02/cyber-bureau-warns-of-phishing-scams-targeting-bank-and-digital-wallet-users)
  and ["Cyber bureau warns internet users of rising cases of
  phishing"](https://kathmandupost.com/national/2025/04/11/cyber-bureau-warns-internet-users-of-rising-cases-of-phishing).
- Documented OTP phone-call social-engineering flow (fraudster poses as
  bank/wallet support, requests the OTP "to verify identity" while
  triggering a real transaction) and the fake NTC data-bonus
  credential-phishing case — CyberSamir, ["Fake SMS & OTP Scams in Nepal:
  How People Are Losing
  Money"](https://blog.cybersamir.com/fake-sms-otp-scams-nepal/).
- General smishing/OTP-fraud context and Cyber Bureau complaint volume
  (13,426 cybercrime complaints in the current fiscal year, 217 tied to
  eSewa/Khalti/bank-account scams) from the above sources plus Nepal
  Telecom's SMS-phishing alert coverage.

Each of the 15 scam templates in `data_generation/templates.py` carries an
inline comment naming the specific pattern it encodes. Loan and Promotion
templates (fake instant-loan offers, fake data-bonus offers) follow the same
advance-fee/credential-phishing structure documented above but are not tied
to one single press report, since Nepal-specific press coverage of those two
sub-types was thinner at the time of writing — this is called out as a
limitation below.

## 3. Generation process

`data_generation/templates.py` defines, per scam type and per legitimate
message category, a small set of hand-written message templates in English,
Nepali (Devanagari), and Roman Nepali, each with slot placeholders (bank
name, wallet name, phone number, amount, URL, OTP code, etc.) drawn from
realistic value pools (real Nepali bank/wallet names, `.tk`/`.xyz`/`.ml`-style
suspicious domains matching the patterns already flagged by
`utils/security_features.py`, and Nepali phone-number formats matching the
existing `_PHONE_RE` pattern).

`data_generation/generate_dataset.py` renders each template into multiple
distinct messages by sampling slot combinations (deduplicated so no two
rendered rows are textually identical), merges them with the original 138
real rows, drops any exact-text duplicates, and writes the result back to
`data/sms_dataset.csv`. The original 138 rows are preserved unmodified in
`data/sms_dataset_v3_original.csv`.

Each row gets a `template_id`: real rows get a unique id per row (so they
each act as their own group), and every rendering of a given synthetic
template shares that template's id. A `source` column (`real`/`synthetic`)
is kept for transparency.

### Category-to-severity mapping

| scam_type | risk_level | Rationale |
|---|---|---|
| Banking | High | Direct account-credential/takeover threat |
| OTP | High | Direct account-takeover threat |
| Lottery | High (majority) / Medium (minority) | Advance-fee fraud; a subset of low-stakes "small reward" variants is milder |
| Loan | High (majority) / Medium (minority) | Advance-fee/loan-app fraud; small-amount variants are milder |
| Promotion | Medium (majority) / High (minority) | Mostly spammy fake offers; a subset carries a credential-phishing link |

This mapping is what raised `risk_level = Medium` from 4 rows to 62 rows —
it was not achieved by inventing an unrelated "Medium" category, but by
recognizing that Promotion/Loan/Lottery scams have a real severity spread
that the original 138-row sample was too small to capture.

## 4. Resulting class balance

| | v3 (original) | v4 (expanded) |
|---|---|---|
| Total rows | 138 | 608 |
| Legit / Scam | 85 / 53 | 315 / 293 |
| Scam types | 8–14 per class | 56–62 per class |
| risk_level Low/High/Medium | 85 / 49 / 4 | 315 / 231 / 62 |
| Languages (En/Roman-Nep/Nep) | 51 / 55 / 32 | 320 / 192 / 96 |

Full breakdown is written to `data_generation/report.txt` on every
generation run.

## 5. Leakage-safe splitting (why train_model.py also changed)

Slot-filled variants of the same template are lexically very similar (e.g.
five "your {bank} account has been locked" messages that differ only in the
bank name and URL). If the train/test split were done at the row level, two
near-duplicate variants of one template could land on opposite sides of the
split — the model would then partly be tested on data it had effectively
already memorised, inflating the reported accuracy without reflecting real
generalisation.

To prevent this, `model/train_model.py` now splits and cross-validates at
the **template group** level:

- `_ensure_template_id()` gives every row a group id (a real row's own row
  id if `template_id` is absent — fully backward compatible with datasets
  that predate this column).
- `group_train_test_split()` assigns whole templates to train or test
  (per-class greedy packing so the test set's row count still lands close
  to the requested 20%, rather than the size a template happens to be).
- `StratifiedGroupKFold` replaces `StratifiedKFold` for every GridSearchCV,
  cross-validation, and learning-curve step, with `groups=` passed through
  so no fold boundary crosses a template either.

**This is worth stating explicitly in the thesis**: the reported metrics
below are measured on a split that cannot benefit from synthetic
near-duplicate leakage, which is why the Scam Type and Risk Level numbers
are visibly more modest (and more trustworthy) than a naive split would
report.

## 6. Resulting metrics (v4 dataset, leakage-safe split)

| Task | Test Accuracy | Test F1 | 5-Fold CV F1 (group-aware) |
|---|---|---|---|
| Scam Detection (binary) | 0.978 | 0.974 | 0.95–0.96 ± 0.03–0.05 |
| Scam Type Classification (5-class) | 0.789 | 0.744 | 0.53–0.55 ± 0.20 |
| Risk Level Prediction (3-class) | 0.947–0.954 | 0.937–0.948 | 0.81 ± 0.20 |

(Small run-to-run variation is expected: template groups are reshuffled by
seed each time the split is regenerated, and group sizes are uneven.)

The binary Scam Detection task remains strong and stable across folds. The
Scam Type task's CV score is markedly lower and noisier than its single
test-set score — the confusion is concentrated between **Loan** and
**Lottery** (both use reward/urgency vocabulary: "claim now", "call
immediately", large sums), which is a genuine, defensible finding rather
than a leakage artifact, and is a natural candidate for the "Evaluation
rigor" / "Model comparison" follow-up work (e.g. richer n-grams, an
SVM/Random Forest comparison, or template features that disambiguate loan
vs. lottery framing).

## 7. Known limitations of this expansion

- The synthetic messages are template-generated, not scraped from real user
  reports (no such labelled public corpus exists for Nepal). Real-world
  wording variety, spelling errors, and code-mixing will be higher than in
  this dataset — this should be stated as a limitation, not hidden.
- Loan and Promotion scam templates are grounded in the *general*
  advance-fee/credential-phishing pattern documented for Nepal rather than
  one specific press-reported incident (unlike Banking/OTP/Lottery, which
  quote or closely mirror documented cases).
- Because template-level grouping trades exact row-level test_size
  precision for leakage safety, the realized test-set size varies slightly
  run to run depending on which groups are drawn; the greedy per-class
  packing keeps this close to 20% but not exact.
