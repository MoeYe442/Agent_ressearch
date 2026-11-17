"""Structural checks for checksum-valid JSON, before semantic artifact validation."""


def mapping(value, code):
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def strings(value, code):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(code)


def string_fields(value, fields, code):
    if any(not isinstance(value.get(key), str) or not value[key] for key in fields):
        raise ValueError(code)


def optional_usage(value, code):
    if value is not None:
        mapping(value, code)
        if type(value.get('estimated')) is not bool or any(type(value.get(key)) is not int or value[key] < 0 for key in ('model_calls', 'tool_calls', 'input_tokens', 'output_tokens')):
            raise ValueError(code)


def snapshot_shape(value):
    value = mapping(value, 'invalid_snapshot_record')
    string_fields(value, ('id', 'commit', 'manifest_hash'), 'invalid_snapshot_record')


def result_shape(record):
    record = mapping(record, 'invalid_result_record')
    if record.get('snapshot') is not None:
        snapshot_shape(record['snapshot'])
    task = record.get('task')
    if task is not None:
        task = mapping(task, 'invalid_task_record')
        string_fields(task, ('id', 'snapshot_id', 'question', 'status', 'mode', 'retrieval_mode'), 'invalid_task_record')
        mapping(task.get('budget_limits'), 'invalid_task_budget')
        optional_usage(task.get('usage'), 'invalid_result_usage')
        strings(task.get('document_ids', []), 'invalid_task_documents')
        snapshot_shape(record.get('snapshot'))
    evidence = record.get('evidence', [])
    if not isinstance(evidence, list):
        raise ValueError('invalid_evidence_records')
    for item in evidence:
        item = mapping(item, 'invalid_evidence_record')
        string_fields(item, ('id', 'path', 'snapshot_id', 'commit_sha', 'content_hash'), 'invalid_evidence_record')
    report = record.get('report')
    if report is not None:
        report = mapping(report, 'invalid_report')
        string_fields(report, ('status', 'mode'), 'invalid_report')
        optional_usage(report.get('usage'), 'invalid_report_usage')
        claims = report.get('claims')
        if not isinstance(claims, list):
            raise ValueError('invalid_claims')
        for item in claims:
            item = mapping(item, 'invalid_claim')
            string_fields(item, ('text',), 'invalid_claim')
            strings(item.get('evidence_ids'), 'invalid_claim_references')


def context_shape(context):
    context = mapping(context, 'invalid_run_context')
    string_fields(context, ('run_id', 'plan_hash'), 'invalid_run_context')
    server = mapping(context.get('server'), 'invalid_run_server')
    if type(server.get('synthetic')) is not bool:
        raise ValueError('unknown_run_environment')
    mapping(server.get('budget_limits'), 'invalid_run_budget')
    if server.get('model_identifier') is not None and not isinstance(server['model_identifier'], str):
        raise ValueError('invalid_run_model')


def review_shape(review):
    review = mapping(review, 'invalid_review_row')
    string_fields(review, ('run_id', 'row_key', 'result_hash'), 'invalid_review_row')
    for group, identifier in (('facts', 'fact_id'), ('claims', 'claim_key'), ('citations', 'citation_key')):
        if not isinstance(review.get(group), list):
            raise ValueError('invalid_review_group')
        for item in review[group]:
            item = mapping(item, 'invalid_review_item')
            string_fields(item, (identifier,), 'invalid_review_identifier')
            if group == 'facts':
                strings(item.get('evidence_ids'), 'invalid_review_references')
