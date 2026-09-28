"""
Identifies data quality issues in a CSV file without modifying or fixing anything.

Usage:
    python identify_data_quality_issues.py [path_to_csv]

Defaults to Data/Raw/dim_client_raw.csv if no path is given.
"""

import csv
import re
import sys
from collections import Counter, defaultdict

DEFAULT_PATH = r"Data\Raw\dim_client_raw.csv"

STATE_ABBR = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL',
    'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT',
    'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
}


def load_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader, start=2):  # line 2 = first data row
            row['_line'] = i
            rows.append(row)
        return reader.fieldnames, rows


def check_duplicate_ids(rows, id_col='client_id'):
    counter = Counter(r[id_col] for r in rows)
    return {k: v for k, v in counter.items() if v > 1}


def check_missing_values(rows, fieldnames):
    missing = Counter()
    for r in rows:
        for col in fieldnames:
            if (r.get(col) or '').strip() == '':
                missing[col] += 1
    return {k: v for k, v in missing.items() if v}


def check_state_format(rows, col='state'):
    values = Counter(r[col].strip() for r in rows if r.get(col))
    return {k: v for k, v in values.items() if k.upper() not in STATE_ABBR}


def check_categorical_variants(rows, col):
    return dict(Counter(r[col].strip() for r in rows))


def check_date_formats(rows, col='client_since'):
    formats = Counter()
    unparsed = []
    for r in rows:
        v = r[col].strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            formats['YYYY-MM-DD'] += 1
        elif re.match(r'^\d{2}/\d{2}/\d{4}$', v):
            formats['MM/DD/YYYY'] += 1
        else:
            formats['OTHER/UNPARSED'] += 1
            unparsed.append((r['_line'], v))
    return formats, unparsed


def check_city_whitespace_case(rows, col='city'):
    issues = []
    for r in rows:
        v = r[col]
        if v != v.strip() or (v.isupper() and len(v.strip()) > 2):
            issues.append((r['_line'], repr(v)))
    return issues


def check_short_zips(rows, col='zip_code', expected_len=5):
    return [(r['_line'], r[col]) for r in rows if len(r[col].strip()) < expected_len]


def check_age_outliers(rows, col='age', min_age=18, max_age=100):
    issues = []
    for r in rows:
        try:
            a = int(r[col])
            if a < min_age or a > max_age:
                issues.append((r['_line'], a))
        except ValueError:
            issues.append((r['_line'], r[col]))
    return issues


def check_numeric_non_positive(rows, col):
    issues = []
    for r in rows:
        try:
            v = float(r[col])
            if v <= 0:
                issues.append((r['_line'], v))
        except ValueError:
            issues.append((r['_line'], r[col]))
    return issues


def check_duplicate_names(rows, first_col='first_name', last_col='last_name'):
    counter = Counter(
        (r[first_col].strip().lower(), r[last_col].strip().lower()) for r in rows
    )
    return {k: v for k, v in counter.items() if v > 1}


def print_section(title):
    print(f"\n=== {title} ===")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    fieldnames, rows = load_rows(path)

    print(f"File: {path}")
    print(f"Total data rows: {len(rows)}")
    print(f"Columns: {fieldnames}")

    dup_ids = check_duplicate_ids(rows)
    print_section("Duplicate client_id values")
    print(sorted(dup_ids.keys(), key=lambda x: int(x)) if dup_ids else "None found")

    missing = check_missing_values(rows, fieldnames)
    print_section("Missing / blank values by column")
    if missing:
        for col, count in missing.items():
            print(f"  {col}: {count} blank")
    else:
        print("None found")

    bad_states = check_state_format(rows)
    print_section("Non-standard state values (not a 2-letter abbreviation)")
    for k, v in sorted(bad_states.items(), key=lambda x: -x[1]):
        print(f"  '{k}': {v} rows")

    print_section("is_active value variants")
    for k, v in check_categorical_variants(rows, 'is_active').items():
        print(f"  '{k}': {v}")

    date_formats, bad_dates = check_date_formats(rows)
    print_section("client_since date format variants")
    for k, v in date_formats.items():
        print(f"  {k}: {v}")
    if bad_dates:
        print(f"  Unparsed examples: {bad_dates[:10]}")

    city_issues = check_city_whitespace_case(rows)
    print_section(f"city whitespace/case issues ({len(city_issues)} rows)")
    for line, v in city_issues[:15]:
        print(f"  line {line}: {v}")
    if len(city_issues) > 15:
        print(f"  ... and {len(city_issues) - 15} more")

    short_zips = check_short_zips(rows)
    print_section(f"zip codes shorter than 5 digits ({len(short_zips)} rows)")
    for line, z in short_zips[:15]:
        print(f"  line {line}: '{z}'")
    if len(short_zips) > 15:
        print(f"  ... and {len(short_zips) - 15} more")

    age_issues = check_age_outliers(rows)
    print_section(f"age outliers/invalid ({len(age_issues)} rows)")
    for line, a in age_issues:
        print(f"  line {line}: {a}")

    aum_issues = check_numeric_non_positive(rows, 'initial_aum')
    print_section(f"initial_aum invalid/non-positive ({len(aum_issues)} rows)")
    for line, a in aum_issues[:15]:
        print(f"  line {line}: {a}")

    print_section("Categorical value sets (for eyeballing typos/inconsistent labels)")
    print(f"  risk_profile: {check_categorical_variants(rows, 'risk_profile')}")
    print(f"  client_tier: {check_categorical_variants(rows, 'client_tier')}")
    print(f"  primary_account_type: {check_categorical_variants(rows, 'primary_account_type')}")

    dup_names = check_duplicate_names(rows)
    print_section(f"Duplicate (first_name, last_name) pairs ({len(dup_names)})")
    for k, v in list(dup_names.items())[:15]:
        print(f"  {k}: {v} occurrences")
    if len(dup_names) > 15:
        print(f"  ... and {len(dup_names) - 15} more")


if __name__ == '__main__':
    main()
