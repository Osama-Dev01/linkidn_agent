"""Standard-library preference catalogue and pure update planner (Python 3.10+).

No LLM calls, MongoDB writes, or implicit authorization occur in this module.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

_DATA = json.loads(Path(__file__).with_name('catalogue.json').read_text(encoding='utf-8'))
CATALOGUE_VERSION = _DATA['version']
_CATALOGUE = {entry['field']: entry for entry in _DATA['fields']}
MISSING = object()
SOURCES = {'profile', 'topic_feedback', 'review_feedback', 'sample'}
STAGE_SOURCE = {'profile_update': 'profile', 'topic_selection': 'topic_feedback',
                'post_finalization': 'review_feedback', 'sample_analysis': 'sample'}
UNSUPPORTED_PROFILE_INPUTS = ('preferences.post_length', 'preferences.word_range',
                            'preferences.paragraph_style', 'interests.distrusted_sources')


class CatalogueError(ValueError):
    pass


def get_definition(field: str) -> dict[str, Any]:
    if not isinstance(field, str) or field not in _CATALOGUE:
        raise CatalogueError(f'Unsupported preference field: {field!r}')
    return deepcopy(_CATALOGUE[field])


def catalogue(categories: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = set(categories) if categories is not None else None
    known = {e['category'] for e in _CATALOGUE.values()}
    if selected is not None and selected - known:
        raise CatalogueError(f'Unknown categories: {sorted(selected - known)}')
    return [deepcopy(e) for e in _CATALOGUE.values()
            if selected is None or e['category'] in selected]


def _read(document: Mapping[str, Any], path: str, separator: str = '/') -> Any:
    value: Any = document
    for key in path.split(separator):
        if not isinstance(value, Mapping) or key not in value:
            return MISSING
        value = value[key]
    return value


def _missing_input(value: Any) -> bool:
    return value is MISSING or value is None or (isinstance(value, str) and not value.strip())


def _normalize(value: Any, schema: Mapping[str, Any]) -> Any:
    kind = schema['type']
    if kind == 'integer':
        if type(value) is not int:
            raise CatalogueError('Expected an integer, not a boolean or numeric string')
        if not schema.get('minimum', value) <= value <= schema.get('maximum', value):
            raise CatalogueError(f'Integer outside supported range {schema.get("minimum")}–{schema.get("maximum")}')
        return value
    if kind == 'string':
        if not isinstance(value, str) or not value.strip():
            raise CatalogueError('Expected nonblank text')
        value = value.strip()
        if 'enum' in schema:
            matches = [item for item in schema['enum'] if item.casefold() == value.casefold()]
            if not matches:
                raise CatalogueError(f'Expected one of {schema["enum"]!r}')
            return matches[0]
        return value
    if kind == 'array':
        if not isinstance(value, list):
            raise CatalogueError('Expected a list, including for add/remove operations')
        result = []
        for item in value:
            item = _normalize(item, schema['items'])
            if item not in result:
                result.append(item)
        return result
    raise CatalogueError(f'Unsupported schema type: {kind}')


def validate_value(field: str, value: Any) -> Any:
    """Return a normalized copy, or raise. No fuzzy enum/semantic coercion."""
    return _normalize(value, get_definition(field)['value_schema'])


def active_state(preferences: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Derived presence only: [] / 0 / literal 'None' are filled, not unset."""
    result = {}
    for field in _CATALOGUE:
        value = _read(preferences, field)
        if _missing_input(value):
            result[field] = {'state': 'unset', 'value': None}
        else:
            try:
                result[field] = {'state': 'filled', 'value': validate_value(field, value)}
            except CatalogueError as exc:
                result[field] = {'state': 'invalid', 'value': deepcopy(value), 'error': str(exc)}
    return result


def map_profile(profile: Mapping[str, Any], preferences: Mapping[str, Any] | None = None,
                *, changed_paths: Iterable[str] | None = None,
                clear_paths: Iterable[str] = ()) -> dict[str, Any]:
   
    preferences = preferences or {}
    changed = set(changed_paths) if changed_paths is not None else None
    clears = set(clear_paths)
    allowed = {e['direct_source'] for e in _CATALOGUE.values() if e['direct_source']}
    if changed is not None and changed - allowed - set(UNSUPPORTED_PROFILE_INPUTS):
        raise CatalogueError('Unknown changed profile preference paths')
    if clears - allowed or (changed is not None and clears - changed):
        raise CatalogueError('Clear paths must be mapped and included in changed_paths')
    result: dict[str, Any] = {'changes': [], 'skipped': [], 'issues': []}
    for field, entry in _CATALOGUE.items():
        src = entry['direct_source']
        if src is None or (changed is not None and src not in changed):
            continue
        value = _read(profile, src, '.')
        if _missing_input(value) or (value == [] and src not in clears):
            result['skipped'].append({'field': field, 'reason': 'no_input'})
            continue
        old = _read(preferences, field)
        if changed is None and not _missing_input(old):
            result['skipped'].append({'field': field, 'reason': 'existing_value_preserved'})
            continue
        try:
            value = validate_value(field, value)
        except CatalogueError as exc:
            result['issues'].append({'field': field, 'source_path': src, 'error': str(exc)})
            continue
        if old is not MISSING and old == value:
            continue
        result['changes'].append({'field': field, 'operation': 'set',
                                  'old_value': None if old is MISSING else deepcopy(old),
                                  'new_value': value, 'status': 'suggested', 'decided_at': None})
    for path in UNSUPPORTED_PROFILE_INPUTS:
        if changed is not None and path not in changed:
            continue
        value = _read(profile, path, '.')
        if not _missing_input(value) and value != []:
            result['issues'].append({'source_path': path, 'error': 'No destination in simplified Preferences schema'})
    return result


def validate_change(change: Mapping[str, Any]) -> dict[str, Any]:
    """Use the exact supplied PreferenceChange vocabulary; ignore model status."""
    if not isinstance(change, Mapping):
        raise CatalogueError('A change must be an object')
    definition = get_definition(change.get('field'))
    operation = change.get('operation')
    if operation not in definition['operations']:
        raise CatalogueError(f'Operation {operation!r} is not allowed for {definition["field"]}')
    if 'new_value' not in change:
        raise CatalogueError('new_value is required')
    result = {'field': definition['field'], 'operation': operation,
              'new_value': validate_value(definition['field'], change['new_value']),
              'status': 'suggested', 'decided_at': None}
    if 'old_value' in change:
        result['old_value'] = deepcopy(change['old_value'])
    if 'content_type' in change:
        result['content_type'] = change['content_type']
    return result


def _edit(document: dict[str, Any], change: Mapping[str, Any]) -> None:
    field = change['field']
    group, key = field.split('/')
    current = _read(document, field)
    if change['operation'] == 'set':
        new = deepcopy(change['new_value'])
    else:
        current = [] if current is MISSING or current is None else validate_value(field, current)
        if change['operation'] == 'add':
            new = current + [x for x in change['new_value'] if x not in current]
        else:
            new = [x for x in current if x not in change['new_value']]
    if group in document and not isinstance(document[group], dict):
        raise CatalogueError(f'Invalid preference group: {group}')
    document.setdefault(group, {})[key] = new


def plan_feedback(preferences: Mapping[str, Any], event: Mapping[str, Any],
                  proposals: list[Mapping[str, Any]], *,
                  authorized_indices: Iterable[int] = ()) -> dict[str, Any]:
    """Return a new preference document plus auditable decisions; never write DB.

    authorized_indices is TRUSTED SERVER INPUT for this exact proposal list,
    after explicit intent verification or user confirmation. Never read it from
    LLM output. Scope is taken from the authenticated event, not model output.
    Bind authorization to event/proposal revisions in the service layer.
    """
    authorized = set(authorized_indices)
    if any(type(i) is not int or not 0 <= i < len(proposals) for i in authorized):
        raise CatalogueError('Invalid authorization indices')
    scope = event.get('scope', 'this_post')
    if scope not in {'this_post', 'future_posts', 'content_type'}:
        raise CatalogueError('Invalid event scope')
    stage = event.get('stage')
    if stage not in STAGE_SOURCE:
        raise CatalogueError('Invalid feedback stage')
    if not isinstance(event.get('event_id'), str) or not event['event_id'].strip():
        raise CatalogueError('event_id is required for provenance')
    result = {'preferences': deepcopy(dict(preferences)), 'changes': [],
              'run_changes': [], 'issues': []}
    # Reject duplicate fields as a whole; do not partially apply an ambiguous pair.
    counts: dict[str, int] = {}
    for proposal in proposals:
        f = proposal.get('field') if isinstance(proposal, Mapping) else None
        if isinstance(f, str):
            counts[f] = counts.get(f, 0) + 1
    now = datetime.now(timezone.utc)
    for index, raw in enumerate(proposals):
        try:
            if isinstance(raw, Mapping) and 'scope' in raw and raw['scope'] != scope:
                raise CatalogueError('Proposal scope differs from event scope; split mixed-scope events before processing')
            change = validate_change(raw)
            field = change['field']
            if counts[field] > 1:
                raise CatalogueError('Multiple changes for the same field require reconciliation')
            current = _read(preferences, field)
            old = None if current is MISSING else current
            if 'old_value' in change and change['old_value'] != old:
                raise CatalogueError('Stale old_value: re-read and reconcile')
            change['old_value'] = deepcopy(old)
            if scope == 'content_type' or 'content_type' in change:
                raise CatalogueError('Persistent content-type overrides have no destination in this schema')
            # Sample analysis only supplies inferences; it cannot set explicit-only fields.
            if stage == 'sample_analysis' and get_definition(field)['learning_policy'] == 'explicit_only':
                raise CatalogueError('This preference cannot be inferred from writing samples')
            if index not in authorized:
                result['changes'].append(change)
                continue
            if scope == 'this_post':
                # Run planner still needs to apply these to its own overlay, not Preferences.
                result['run_changes'].append(change)
                result['changes'].append(change)
                continue
            _edit(result['preferences'], change)
            meta: dict[str, Any] = {'source': STAGE_SOURCE[stage],
                                    'feedback_event_id': event['event_id'], 'updated_at': now}
            if stage == 'sample_analysis':
                ids = event.get('sample_ids')
                if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x for x in ids):
                    raise CatalogueError('Sample analysis requires sample_ids')
                meta['sample_ids'] = list(ids)
            result['preferences'].setdefault('field_metadata', {})[field] = meta
            change.update(status='applied', decided_at=now)
            result['changes'].append(change)
        except (CatalogueError, TypeError) as exc:
            # Stage result is reconstructed below from successfully applied changes,
            # ensuring errors after validation cannot leak a partially edited field.
            result['issues'].append({'index': index, 'error': str(exc)})
    rebuilt = deepcopy(dict(preferences))
    for change in result['changes']:
        if change['status'] == 'applied':
            _edit(rebuilt, change)
            rebuilt.setdefault('field_metadata', {})[change['field']] = result['preferences']['field_metadata'][change['field']]
    result['preferences'] = rebuilt
    return result


def llm_context(categories: Iterable[str] | None = None) -> dict[str, Any]:
    """Return definitions and an output contract for YOUR chosen LLM client."""
    definitions = catalogue(categories)
    return {
        'catalogue_version': CATALOGUE_VERSION,
        'instructions': (
            'Propose only supported field changes with evidence quotes and per-change scope. '
            'Distinguish explicit instructions from inferred patterns. Never fill unsupported '
            'fields, invent personal facts or permissions, or overwrite explicit values from '
            'sample habits. Return an empty proposals list when no preference change is justified. '
            'Content-type persistence is unsupported; report that limitation instead of '
            'broadening scope. Your output cannot authorize application or confirmation.'),
        'fields': definitions,
        'output_schema': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'proposals': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'field': {'type': 'string', 'enum': [e['field'] for e in definitions]},
                    'operation': {'type': 'string', 'enum': ['set', 'add', 'remove']},
                    'new_value': {'anyOf': [{'type': 'string'}, {'type': 'integer'},
                                           {'type': 'array', 'items': {'type': 'string'}}]},
                    'scope': {'type': 'string', 'enum': ['this_post', 'future_posts', 'content_type']},
                    'basis': {'type': 'string', 'enum': ['explicit', 'inferred']},
                    'evidence': {'type': 'string'},
                    'reason': {'type': 'string'}},
                'required': ['field', 'operation', 'new_value', 'scope', 'basis', 'evidence', 'reason']}}},
            'required': ['proposals']}}
