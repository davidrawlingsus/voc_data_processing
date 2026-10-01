#!/usr/bin/env python3
"""
Extract "Country Life B Complex Reviews" from Caplena, process it, and (optionally)
upload to the Visualized DB under a new "Country Life" client/tenant.

This is a product-review dataset (~500 Amazon-style reviews). It has one
text_to_analyze column (the review body, already coded with topics + sentiment in
Caplena) plus scalar metadata (rating, country, date, reviewer, etc.).

Modeling (the "rich" layout):
  - Review Content   open_text   the coded review body (topics + sentiment)
  - Rating           numeric     1-5 star rating
  - Country          geo         reviewer country (blanks skipped)
  - Rewarded Review  multi_choice  Yes / No (incentivised review flag)

Everything else (title, date, reviewer, helpful counts, language,
verified_purchase) rides along in survey_metadata as cross-filters.

Notes on deviations from a naive "rich" layout:
  - verified_purchase is True for all 500 rows, so it is NOT promoted to a
    dimension (it would be a single bar). It is kept in survey_metadata.
  - Each entry's `created` is set to the review `date` so time-series charts
    reflect when the review was written, not when it was imported.

Run dry (no upload, writes JSON + prints a review report):
    python extract_and_upload_country_life_b_complex.py
Upload after review:
    python extract_and_upload_country_life_b_complex.py --upload
"""

import argparse
import json
import os
from collections import Counter
from datetime import datetime

from caplena import Client

from config import Config
from upload_to_db import upload_flattened_data

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ID = "pj_3ve39"
# New tenant — created by upload_to_db.get_or_create_client (client_uuid left None).
CLIENT_NAME = "Country Life"
PROJECT_NAME = "B Complex"
DATA_SOURCE = "Reviews"

# --- Column refs (from the Caplena project schema) ---------------------------
REF_TEXT = "text_aab0d47e"          # text_to_analyze — the review body
REF_REVIEW_ID = "review_id_3be25fa0"
REF_RATING = "rating_05eb5a57"      # numerical 1-5
REF_TITLE = "title_37e48ab1"
REF_DATE = "date_702d8c6d"          # date
REF_VERIFIED = "verified_pu_1794c900"  # boolean (all True -> metadata only)
REF_HELPFUL_YES = "helpful_yes_b37c98a4"
REF_HELPFUL_NO = "helpful_no_26960647"
REF_LANGUAGE = "language_61d87b26"
REF_REVIEWER = "reviewer_02c472b8"
REF_COUNTRY = "country_7926cbcb"
REF_REWARDED = "rewarded_dcba4b2c"  # boolean (471 True / 29 False)

# Promoted dimensions
OPEN_TEXT_DIMENSION_NAME = "Review Content"
OPEN_TEXT_QUESTION = "What did customers say in their review?"

# Scalar columns kept as survey_metadata (human-readable key -> ref)
SCALAR_METADATA = {
    "Rating": REF_RATING,
    "Title": REF_TITLE,
    "Date": REF_DATE,
    "Reviewer": REF_REVIEWER,
    "Helpful (Yes)": REF_HELPFUL_YES,
    "Helpful (No)": REF_HELPFUL_NO,
    "Language": REF_LANGUAGE,
    "Verified Purchase": REF_VERIFIED,
    "Country": REF_COUNTRY,
}


def fmt(value):
    """Coerce a cell value to a JSON-friendly form for survey_metadata."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def extract(project, dry_run=True, output_dir="outputs"):
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "country_life_b_complex_flattened.json")

    flattened = []
    row_count = 0
    # tallies for the review report
    rating_totals = Counter()
    country_totals = Counter()
    rewarded_totals = Counter()
    sentiment_totals = Counter()
    skipped_country_blank = 0

    print("Loading rows...", end=" ", flush=True)
    for row in project.list_rows():
        row_count += 1
        if row_count % 200 == 0:
            print(f"{row_count}...", end=" ", flush=True)

        cells = {col.ref: getattr(col, "value", None) for col in row.columns}

        # Event time = the review date; fall back to row created.
        review_date = cells.get(REF_DATE)
        created = fmt(review_date) if review_date else fmt(getattr(row, "created", None))
        last_modified = fmt(getattr(row, "last_modified", None))

        # Build survey_metadata from scalar columns (skip blanks).
        survey_metadata = {}
        for label, ref in SCALAR_METADATA.items():
            v = fmt(cells.get(ref))
            if v not in (None, ""):
                survey_metadata[label] = v

        def base_entry():
            return {
                "respondent_id": row.id,
                "created": created,
                "last_modified": last_modified,
                "client_id": None,
                "client_uuid": None,        # new tenant -> created by name on upload
                "client_name": CLIENT_NAME,
                "project_id": project.id,
                "project_name": PROJECT_NAME,
                "total_rows": row_count,
                "data_source": DATA_SOURCE,
                "survey_metadata": survey_metadata.copy() if survey_metadata else None,
                "overall_sentiment": None,
                "topics": [],
            }

        # 1) Open-text dimension: the coded review body.
        for col in row.columns:
            if col.type == "text_to_analyze" and col.value:
                topics = [{"category": t.category, "label": t.label} for t in col.topics]
                sentiment = getattr(col, "sentiment_overall", None)
                e = base_entry()
                e.update({
                    "dimension_ref": col.ref,
                    "dimension_name": OPEN_TEXT_DIMENSION_NAME,
                    "question_text": OPEN_TEXT_QUESTION,
                    "question_type": "open_text",
                    "value": col.value,
                    "overall_sentiment": sentiment,
                    "topics": topics,
                })
                flattened.append(e)
                if sentiment:
                    sentiment_totals[sentiment] += 1

        # 2) Rating -> numeric dimension.
        rating = cells.get(REF_RATING)
        if rating not in (None, ""):
            try:
                rating_val = int(rating)
                e = base_entry()
                e.update({
                    "dimension_ref": REF_RATING,
                    "dimension_name": "Rating",
                    "question_text": "Star rating given by the reviewer",
                    "question_type": "numeric",
                    "value": str(rating_val),
                })
                flattened.append(e)
                rating_totals[rating_val] += 1
            except (ValueError, TypeError):
                pass

        # 3) Country -> geo dimension (skip blanks).
        country = cells.get(REF_COUNTRY)
        if country not in (None, ""):
            e = base_entry()
            e.update({
                "dimension_ref": REF_COUNTRY,
                "dimension_name": "Country",
                "question_text": "Reviewer country",
                "question_type": "geo",
                "value": str(country),
            })
            flattened.append(e)
            country_totals[str(country)] += 1
        else:
            skipped_country_blank += 1

        # 4) Rewarded -> multi_choice dimension (Yes / No).
        rewarded = cells.get(REF_REWARDED)
        if rewarded is not None:
            val = "Yes" if rewarded else "No"
            e = base_entry()
            e.update({
                "dimension_ref": REF_REWARDED,
                "dimension_name": "Rewarded Review",
                "question_text": "Was the review incentivised / rewarded?",
                "question_type": "multi_choice",
                "value": val,
            })
            flattened.append(e)
            rewarded_totals[val] += 1

    for e in flattened:
        e["total_rows"] = row_count

    print(f"\n✓ {row_count} reviews -> {len(flattened)} entries")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"flattened_results": flattened}, f, indent=2, ensure_ascii=False)

    _print_report(row_count, flattened, rating_totals, country_totals,
                  rewarded_totals, sentiment_totals, skipped_country_blank, out_file)

    if not dry_run:
        print("\n📤 Uploading to database (creates the 'Country Life' client)...")
        upload_flattened_data(out_file, batch_size=1000)
    else:
        print("\n🟡 DRY RUN — nothing uploaded. Review above, then re-run with --upload.")

    return out_file


def _print_report(row_count, flattened, rating_totals, country_totals,
                  rewarded_totals, sentiment_totals, skipped_country_blank, out_file):
    print("\n" + "=" * 78)
    print(f"REVIEW REPORT — Country Life B Complex Reviews ({row_count} reviews)")
    print(f"  client: {CLIENT_NAME}  |  project: {PROJECT_NAME}  |  source: {DATA_SOURCE}")
    print("=" * 78)

    def dim_count(name):
        return sum(1 for e in flattened if e["dimension_name"] == name)

    print(f"\n📝 OPEN-TEXT DIMENSION:")
    print(f"   - {OPEN_TEXT_DIMENSION_NAME}  ({dim_count(OPEN_TEXT_DIMENSION_NAME)} coded reviews)")
    for s, c in sentiment_totals.most_common():
        print(f"        sentiment {s:>9}: {c}")

    print(f"\n🔢 NUMERIC DIMENSION — Rating  ({dim_count('Rating')} rows):")
    for r, c in sorted(rating_totals.items(), reverse=True):
        print(f"        {r}★  {c}")

    print(f"\n🌍 GEO DIMENSION — Country  ({dim_count('Country')} rows, {skipped_country_blank} blank skipped):")
    for country, c in country_totals.most_common(10):
        print(f"        {c:>5}  {country}")
    if len(country_totals) > 10:
        print(f"        ... (+{len(country_totals) - 10} more countries)")

    print(f"\n🔘 MULTI-CHOICE DIMENSION — Rewarded Review  ({dim_count('Rewarded Review')} rows):")
    for v, c in rewarded_totals.most_common():
        print(f"        {c:>5}  {v}")

    print(f"\n🏷️  SURVEY METADATA KEYS: {', '.join(SCALAR_METADATA.keys())}")
    print(f"\n💾 Written: {out_file}")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help="Upload to DB after processing")
    args = parser.parse_args()

    client = Client(api_key=Config.API_KEY)
    print(f"📡 Retrieving {PROJECT_ID}...")
    project = client.projects.retrieve(id=PROJECT_ID)
    print(f"📊 {project.name}")
    extract(project, dry_run=not args.upload)


if __name__ == "__main__":
    main()
