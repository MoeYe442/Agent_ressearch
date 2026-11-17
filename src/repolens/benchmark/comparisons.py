"""Descriptive same-plan comparisons; unknowns never become zero-cost observations."""
from repolens.benchmark.protocol import CONFIGS


def comparisons(plan, rows, summaries):
    pairs = [('direct', 'single_keyword'), ('single_keyword', 'collaborative_keyword'),
             ('collaborative_keyword', 'collaborative_hybrid'),
             ('collaborative_hybrid', 'collaborative_hybrid_rerank')]
    pairs += [(name.removesuffix('_compressed'), name) for name in CONFIGS if name.endswith('_compressed')]
    indexed = {(row['configuration'], row['case_id'], row['repeat']): row for row in rows}
    result = []
    for baseline, variant in pairs:
        if baseline not in summaries or variant not in summaries:
            continue
        left, right = summaries[baseline], summaries[variant]
        matched = [(indexed[baseline, case, repeat], indexed[variant, case, repeat]) for case in plan.case_ids for repeat in range(1, plan.repeats + 1)]
        observed = [(a, b) for a, b in matched if a['record'] is not None and b['record'] is not None]
        usage_left, usage_right = left['complete_usage_totals'], right['complete_usage_totals']
        usage_complete = len(observed) == len(matched) and usage_left is not None and usage_right is not None

        def difference(key, factor=1):
            a, b = left.get(key), right.get(key)
            return (b - a) * factor if a is not None and b is not None else None

        def saving(key):
            a = usage_left[key] if usage_complete else None
            return (a - usage_right[key]) / a if a is not None and a > 0 else None

        result.append(dict(baseline=baseline, variant=variant, planned_pairs=len(matched), observed_pairs=len(observed),
                           unavailable_pairs=len(matched) - len(observed),
                           quality_difference_percentage_points=difference('quality_completion_rate', 100),
                           answer_difference_percentage_points=difference('answer_correctness_rate', 100),
                           fact_coverage_difference_percentage_points=difference('fact_coverage_rate', 100),
                           answer_fact_coverage_difference_percentage_points=difference('answer_fact_coverage_rate', 100),
                           median_latency_difference_ms=difference('median_latency_ms') if len(observed) == len(matched) and left['latency_sample_size']==len(matched) and right['latency_sample_size']==len(matched) else None,
                           p95_latency_difference_ms=difference('p95_latency_ms') if len(observed) == len(matched) and left['latency_sample_size']==len(matched) and right['latency_sample_size']==len(matched) else None,
                           input_token_saving_fraction=saving('input_tokens'),
                           total_token_saving_fraction=((usage_left['input_tokens'] + usage_left['output_tokens']) - (usage_right['input_tokens'] + usage_right['output_tokens'])) / (usage_left['input_tokens'] + usage_left['output_tokens']) if usage_complete and usage_left['input_tokens'] + usage_left['output_tokens'] > 0 else None,
                           usage_complete=usage_complete, usage_contains_estimates=(left['estimated'] or right['estimated']) if usage_complete else None,
                           interpretation='Same case/repeat slots, descriptive aggregate differences; negative savings means increased use. Direct factual judgments are not source verification. No significance or monetary-cost claim.'))
    return result
