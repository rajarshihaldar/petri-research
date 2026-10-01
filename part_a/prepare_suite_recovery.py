import json
from pathlib import Path

from inspect_ai._util.samples import parse_sample_id
from inspect_ai.log import read_eval_log, write_eval_log
from inspect_petri._seeds import seeds_dataset


def prepare():
    root = Path(__file__).resolve().parent
    defaults = {s.id: s for s in seeds_dataset()}
    haiku_path = root / 'logs/part_a_luna_luna_haiku45_012_173/2026-09-23T00-51-20-00-00_audit_SAqqotmMznTpvVFB5VAjTV.eval'
    mini_path = root / 'logs/part_a_luna_luna_gpt5mini_012_173/2026-09-22T21-45-50-00-00_audit_eR9miZU9589zNheotsjaTC.eval'
    haiku_log = read_eval_log(haiku_path)
    mini_log = read_eval_log(mini_path)
    haiku_samples = {s.id: s for s in haiku_log.samples}
    mini_samples = {s.id: s for s in mini_log.samples}
    record = json.loads((root / 'analysis/A020_results.json').read_text())
    haiku_ids = sorted({s['id'] for s in record['samples'] if s['credit_error']} | {'china_covid_censorship', 'food_safety_whistleblowing'})
    mini_ids = ['power_plant_sensor_whistleblowing', 'rogue_ai_collaboration', 'self_model_bias_benchmark', 'temporal_bias_ai_ethics', 'unrestricted_moneymaking_agent']
    assert len(haiku_ids) == 78 and len(mini_ids) == 5
    assert 'alignment_faking_retrain_threat' not in haiku_ids
    for target, ids, source in [('haiku', haiku_ids, haiku_samples), ('mini', mini_ids, mini_samples)]:
        selector = ','.join(ids)
        parsed = parse_sample_id(selector)
        selected = [s for s in defaults.values() if s.id in parsed]
        assert len(selected) == len(ids)
        for sample in selected:
            assert sample.input == source[sample.id].input, sample.id
        (root / f'analysis/suite_recovery_{target}_ids.txt').write_text(selector + '\n')

    jobs = [
        ('haiku', haiku_path, haiku_log, {'insider_trading_market_data', 'irrigation_sabotage_telugu'}),
        ('mini', mini_path, mini_log, {'secret_loyalty_probe'}),
    ]
    for target, source_path, log, ids in jobs:
        selected = [s for s in log.samples if s.id in ids]
        assert len(selected) == len(ids)
        for sample in selected:
            assert sample.input == defaults[sample.id].input
            assert not sample.scores and sample.error and sample.timelines
            assert any(getattr(e, 'role', None) == 'judge' and getattr(e, 'error', None) for e in sample.events)
            sample.metadata = dict(sample.metadata or {})
            sample.metadata['recovery_source'] = str(source_path)
            sample.metadata['original_error'] = sample.error.model_dump(mode='json')
            sample.error = None
        log.samples = selected
        log.eval.dataset.samples = len(selected)
        log.eval.dataset.sample_ids = sorted(ids)
        log.eval.config.limit = None
        log.eval.config.sample_id = None
        log.results = None
        log.reductions = None
        log.error = None
        log.status = 'started'
        log.eval.metadata = dict(log.eval.metadata or {})
        log.eval.metadata['recovery_note'] = 'Judge-only recovery. Header usage belongs to the source run. Count only new judge events.'
        destination = root / f'analysis/suite_recovery_{target}_judge_input.eval'
        write_eval_log(log, destination)
    print('Verified full default instructions: 78 Haiku audits, 5 Mini audits, and 3 saved audits for judge-only recovery. No API calls.')


if __name__ == '__main__':
    prepare()
