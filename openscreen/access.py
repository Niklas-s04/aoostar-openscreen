"""Boundaries for the full Docker distribution."""
from .network_access import AccessPolicy, same_origin, values


def validate_source(source):
    if source.kind != 'local' and source.url not in values('OPENSCREEN_ALLOWED_SOURCE_URLS'):
        raise ValueError('Datenquellen-URL ist nicht in OPENSCREEN_ALLOWED_SOURCE_URLS freigegeben')


def validate_config(config, existing_device=None):
    from .discovery import allowed_device
    if config.output.kind=='broker':
        import re
        if config.device!='auto' and not re.fullmatch(r'broker:[a-f0-9]{32}',config.device):
            raise ValueError('Broker-Gerät aus der Liste auswählen')
    elif config.device!=existing_device and not allowed_device(config.device):
        raise ValueError('Gerät nicht freigegeben: erkanntes AOOSTAR-Gerät, /dev/aoostar oder OPENSCREEN_ALLOWED_DEVICES verwenden')
    for source in config.sources:
        validate_source(source)
