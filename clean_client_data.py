"""
Cleans Data/Raw/dim_client_raw.csv one data quality issue at a time and writes
the result to Data/Cleaned/dim_client_clean.csv.

Each issue gets its own function (One Piece style: one piece at a time), applied
in sequence in main(). The strategy, justification, and risk behind each fix are
documented in DECISION_LOG.md - keep the two in sync when either changes.

Usage:
    python clean_client_data.py [input_path] [output_path]
"""

import csv
import random
import sys
from collections import Counter

DEFAULT_INPUT = r"Data\Raw\dim_client_raw.csv"
DEFAULT_OUTPUT = r"Data\Cleaned\dim_client_clean.csv"

RANDOM_SEED = 42  # fixed so risk_profile imputation is reproducible

STATE_FULL_TO_ABBR = {
    'PENNSYLVANIA': 'PA', 'NEW JERSEY': 'NJ', 'NEW YORK': 'NY', 'FLORIDA': 'FL',
    'CALIFORNIA': 'CA', 'VIRGINIA': 'VA', 'MASSACHUSETTS': 'MA', 'TEXAS': 'TX',
    'ILLINOIS': 'IL', 'MARYLAND': 'MD', 'GEORGIA': 'GA', 'OHIO': 'OH',
    'NORTH CAROLINA': 'NC', 'DELAWARE': 'DE', 'WASHINGTON': 'WA',
    'CONNECTICUT': 'CT', 'COLORADO': 'CO', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN',
    'ARIZONA': 'AZ',
}


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, [dict(row) for row in reader]


def save_rows(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Issue 1: duplicate / corrupted client records
# ---------------------------------------------------------------------------

def remove_duplicate_records(rows, id_col='client_id'):
    """Keeps the first occurrence of each client_id, drops later duplicates
    (the corrupted-name rows appended at the end of the raw file)."""
    seen = set()
    deduped = []
    removed = 0
    for r in rows:
        cid = r[id_col]
        if cid in seen:
            removed += 1
            continue
        seen.add(cid)
        deduped.append(r)
    print(f"  [duplicates] removed {removed} duplicate record(s)")
    return deduped


# ---------------------------------------------------------------------------
# Issue 3: non-standard state values
# ---------------------------------------------------------------------------

def fix_state(rows, col='state'):
    changed = 0
    for r in rows:
        v = r[col].strip()
        abbr = STATE_FULL_TO_ABBR.get(v.upper())
        if abbr:
            r[col] = abbr
            changed += 1
    print(f"  [state] normalized {changed} full state name(s) to abbreviations")
    return rows


# ---------------------------------------------------------------------------
# Issue 4: inconsistent is_active encoding
# ---------------------------------------------------------------------------

def fix_is_active(rows, col='is_active'):
    changed = 0
    for r in rows:
        original = r[col].strip()
        normalized = 'True' if original.lower() in ('true', 'yes', '1') else 'False'
        if normalized != original:
            changed += 1
        r[col] = normalized
    print(f"  [is_active] normalized {changed} non-standard value(s) to True/False")
    return rows


# ---------------------------------------------------------------------------
# Issue 5: mixed client_since date formats
# ---------------------------------------------------------------------------

def fix_client_since(rows, col='client_since'):
    changed = 0
    for r in rows:
        v = r[col].strip()
        if '/' in v:
            month, day, year = v.split('/')
            r[col] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            changed += 1
    print(f"  [client_since] reformatted {changed} MM/DD/YYYY date(s) to YYYY-MM-DD")
    return rows


# ---------------------------------------------------------------------------
# Issue 6: zip codes shorter than 5 digits
# ---------------------------------------------------------------------------

def fix_zip_code(rows, col='zip_code', width=5):
    changed = 0
    for r in rows:
        v = r[col].strip()
        if len(v) < width:
            r[col] = v.zfill(width)
            changed += 1
    print(f"  [zip_code] zero-padded {changed} short zip code(s) to {width} digits")
    return rows


# ---------------------------------------------------------------------------
# Issue 7: messy city values (whitespace / ALL CAPS)
# ---------------------------------------------------------------------------

def fix_city(rows, col='city'):
    changed = 0
    for r in rows:
        original = r[col]
        v = original.strip()
        if v.isupper() and len(v) > 2:
            v = v.title()
        if v != original:
            changed += 1
        r[col] = v
    print(f"  [city] cleaned whitespace/casing on {changed} value(s)")
    return rows


# ---------------------------------------------------------------------------
# Issue 8: age outliers
# ---------------------------------------------------------------------------

def fix_age_outliers(rows, col='age', flag_col='age_flagged', min_age=18, max_age=100):
    flagged = 0
    for r in rows:
        try:
            a = int(r[col])
            invalid = a < min_age or a > max_age
        except ValueError:
            invalid = True
        if invalid:
            r[col] = ''
            r[flag_col] = 'True'
            flagged += 1
        else:
            r[flag_col] = 'False'
    print(f"  [age] flagged and blanked {flagged} implausible value(s) (see {flag_col})")
    return rows


# ---------------------------------------------------------------------------
# Issue 2: missing risk_profile (confirmed MCAR - see analyze_risk_profile_missingness.py)
# ---------------------------------------------------------------------------

def impute_risk_profile(rows, col='risk_profile', flag_col='risk_profile_imputed', seed=RANDOM_SEED):
    """Fills blanks by drawing from the observed category distribution
    (weighted random choice), since missingness testing found no predictive
    variable to condition a smarter imputation on. See DECISION_LOG.md #2."""
    observed = [r[col].strip() for r in rows if r[col].strip() != '']
    counts = Counter(observed)
    categories = list(counts.keys())
    weights = [counts[c] for c in categories]

    rng = random.Random(seed)
    imputed = 0
    for r in rows:
        if r[col].strip() == '':
            r[col] = rng.choices(categories, weights=weights, k=1)[0]
            r[flag_col] = 'True'
            imputed += 1
        else:
            r[flag_col] = 'False'
    print(f"  [risk_profile] imputed {imputed} missing value(s) via weighted random draw "
          f"from observed distribution {dict(counts)} (see {flag_col})")
    return rows


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT

    fieldnames, rows = load_rows(input_path)
    print(f"Loaded {len(rows)} rows from {input_path}")

    print("\nStep 1/8: duplicate / corrupted records")
    rows = remove_duplicate_records(rows)

    print("Step 2/8: non-standard state values")
    rows = fix_state(rows)

    print("Step 3/8: inconsistent is_active encoding")
    rows = fix_is_active(rows)

    print("Step 4/8: mixed client_since date formats")
    rows = fix_client_since(rows)

    print("Step 5/8: short zip codes")
    rows = fix_zip_code(rows)

    print("Step 6/8: messy city values")
    rows = fix_city(rows)

    print("Step 7/8: age outliers")
    rows = fix_age_outliers(rows)

    print("Step 8/8: missing risk_profile (imputation)")
    rows = impute_risk_profile(rows)

    # New flag columns added by the fixes above go at the end of the schema
    output_fieldnames = fieldnames + ['age_flagged', 'risk_profile_imputed']

    save_rows(output_path, output_fieldnames, rows)
    print(f"\nWrote {len(rows)} cleaned rows to {output_path}")


if __name__ == '__main__':
    main()
