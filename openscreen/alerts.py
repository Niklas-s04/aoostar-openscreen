from collections import deque
import math


class AlertEngine:
    def __init__(self):
        self.pending = {}
        self.history = {}
        self.fingerprints = {}

    def evaluate(self, config, snapshots, now):
        results = []
        live_ids = {r.id for r in config.rules}
        for mapping in (self.pending, self.history, self.fingerprints):
            for key in list(mapping):
                if key not in live_ids:
                    del mapping[key]
        sources = {s.id: s for s in config.sources}
        for rule in config.rules:
            signature = rule.model_dump_json()
            if self.fingerprints.get(rule.id) != signature:
                self.pending.pop(rule.id, None)
                self.history.pop(rule.id, None)
                self.fingerprints[rule.id] = signature
            source = sources[rule.source_id]
            snap = snapshots.get(rule.source_id)
            known = source.enabled and snap and snap.ok and now - snap.observed_at <= source.interval * 2
            match = self._matches(rule, snap, now) if known and rule.enabled else None
            if not rule.enabled:
                state = 'disabled'
                self.pending.pop(rule.id, None)
            elif match is None:
                state = 'unknown'
                self.pending.pop(rule.id, None)
            elif match:
                since = self.pending.setdefault(rule.id, now)
                state = 'active' if now - since >= rule.delay else 'pending'
            else:
                state = 'ok'
                self.pending.pop(rule.id, None)
            results.append({**rule.model_dump(), 'state': state, 'since': self.pending.get(rule.id)})
        return results

    def _matches(self, rule, snap, now):
        if rule.condition in ('gt', 'lt'):
            value = snap.metrics.get(rule.metric)
            if value is None:
                return None
            return value > rule.threshold if rule.condition == 'gt' else value < rule.threshold
        items = snap.pools if rule.condition == 'pool_not_online' else snap.workloads
        selected = [x for x in items if not rule.target or rule.target in (x.get('id'), x.get('name'))]
        if not selected:
            return None
        if rule.condition == 'restart_loop':
            histories = self.history.setdefault(rule.id, {})
            values = []
            for item in selected:
                count = item.get('restarts')
                if not isinstance(count,(int,float)) or isinstance(count,bool) or not math.isfinite(count):
                    continue
                history = histories.setdefault(item['id'], deque())
                if history and count < history[-1][1]:
                    history.clear()
                if not history or history[-1][0] != snap.observed_at:
                    history.append((snap.observed_at, count))
                while len(history) > 1 and history[1][0] < now - 60:
                    history.popleft()
                # No sample inside the window means no recent restart evidence.
                base = history[0][1] if history[0][0] >= now - 60 else history[1][1] if len(history) > 1 else count
                values.append(count - base > rule.threshold)
            return any(values) if values else None
        key = 'health' if rule.condition == 'unhealthy' else 'state'
        values = [item.get(key) for item in selected]
        if not all(v is not None and str(v).lower() not in ('unknown','unavailable','') for v in values):
            return None
        if rule.condition == 'unhealthy':
            return any(v == 'unhealthy' for v in values)
        return any(str(item[key]).lower() != ('online' if rule.condition == 'pool_not_online' or item.get('kind')=='node' else 'running') for item in selected)
