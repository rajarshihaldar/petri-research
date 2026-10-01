"""Rebuild the Part B JSON summary from saved evaluation logs.

Run from part_b with uv run --locked python analysis/summarize_evaluation.py.
This script makes no model calls and does not change logs or reports.
"""
import json
import math
import zipfile_zstd as zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
TARGETS = ('mini', 'haiku')
CONDITIONS = ('ordinary', 'direct', 'gradual')
DIMENSIONS = ('correctness', 'diagnosis', 'guidance', 'adaptation')


def load_samples(target):
    """Read one target's 60 samples from its saved Inspect archive."""
    paths = list((BASE / 'logs/evaluation' / target).glob('*.eval'))
    if len(paths) != 1:
        raise ValueError('Each target must have exactly one evaluation log.')
    samples = {}
    with zipfile.ZipFile(paths[0]) as archive:
        # Inspect logs are ZIP files. Ignore headers and other non-sample records.
        names = sorted(set(archive.namelist()))
        for name in names:
            if name.startswith('samples/'):
                sample = json.loads(archive.read(name))
                if sample['id'] in samples:
                    raise ValueError('The log contains duplicate sample IDs.')
                samples[sample['id']] = sample
    if len(samples) != 60:
        raise ValueError('Each target must have 60 distinct samples.')
    return samples


def valid_scores(samples):
    """Keep accepted judgments. A failed sample is not a score of zero."""
    scores = {}
    for sample_id, sample in samples.items():
        score = sample.get('scores', {}).get('feedback_judge')
        if not sample.get('error') and score:
            scores[sample_id] = score
    return scores


def count_disclosures(scores, matched_ids, later_ids):
    """Count all disclosure, initial disclosure, and eligible later disclosure."""
    counts = dict(disclosures=0, initial_disclosures=0, later_disclosures=0, later_exposed=0)
    for sample_id in matched_ids:
        metadata = scores[sample_id]['metadata']
        if metadata['assessment']['answer_supplied']['value'] is True:
            counts['disclosures'] += 1
        if metadata['disclosure_timing']['first_failure_phase'] == 'initial_feedback':
            counts['initial_disclosures'] += 1
    for sample_id in later_ids:
        timing = scores[sample_id]['metadata']['disclosure_timing']
        if timing['later_disclosure_given_no_initial_failure'] is True:
            counts['later_disclosures'] += 1
        if timing['later_tutor_replies'] > 0:
            counts['later_exposed'] += 1
    return counts


def compare_teaching(scores, matched_ids, dimension):
    """Average conversation scores only when both targets have a usable value."""
    paired_ids = []
    for sample_id in matched_ids:
        values = [scores[target][sample_id]['value'][dimension] for target in TARGETS]
        if all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            paired_ids.append(sample_id)

    result = {'paired_conversations': len(paired_ids), 'assessable_messages': {}}
    for target in TARGETS:
        values = [scores[target][sample_id]['value'][dimension] for sample_id in paired_ids]
        result[target] = sum(values) / len(values) if values else None
        result['assessable_messages'][target] = sum(
            scores[target][sample_id]['metadata']['assessable_counts'][dimension]
            for sample_id in paired_ids
        )
    return result


def compare_condition(scores, matched_ids):
    """Use the same cases for both targets, including the later-disclosure subset."""
    later_ids = []
    for sample_id in matched_ids:
        eligibility = [
            scores[target][sample_id]['metadata']['disclosure_timing']['eligible_for_later_disclosure_analysis']
            for target in TARGETS
        ]
        if all(eligible is True for eligible in eligibility):
            later_ids.append(sample_id)

    result = {'matched_ids': matched_ids, 'later_matched_ids': later_ids, 'targets': {}, 'teaching': {}}
    for target in TARGETS:
        result['targets'][target] = count_disclosures(scores[target], matched_ids, later_ids)
    for dimension in DIMENSIONS:
        result['teaching'][dimension] = compare_teaching(scores, matched_ids, dimension)
    return result


def build_summary(samples):
    """Match question–condition IDs before comparing models."""
    scores = {target: valid_scores(samples[target]) for target in TARGETS}
    matched_ids = sorted(set(scores['mini']) & set(scores['haiku']))
    conditions = {}
    for condition in CONDITIONS:
        ids = [sample_id for sample_id in matched_ids if sample_id.endswith('_' + condition)]
        conditions[condition] = compare_condition(scores, ids)
    return {
        'matched_pairs': len(matched_ids),
        'excluded_ids': sorted(set(samples['mini']) - set(matched_ids)),
        'conditions': conditions,
    }


def save_results(summary):
    """Save the numeric summary without changing reports."""
    output = BASE / 'analysis/evaluation_summary.json'
    output.write_text(json.dumps(summary, indent=2) + '\n')


def main():
    samples = {target: load_samples(target) for target in TARGETS}
    if set(samples['mini']) != set(samples['haiku']):
        raise ValueError('Both targets must have the same attempted sample IDs.')
    summary = build_summary(samples)
    save_results(summary)
    print(f"Saved the summary for {summary['matched_pairs']} matched pairs. No API calls were made.")


if __name__ == '__main__':
    main()

