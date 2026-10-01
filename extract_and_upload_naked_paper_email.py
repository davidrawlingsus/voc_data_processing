#!/usr/bin/env python3
"""
Extract "Naked Paper Email Survey" from Caplena, process it, and (optionally) upload to DB.

This survey contains 5 multi-select questions that are stored one-column-per-option.
Following our established multi-select pattern (see augment_brand_survey_dimensions.py),
each multi-select question is converted into a `multi_choice` dimension: one long row per
selected option, sharing a single dimension_ref. This gives Visualized per-option totals
AND cross-segmentation.

Open-text columns (text_to_analyze) flatten into normal coded dimensions.
Scalar columns ride along in survey_metadata for filtering. PII is excluded.

Run dry (no upload, writes JSON + prints review report):
    python extract_and_upload_naked_paper_email.py
Upload after review:
    python extract_and_upload_naked_paper_email.py --upload
"""

import argparse
import json
import os
import sys
from datetime import datetime

from caplena import Client

from config import Config
from upload_to_db import upload_flattened_data

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ID = "pj_ygknz"
# Target the "client" tenant (NakedPaper / slug nakedpaper), NOT the lead tenant.
CLIENT_NAME = "NakedPaper"
TARGET_CLIENT_UUID = "c5a4a90e-e1c1-4cb9-a7ed-b463aefd6856"
PROJECT_NAME = "Initial Research"
DATA_SOURCE = "Email Survey"

# --- Multi-select questions -------------------------------------------------
# Prefixed groups: any column whose name starts with the prefix is an option of
# that question. The option value is the cell value (clean label, e.g. "Andrex").
PREFIX_GROUPS = {
    "Before: ": {
        "dimension_ref": "brands_before",
        "dimension_name": "Brands Used Before Naked Paper",
        "question_text": "Which paper brands did you buy before Naked Paper?",
    },
    "Eco: ": {
        "dimension_ref": "eco_brands_tried",
        "dimension_name": "Other Eco Brands Tried",
        "question_text": "Which other eco / alternative paper brands have you tried?",
    },
}

# Un-prefixed groups: explicit member column names (exact match on Caplena column name).
EXPLICIT_GROUPS = {
    "products_tried": {
        "dimension_name": "Naked Paper Products Tried",
        "question_text": "Which Naked Paper products have you tried?",
        "columns": ["Bamboo", "Recycled", "Unbleached"],
    },
    "matters_most": {
        "dimension_name": "What Matters Most When Choosing Paper Goods",
        "question_text": "When choosing paper goods for your home, which of these matter most?",
        "columns": [
            "Plastic-free packaging",
            "Made from recycled paper",
            "Made from bamboo (tree-free)",
            "Softness / comfort",
            "Strength / no tearing",
            "Value for money",
            "Convenience of home delivery",
            "Looks good in the bathroom",
            "Independent / ethical business",
            "Low climate footprint",
            "Supports a charity or cause",
            "No wrappers on the rolls",
            "Convenience of a subscription",
        ],
    },
    "trust_sources": {
        "dimension_name": "Trusted Advice Sources",
        "question_text": "When looking for advice on eco-friendly products / sustainable living, who do you actually trust?",
        "columns": [
            "Instagram accounts / influencers",
            "TikTok creators",
            "YouTubers",
            "Podcasts",
            "Newsletters",
            "Print magazines",
            "Online publications (Guardian, Ethical Consumer, etc.)",
            "Word of mouth / friends & family",
            "Facebook groups or forums",
            "Product review sites (Which?, Trustpilot, etc.)",
            "None of these really",
        ],
    },
}

# --- Scalar metadata (one value per respondent; kept in survey_metadata) -----
SCALAR_METADATA = {
    "Which best describes you?",
    "How long ago did you first try Naked Paper?",
    "Which Naked Paper product was your main purchase?",
    "How did you first come across Naked Paper?",
    "Would you ever go back to a non-eco brand?",
    "Have you ever tried any other eco / alternative paper brands?",
    "Have you ever had a subscription to Naked Paper?",
    "Which age bracket are you in?",
    "How many adults (18+) in your household?",
    "How many children (under 18) in your household?",
    "Would you be up for a 20-minute chat with us to go into more detail?",
    "Start Date (UTC)",
    "Submit Date (UTC)",
    "Network ID",
}

# Single-choice categorical questions -> their own multi_choice dimension
# (one row per respondent, value = the chosen answer). dimension_name = the question.
# These ALSO stay in survey_metadata above, so they remain available as cross-filters.
SINGLE_CHOICE_QUESTIONS = {
    "Which best describes you?": "which_best_describes",
    "How long ago did you first try Naked Paper?": "how_long_ago_first_try",
    "Which Naked Paper product was your main purchase?": "main_product_purchased",
    "How did you first come across Naked Paper?": "how_came_across",
    "Would you ever go back to a non-eco brand?": "would_go_back_noneco",
    "Have you ever tried any other eco / alternative paper brands?": "tried_other_eco_yn",
    "Have you ever had a subscription to Naked Paper?": "subscription_status",
    "Which age bracket are you in?": "age_bracket",
}

# Numeric questions -> their own numeric dimension.
NUMERIC_QUESTIONS = {
    "How many adults (18+) in your household?": "household_adults",
    "How many children (under 18) in your household?": "household_children",
}

# Numeric fields where implausible outliers are treated as null (data entry junk).
HOUSEHOLD_FIELDS = {
    "How many adults (18+) in your household?",
    "How many children (under 18) in your household?",
}
HOUSEHOLD_MAX = 20

# --- PII / system columns to exclude entirely --------------------------------
PII_NAME_PREFIXES = ("If you'd like to be entered into the prize draw",)
PII_EXCLUDE = {"first_name"}
SYSTEM_EXCLUDE = {"Tags", "Ending", "Just checking...", "Stage Date (UTC)"}
# Dropped after review: # duplicates respondent_id; Response Type is a single value.
DROPPED_PER_REVIEW = {"#", "Response Type"}


def is_pii(name):
    if name in PII_EXCLUDE:
        return True
    return any(name.startswith(p) for p in PII_NAME_PREFIXES)


def format_value(value):
    """Coerce a cell value to a JSON-friendly form for survey_metadata."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def classify_columns(project):
    """Return dicts describing how each non-open-text column is treated.

    Returns:
        column_map: ref -> name
        groups: dimension_ref -> {meta..., 'refs': [col refs]}
        scalar_refs: set of refs kept as survey_metadata
        excluded: list of (name, reason)
        unassigned: list of names that look like options but matched no group
    """
    column_map = {c.ref: c.name for c in project.columns}
    name_to_ref = {c.name: c.ref for c in project.columns}

    groups = {}
    assigned_refs = set()

    # Prefixed groups
    for prefix, meta in PREFIX_GROUPS.items():
        refs = [c.ref for c in project.columns
                if c.type != "text_to_analyze" and (c.name or "").startswith(prefix)]
        groups[meta["dimension_ref"]] = {**meta, "prefix": prefix, "refs": refs}
        assigned_refs.update(refs)

    # Explicit groups
    for dim_ref, meta in EXPLICIT_GROUPS.items():
        refs = [name_to_ref[n] for n in meta["columns"] if n in name_to_ref]
        missing = [n for n in meta["columns"] if n not in name_to_ref]
        groups[dim_ref] = {**meta, "dimension_ref": dim_ref, "refs": refs, "missing": missing}
        assigned_refs.update(refs)

    scalar_refs = set()
    excluded = []
    for c in project.columns:
        if c.type == "text_to_analyze" or c.ref in assigned_refs:
            continue
        name = c.name or c.ref
        if is_pii(name):
            excluded.append((name, "PII"))
        elif name in DROPPED_PER_REVIEW:
            excluded.append((name, "dropped per review"))
        elif name in SYSTEM_EXCLUDE:
            excluded.append((name, "system/noise"))
        elif name in SCALAR_METADATA:
            scalar_refs.add(c.ref)
        else:
            excluded.append((name, "unmapped — defaulted to excluded"))

    return column_map, groups, scalar_refs, excluded


def extract(project, dry_run=True, output_dir="outputs"):
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "naked_paper_email_flattened.json")

    column_map, groups, scalar_refs, excluded = classify_columns(project)
    ref_to_group = {ref: (dim_ref, meta)
                    for dim_ref, meta in groups.items() for ref in meta["refs"]}

    # Single-choice / numeric question columns -> their own dimensions
    name_to_ref = {c.name: c.ref for c in project.columns}
    single_by_ref = {name_to_ref[n]: (dr, n)
                     for n, dr in SINGLE_CHOICE_QUESTIONS.items() if n in name_to_ref}
    numeric_by_ref = {name_to_ref[n]: (dr, n)
                      for n, dr in NUMERIC_QUESTIONS.items() if n in name_to_ref}

    flattened = []
    row_count = 0
    # tallies for the review report
    option_totals = {dim_ref: {} for dim_ref in groups}
    single_totals = {dr: {} for dr in SINGLE_CHOICE_QUESTIONS.values()}
    numeric_counts = {dr: 0 for dr in NUMERIC_QUESTIONS.values()}
    scalar_values = {column_map[r]: set() for r in scalar_refs}

    print("Loading rows...", end=" ", flush=True)
    for row in project.list_rows():
        row_count += 1
        if row_count % 200 == 0:
            print(f"{row_count}...", end=" ", flush=True)

        created = getattr(row, "created", None)
        last_modified = getattr(row, "last_modified", None)
        if isinstance(created, datetime):
            created = created.isoformat()
        if isinstance(last_modified, datetime):
            last_modified = last_modified.isoformat()

        # Build survey_metadata from scalar columns only
        survey_metadata = {}
        for col in row.columns:
            if col.ref in scalar_refs and col.value not in (None, ""):
                fv = format_value(col.value)
                name = column_map.get(col.ref, col.ref)
                # Treat implausible household counts as null (data-entry junk)
                if name in HOUSEHOLD_FIELDS:
                    try:
                        if int(fv) > HOUSEHOLD_MAX:
                            fv = None
                    except (ValueError, TypeError):
                        fv = None
                if fv is not None and fv != "":
                    survey_metadata[name] = fv
                    scalar_values[name].add(str(fv)[:60])

        def base_entry():
            return {
                "respondent_id": row.id,
                "created": created,
                "last_modified": last_modified,
                "client_id": None,
                "client_uuid": TARGET_CLIENT_UUID,
                "client_name": CLIENT_NAME,
                "project_id": project.id,
                "project_name": PROJECT_NAME,
                "total_rows": row_count,
                "data_source": DATA_SOURCE,
                "survey_metadata": survey_metadata.copy() if survey_metadata else None,
                "overall_sentiment": None,
                "topics": [],
            }

        for col in row.columns:
            # Open-text dimension (already coded in Caplena)
            if col.type == "text_to_analyze":
                if not col.value:
                    continue
                topics = [{"category": t.category, "label": t.label} for t in col.topics]
                e = base_entry()
                e.update({
                    "dimension_ref": col.ref,
                    "dimension_name": column_map.get(col.ref),
                    "question_text": column_map.get(col.ref),
                    "question_type": "open_text",
                    "value": col.value,
                    "overall_sentiment": getattr(col, "sentiment_overall", None),
                    "topics": topics,
                })
                flattened.append(e)

            # Multi-select option (selected when cell non-empty)
            elif col.ref in ref_to_group and col.value not in (None, ""):
                dim_ref, meta = ref_to_group[col.ref]
                prefix = meta.get("prefix")
                col_name = column_map.get(col.ref, "")
                # Clean option label: prefer the cell value; strip prefix from name otherwise
                option = col.value if isinstance(col.value, str) and col.value.strip() else (
                    col_name[len(prefix):] if prefix and col_name.startswith(prefix) else col_name)
                e = base_entry()
                e.update({
                    "dimension_ref": dim_ref,
                    "dimension_name": meta["dimension_name"],
                    "question_text": meta["question_text"],
                    "question_type": "multi_choice",
                    "value": option,
                })
                flattened.append(e)
                option_totals[dim_ref][option] = option_totals[dim_ref].get(option, 0) + 1

            # Single-choice categorical question -> one multi_choice row per respondent
            elif col.ref in single_by_ref and col.value not in (None, ""):
                dim_ref, qname = single_by_ref[col.ref]
                val = str(col.value)
                e = base_entry()
                e.update({
                    "dimension_ref": dim_ref,
                    "dimension_name": qname,
                    "question_text": qname,
                    "question_type": "multi_choice",
                    "value": val,
                })
                flattened.append(e)
                single_totals[dim_ref][val] = single_totals[dim_ref].get(val, 0) + 1

            # Numeric question -> one numeric row per respondent (outliers dropped)
            elif col.ref in numeric_by_ref and col.value not in (None, ""):
                dim_ref, qname = numeric_by_ref[col.ref]
                try:
                    n = int(col.value)
                except (ValueError, TypeError):
                    continue
                if n > HOUSEHOLD_MAX:
                    continue
                e = base_entry()
                e.update({
                    "dimension_ref": dim_ref,
                    "dimension_name": qname,
                    "question_text": qname,
                    "question_type": "numeric",
                    "value": str(n),
                })
                flattened.append(e)
                numeric_counts[dim_ref] += 1

    for e in flattened:
        e["total_rows"] = row_count

    print(f"\n✓ {row_count} respondents -> {len(flattened)} entries")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"flattened_results": flattened}, f, indent=2, ensure_ascii=False)

    _print_report(row_count, flattened, groups, column_map, option_totals,
                  single_totals, numeric_counts, scalar_values, excluded, out_file)

    if not dry_run:
        print("\n📤 Uploading to database...")
        upload_flattened_data(out_file, batch_size=1000)
    else:
        print("\n🟡 DRY RUN — nothing uploaded. Review above, then re-run with --upload.")

    return out_file


def _print_report(row_count, flattened, groups, column_map, option_totals,
                  single_totals, numeric_counts, scalar_values, excluded, out_file):
    print("\n" + "=" * 78)
    print(f"REVIEW REPORT — Naked Paper Email Survey ({row_count} respondents)")
    print("=" * 78)

    open_text = sorted({e["dimension_name"] for e in flattened if e["question_type"] == "open_text"})
    print(f"\n📝 OPEN-TEXT DIMENSIONS ({len(open_text)}):")
    for n in open_text:
        cnt = sum(1 for e in flattened if e["dimension_name"] == n)
        print(f"   - {n}  ({cnt} coded responses)")

    print(f"\n📊 MULTI-SELECT DIMENSIONS ({len(groups)}):")
    for dim_ref, meta in groups.items():
        totals = option_totals.get(dim_ref, {})
        respondents = len(set(e["respondent_id"] for e in flattened if e["dimension_ref"] == dim_ref))
        missing = meta.get("missing")
        print(f"\n   ▸ {meta['dimension_name']}  [{dim_ref}]")
        print(f"     q: {meta['question_text']}")
        print(f"     {len(meta['refs'])} option columns | {respondents} respondents selected ≥1 | {sum(totals.values())} total selections")
        if missing:
            print(f"     ⚠️ configured but NOT found in project: {missing}")
        for opt, cnt in sorted(totals.items(), key=lambda kv: -kv[1])[:8]:
            print(f"        {cnt:>5}  {opt}")
        if len(totals) > 8:
            print(f"        ... (+{len(totals) - 8} more options)")

    print(f"\n🔘 SINGLE-CHOICE DIMENSIONS ({len(SINGLE_CHOICE_QUESTIONS)}):")
    for qname, dim_ref in SINGLE_CHOICE_QUESTIONS.items():
        totals = single_totals.get(dim_ref, {})
        respondents = sum(totals.values())
        print(f"\n   ▸ {qname}  [{dim_ref}]  ({respondents} respondents)")
        for opt, cnt in sorted(totals.items(), key=lambda kv: -kv[1])[:6]:
            print(f"        {cnt:>5}  {opt}")
        if len(totals) > 6:
            print(f"        ... (+{len(totals) - 6} more)")

    print(f"\n🔢 NUMERIC DIMENSIONS ({len(NUMERIC_QUESTIONS)}):")
    for qname, dim_ref in NUMERIC_QUESTIONS.items():
        print(f"   - {qname}  [{dim_ref}]  ({numeric_counts.get(dim_ref, 0)} rows)")

    print(f"\n🏷️  SCALAR METADATA KEYS ({len(scalar_values)}):")
    for name in sorted(scalar_values):
        vals = sorted(scalar_values[name])
        preview = ", ".join(vals[:5]) + (" …" if len(vals) > 5 else "")
        print(f"   - {name}  ({len(vals)} distinct)  e.g. {preview}")

    print(f"\n🚫 EXCLUDED COLUMNS ({len(excluded)}):")
    for name, reason in excluded:
        print(f"   - {name}  → {reason}")

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
