# Data Cleaning Decision Log

Tracks every data quality issue found, the strategy chosen to address it, why that
strategy was chosen over the alternatives, and the residual risk it carries. Update
this file whenever a new issue is found or a strategy changes — it's the record of
*why* the cleaned data looks the way it does, not just what changed.

Source file: `Data/Raw/dim_client_raw.csv`
Output file: `Data/Cleaned/dim_client_clean.csv`
Cleaning script: `clean_client_data.py`

---

## 1. Duplicate / corrupted client records

- **Issue**: 20 `client_id`s each appear twice. The second occurrence (the last 20
  rows of the file) is identical to the original in every field except `last_name`,
  which has been corrupted with leetspeak-style character substitution (e.g.
  `Harding` → `H@Rding`, `Green` → `Gr3En`).
- **Strategy**: Drop the duplicate occurrence, keep the first (clean-named) row for
  each `client_id`.
- **Justification**: `client_id` is the primary key (1–2525, otherwise unique).
  These are exact duplicates of a real record with a corrupted name field, not a
  legitimate name change — there's no accompanying evidence (e.g. an updated
  timestamp) of an intentional edit.
- **Risk**: If a corrupted row ever *did* represent a genuine correction rather than
  injected noise, that correction would be silently discarded. Low likelihood here
  given the consistent, synthetic-looking corruption pattern, but worth a spot check
  if this pattern shows up in future data pulls from the same source.

---

## 2. Missing `risk_profile` (155 rows, 6.1%)

- **Issue**: `risk_profile` is blank for 155 of 2,545 rows.
- **Missingness analysis**: Chi-square tests of missingness against `client_tier`,
  `primary_account_type`, `state`, `advisor_id`, `is_active`, `age group`,
  `initial_aum` quartile, `client_since` year, and membership in the corrupted
  duplicate block all returned p > 0.05 (see `analyze_risk_profile_missingness.py`
  output). No variable predicts missingness — the pattern looks like **MCAR**
  (missing completely at random).
- **Strategy**: Impute missing values by drawing randomly from the *observed*
  category distribution (weighted by each category's observed frequency), using a
  fixed random seed for reproducibility. A new `risk_profile_imputed` flag column
  (`True`/`False`) is added so imputed rows stay traceable.
- **Justification**: Because missingness is MCAR, there's no defensible subgroup
  (state, tier, advisor, etc.) to condition an imputation on — any conditional
  imputation would be fabricating a correlation the data doesn't support. A single
  mode-fill (always "Balanced") would distort the distribution by
  over-representing the plurality category. Proportional random draw preserves the
  original marginal distribution shape, which is the least-biased option available
  without more information.
- **Risk**: Imputed values are statistically plausible, not individually verified —
  they do NOT reflect an actual client's stated risk tolerance. Any downstream use
  that matters at the individual-client level (e.g. suitability/compliance checks)
  must filter on `risk_profile_imputed == True` and treat those rows as
  estimates requiring follow-up with the source system, not as fact.

---

## 3. Non-standard `state` values (228 rows)

- **Issue**: 228 rows spell out the full state name (`Pennsylvania`, `New Jersey`,
  etc. — 20 distinct full names) instead of using the 2-letter USPS abbreviation
  used everywhere else.
- **Strategy**: Map each full name to its standard abbreviation via a lookup table.
- **Justification**: Unambiguous 1:1 mapping; no information is lost or guessed.
- **Risk**: Low. Only risk is an unmapped new full-name spelling appearing in a
  future data pull if the lookup table isn't extended to cover it (the script will
  currently pass such values through unchanged rather than fail).

---

## 4. Inconsistent `is_active` encoding (all 2,545 rows use 1 of 4 formats)

- **Issue**: Values appear as `True`, `False`, `0`, and `yes` — no `1` or `no`
  variant appeared, but it's still 4 different representations of a boolean.
- **Strategy**: Normalize `True` / `1` / `yes` → boolean `True`; `False` / `0` →
  boolean `False`.
- **Justification**: All observed values map unambiguously onto a boolean.
- **Risk**: Assumes `'yes'` is semantically equivalent to `True` (active). This is
  the only reasonable reading given the column name, but it's an assumption absent
  a data dictionary confirming it.

---

## 5. Mixed `client_since` date formats (76 rows)

- **Issue**: 2,469 rows use `YYYY-MM-DD`; 76 rows use `MM/DD/YYYY`.
- **Strategy**: Parse both formats and normalize everything to ISO 8601
  (`YYYY-MM-DD`).
- **Justification**: ISO format is unambiguous and sorts correctly as a string.
- **Risk**: `MM/DD/YYYY` vs `DD/MM/YYYY` ambiguity is possible in general, but every
  first-slot value observed in the `/`-formatted rows is ≤ 12, and the source
  system is US-based, so US month/day ordering is assumed. If a future batch
  includes a non-US-formatted date this assumption should be revisited.

---

## 6. Zip codes shorter than 5 digits (234 rows)

- **Issue**: 234 rows have zip codes with fewer than 5 digits (e.g. `3897`,
  `1084`).
- **Strategy**: Zero-pad to 5 digits and store as text, not a number.
- **Justification**: US zip codes are fixed-width identifiers, not quantities —
  leading zeros are legitimate (common in New England / mid-Atlantic states, which
  is exactly where the short values cluster). The pattern is consistent with the
  zip code having been stored/exported as a number upstream, which silently drops
  leading zeros.
- **Risk**: If a short value was actually a genuine data-entry error (not a
  leading-zero loss), zero-padding would mask it rather than surface it. The
  regional clustering supports the leading-zero theory but this hasn't been
  verified against a canonical zip/state reference table.

---

## 7. Messy `city` values (50 rows)

- **Issue**: 50 rows have leading/trailing whitespace and/or are in ALL CAPS,
  instead of the Title Case used elsewhere.
- **Strategy**: Trim whitespace; convert ALL-CAPS values to Title Case.
- **Justification**: Cosmetic standardization only — doesn't change the
  identified city, just its formatting, matching the convention used by the
  majority of rows.
- **Risk**: Naive title-casing can mis-capitalize names with internal capitals or
  special constructs (e.g. `McDonaldville`). Worth a spot check of the output,
  though the synthetic city names in this dataset are unlikely to hit that case.

---

## 8. Age outliers (5 rows: `0`, `0`, `999`, `999`, `-5`)

- **Issue**: 5 rows have implausible ages for an adult client.
- **Strategy**: Set to blank/null and add an `age_flagged` column (`True`/`False`)
  rather than imputing a value.
- **Justification**: Unlike `risk_profile`, there's no basis (statistical or
  otherwise) to guess a plausible age for these 5 clients — mean/median
  imputation would materially misrepresent a specific individual, which is a
  different (worse) kind of error than leaving it blank.
- **Risk**: Introduces 5 rows of missing `age` data. If `age` feeds a required
  downstream calculation (e.g. age-based suitability rules), these 5 rows need
  manual verification against the source system before being used.

---

## 9. Duplicate `(first_name, last_name)` pairs under different `client_id`s (50 pairs)

- **Issue**: 50 name pairs (e.g. "Robert Smith" ×5, "Michael Smith" ×3) appear
  under different `client_id`s.
- **Strategy**: No automated fix. Flagged for manual review only — not treated as
  a confirmed error.
- **Justification**: With 2,545 independent synthetic clients, common-name
  collisions are expected by chance; there's no corroborating field (DOB,
  address, SSN) available to confirm these are the same person duplicated under
  two IDs.
- **Risk**: If some of these genuinely are the same client under two IDs, they
  remain unmerged, which would inflate client counts and AUM aggregates in any
  downstream reporting.
