"""AI-6 plain-language rules: named landmarks, Claude-drafted rules, schedules, enforced zones.

Claude only drafts. A draft is never enforced until the operator confirms it, and anything
the model returns that does not match a real landmark or a valid time becomes a question.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime

from .review import FALLBACK_MODELS

DEFAULT_MODEL = 'claude-opus-5-5'
SCHEDULE_TYPES = ('always', 'window', 'nap')
CLOCK = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
ASK_PLACE = "Which landmark should this rule use? If it isn't listed yet, draw it in landmark mode first."
ASK_TIME = 'When should this rule apply? Use 24-hour times, for example 12:30 to 14:30, or say "always" or "during nap time".'

SYSTEM = (
    "You turn a daycare operator's plain-language safety rule into a structured restricted-area rule. "
    'Use only the listed landmarks and refer to one by its id. If the text does not clearly match exactly one listed '
    'landmark, or its timing is ambiguous, set action to clarify and ask one short question. Schedules: always; window '
    'with 24-hour HH:MM start and end in local time; nap when the rule applies during nap time without clock times. '
    'Severity is critical only when the text signals immediate danger (stairs, water, exits, heat); otherwise high. '
    'The summary restates the rule in one plain sentence.'
)
nullable = lambda schema: {'anyOf': [schema, {'type': 'null'}]}
SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['propose', 'clarify']},
        'landmark_id': nullable({'type': 'string'}),
        'schedule': nullable({'type': 'string', 'enum': list(SCHEDULE_TYPES)}),
        'start': nullable({'type': 'string'}),
        'end': nullable({'type': 'string'}),
        'severity': nullable({'type': 'string', 'enum': ['high', 'critical']}),
        'summary': nullable({'type': 'string'}),
        'question': nullable({'type': 'string'}),
    },
    'required': ['action', 'landmark_id', 'schedule', 'start', 'end', 'severity', 'summary', 'question'],
    'additionalProperties': False,
}


def validate_landmark(name, vertices, existing: list[dict]) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
        raise ValueError('Name the landmark in 1–40 characters')
    name = name.strip()
    if any(l['name'].lower() == name.lower() for l in existing):
        raise ValueError(f'A landmark named "{name}" already exists')
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= 12:
        raise ValueError('Outline the landmark with 3–12 points')
    points = []
    for v in vertices:
        if not isinstance(v, list) or len(v) != 2 or any(isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1 for c in v):
            raise ValueError('Landmark points must be on the video')
        points.append([float(v[0]), float(v[1])])
    area = abs(sum(points[i][0] * points[i - 1][1] - points[i - 1][0] * points[i][1] for i in range(len(points)))) / 2
    if area < 0.0005:
        raise ValueError('The landmark outline must enclose an area')
    return {'id': 'lm-' + uuid.uuid4().hex[:8], 'name': name, 'vertices': points}


def schedule_active(schedule: dict, now: datetime, nap_mode: bool) -> bool:
    kind = schedule.get('type')
    if kind == 'always':
        return True
    if kind == 'nap':
        return nap_mode
    if kind == 'window':
        minutes = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:])
        start, end, at = minutes(schedule['start']), minutes(schedule['end']), now.hour * 60 + now.minute
        return start <= at < end if start < end else (at >= start or at < end)  # Windows may wrap past midnight.
    return False


def interpret(data: dict, text: str, landmarks: list[dict]) -> dict:
    """Model output → {'rule': draft} or {'question': str}. Nothing invalid becomes a rule."""
    if data.get('action') != 'propose':
        return {'question': (data.get('question') or ASK_PLACE).strip()[:300]}
    if data.get('landmark_id') not in {l['id'] for l in landmarks}:
        return {'question': ASK_PLACE}
    kind = data.get('schedule')
    if kind not in SCHEDULE_TYPES:
        return {'question': ASK_TIME}
    schedule = {'type': kind}
    if kind == 'window':
        start, end = data.get('start') or '', data.get('end') or ''
        if not (CLOCK.match(start) and CLOCK.match(end)) or start == end:
            return {'question': ASK_TIME}
        schedule.update(start=start, end=end)
    return {'rule': {'id': 'rule-' + uuid.uuid4().hex[:8], 'landmark_id': data['landmark_id'], 'schedule': schedule,
                     'severity': data.get('severity') if data.get('severity') in ('high', 'critical') else 'high',
                     'summary': (data.get('summary') or text).strip()[:200], 'source_text': text, 'status': 'draft', 'created_at': time.time()}}


async def draft_rule(client, model: str, text: str, landmarks: list[dict]) -> dict:
    listed = json.dumps([{'id': l['id'], 'name': l['name']} for l in landmarks])
    params = dict(model=model, max_tokens=2000, system=SYSTEM,
                  messages=[{'role': 'user', 'content': f'Landmarks: {listed}\nRule: {text}'}],
                  output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}})
    if model in FALLBACK_MODELS:
        response = await client.beta.messages.create(**params, betas=['server-side-fallback-2026-07-01'], fallbacks='default')
    else:
        response = await client.messages.create(**params)
    if response.stop_reason in ('refusal', 'max_tokens'):
        return {'question': "I couldn't turn that into a rule. Name the place and the time, for example: keep kids away from the stairs from 12:30 to 14:30."}
    return interpret(json.loads(next(b.text for b in response.content if b.type == 'text')), text, landmarks)


def active_zones(settings: dict, now: datetime) -> list[dict]:
    """Restricted zones in force now: the default zone, plus confirmed rules whose schedule applies."""
    zones = []
    zone = settings.get('zone')
    if isinstance(zone, dict) and zone.get('enabled', True) and isinstance(zone.get('vertices'), list) and len(zone['vertices']) >= 3:
        zones.append({'id': 'default', 'name': 'configured restricted area', 'polygon': [tuple(v) for v in zone['vertices']], 'priority': 'high'})
    landmarks = {l['id']: l for l in settings.get('landmarks', []) if isinstance(l, dict)}
    for rule in settings.get('rules', []):
        landmark = landmarks.get(rule.get('landmark_id'))
        if rule.get('status') == 'active' and landmark and schedule_active(rule.get('schedule', {}), now, settings.get('nap_mode') is True):
            zones.append({'id': rule['id'], 'name': landmark['name'], 'polygon': [tuple(v) for v in landmark['vertices']], 'priority': rule.get('severity', 'high')})
    return zones
