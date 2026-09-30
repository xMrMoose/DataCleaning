"""
Analyzes the missingness pattern of the `risk_profile` column in the client CSV.

This does NOT fix or impute anything - it only characterizes whether the missing
values look randomly distributed (MCAR) or associated with other columns
(MAR / MNAR), which determines the right way to handle them later.

Usage:
    python analyze_risk_profile_missingness.py [path_to_csv]

Defaults to Data/Raw/dim_client_raw.csv if no path is given.
"""

import csv
import math
import sys
from collections import Counter, defaultdict

DEFAULT_PATH = r"Data\Raw\dim_client_raw.csv"

# Maps the non-standard full state names found in the data to their abbreviation,
# purely so the missingness breakdown by state isn't split across two spellings
# of the same state. This does not touch the source file.
STATE_FULL_TO_ABBR = {
    'PENNSYLVANIA': 'PA', 'NEW JERSEY': 'NJ', 'NEW YORK': 'NY', 'FLORIDA': 'FL',
    'CALIFORNIA': 'CA', 'VIRGINIA': 'VA', 'MASSACHUSETTS': 'MA', 'TEXAS': 'TX',
    'ILLINOIS': 'IL', 'MARYLAND': 'MD', 'GEORGIA': 'GA', 'OHIO': 'OH',
    'NORTH CAROLINA': 'NC', 'DELAWARE': 'DE', 'WASHINGTON': 'WA',
    'CONNECTICUT': 'CT', 'COLORADO': 'CO', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN',
    'ARIZONA': 'AZ',
}


# ---------------------------------------------------------------------------
# Chi-square machinery (stdlib only - no scipy available in this environment)
# ---------------------------------------------------------------------------

def _gammainc_series(a, x):
    ap = a
    summ = 1.0 / a
    delta = summ
    for _ in range(500):
        ap += 1
        delta *= x / ap
        summ += delta
        if abs(delta) < abs(summ) * 1e-14:
            break
    return summ * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammaincc_cf(a, x):
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x, df):
    """P(X > x) for a chi-square distribution with df degrees of freedom."""
    if x <= 0:
        return 1.0
    a = df / 2.0
    xx = x / 2.0
    if xx < a + 1.0:
        return 1.0 - _gammainc_series(a, xx)
    return _gammaincc_cf(a, xx)


def chi_square_test(rows, is_missing_fn, group_fn):
    """2 x K test of independence between missingness and a grouping variable."""
    table = defaultdict(lambda: [0, 0])  # group -> [missing_count, present_count]
    for r in rows:
        g = group_fn(r)
        table[g][0 if is_missing_fn(r) else 1] += 1

    groups = list(table.keys())
    total = len(rows)
    total_missing = sum(v[0] for v in table.values())
    total_present = sum(v[1] for v in table.values())
    if total_missing == 0 or total_present == 0 or len(groups) < 2:
        return None  # no variation to test

    chi2 = 0.0
    for g in groups:
        row_total = sum(table[g])
        for idx, col_total in enumerate((total_missing, total_present)):
            expected = row_total * col_total / total
            observed = table[g][idx]
            if expected > 0:
                chi2 += (observed - expected) ** 2 / expected
    df = len(groups) - 1
    p = chi2_sf(chi2, df)
    return chi2, df, p, table


# ---------------------------------------------------------------------------
# Data loading / helpers
# ---------------------------------------------------------------------------

def load_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader, start=2):
            row['_line'] = i
            rows.append(row)
        return rows


def is_missing(r, col='risk_profile'):
    return (r.get(col) or '').strip() == ''


def normalize_state(r):
    v = r['state'].strip().upper()
    return STATE_FULL_TO_ABBR.get(v, v)


def normalize_is_active(r):
    v = r['is_active'].strip().lower()
    if v in ('true', 'yes', '1'):
        return 'active'
    return 'inactive'


def age_bin(r):
    try:
        a = int(r['age'])
    except ValueError:
        return 'invalid'
    if a < 18 or a > 100:
        return 'invalid'
    if a <= 35:
        return '18-35'
    if a <= 50:
        return '36-50'
    if a <= 65:
        return '51-65'
    if a <= 80:
        return '66-80'
    return '81+'


def aum_quartile_fn(rows):
    values = sorted(float(r['initial_aum']) for r in rows)
    n = len(values)

    def pct(p):
        return values[int(p * (n - 1))]

    q1, q2, q3 = pct(0.25), pct(0.5), pct(0.75)

    def fn(r):
        v = float(r['initial_aum'])
        if v <= q1:
            return f'Q1 (<= {q1:,.0f})'
        if v <= q2:
            return f'Q2 (<= {q2:,.0f})'
        if v <= q3:
            return f'Q3 (<= {q3:,.0f})'
        return f'Q4 (> {q3:,.0f})'

    return fn


def client_since_year(r):
    v = r['client_since'].strip()
    if '/' in v:
        parts = v.split('/')
        return parts[2] if len(parts) == 3 else 'invalid'
    if '-' in v:
        return v.split('-')[0]
    return 'invalid'


def is_corrupted_duplicate_block(r, rows):
    """The last 20 rows in the file are known fuzzy-duplicate records
    (same client_id as an earlier row, last_name corrupted). Flag them so we
    can check whether missingness clusters there rather than in the real data."""
    max_line = max(row['_line'] for row in rows)
    return r['_line'] > max_line - 20


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_breakdown(title, rows, group_fn):
    print(f"\n=== Missingness by {title} ===")
    counts = defaultdict(lambda: [0, 0])  # group -> [missing, total]
    for r in rows:
        g = group_fn(r)
        counts[g][1] += 1
        if is_missing(r):
            counts[g][0] += 1

    overall_missing = sum(v[0] for v in counts.values())
    overall_total = sum(v[1] for v in counts.values())
    overall_rate = overall_missing / overall_total * 100

    for g in sorted(counts.keys(), key=lambda k: -counts[k][1]):
        missing, total = counts[g]
        rate = missing / total * 100 if total else 0
        flag = "  <-- above overall rate" if rate > overall_rate * 1.3 and total >= 10 else ""
        print(f"  {g!s:<25} missing {missing:>4} / {total:<5} ({rate:5.1f}%){flag}")

    result = chi_square_test(rows, is_missing, group_fn)
    if result:
        chi2, df, p, _ = result
        sig = "SIGNIFICANT (p < 0.05)" if p < 0.05 else "not significant"
        print(f"  Chi-square test: chi2={chi2:.2f}, df={df}, p={p:.4f} -> {sig}")
    else:
        print("  Chi-square test: not applicable (insufficient variation)")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    rows = load_rows(path)

    total = len(rows)
    missing = sum(1 for r in rows if is_missing(r))
    print(f"File: {path}")
    print(f"Total rows: {total}")
    print(f"risk_profile missing: {missing} ({missing / total * 100:.1f}%)")

    print_breakdown("client_tier", rows, lambda r: r['client_tier'].strip())
    print_breakdown("primary_account_type", rows, lambda r: r['primary_account_type'].strip())
    print_breakdown("state", rows, normalize_state)
    print_breakdown("advisor_id", rows, lambda r: r['advisor_id'].strip().zfill(2))
    print_breakdown("is_active", rows, normalize_is_active)
    print_breakdown("age group", rows, age_bin)
    print_breakdown("initial_aum quartile", rows, aum_quartile_fn(rows))
    print_breakdown("client_since year", rows, client_since_year)
    print_breakdown(
        "corrupted duplicate block (last 20 rows)",
        rows,
        lambda r: is_corrupted_duplicate_block(r, rows),
    )

    print(
        "\nInterpretation guide: a SIGNIFICANT chi-square result means missingness "
        "is NOT random with respect to that variable (MAR), so imputing by group "
        "mean/mode within that variable is more defensible than dropping rows or "
        "a single global fill value. If nothing comes back significant, missingness "
        "looks closer to MCAR (missing completely at random)."
    )


if __name__ == '__main__':
    main()
