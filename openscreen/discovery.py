"""Passive discovery: never send guessed commands to an unknown serial device."""
import os
import re
import stat
import time
from pathlib import Path
from serial.tools.list_ports import comports


def ports():
    try:
        return list(comports())[:128]
    except (OSError, ValueError):
        return []


def recognized(port):
    return (port.vid,port.pid)==(0x0416,0x90a1)


def allowed_device(device):
    if device in ('auto','/dev/aoostar'):
        return True
    if not re.fullmatch(r'/dev/(?:tty(?:ACM|USB|S)\d+|serial/by-id/[^/]+)|COM[1-9]\d*',device):
        return False
    explicit = {s.strip() for s in os.getenv('OPENSCREEN_ALLOWED_DEVICES','').split(',') if s.strip()}
    if device in explicit:
        return True
    return any(recognized(p) and os.path.realpath(p.device)==os.path.realpath(device) for p in ports())


def accessible(device):
    if os.name=='nt':
        return any(p.device==device for p in ports())
    try:
        return stat.S_ISCHR(Path(device).stat().st_mode) and os.access(device,os.R_OK|os.W_OK)
    except OSError:
        return False


def character_device(device):
    try:
        return stat.S_ISCHR(Path(device).stat().st_mode)
    except OSError:
        return False


def serial_displays():
    found=[]
    seen=set()
    candidates=[(p.device,p) for p in ports() if recognized(p)]
    if character_device('/dev/aoostar'):
        candidates.insert(0,('/dev/aoostar',None))
    for device,port in candidates:
        real=os.path.realpath(device)
        if os.name!='nt':
            try:
                info=Path(device).stat()
                if stat.S_ISCHR(info.st_mode):
                    real=('character-device',info.st_rdev)
            except OSError:
                pass
        if real in seen:
            continue
        seen.add(real)
        found.append({'device':device,'name':'AOOSTAR / Synwit' if port else 'Zugeordnetes AOOSTAR-Gerät',
                      'kind':'aoostar','width':960,'height':376,'size_source':'adapter-profile',
                      'accessible':accessible(device),'verified':False})
    return found


class PlayerRegistry:
    """Short-lived client reports, not a scan of the local network."""
    def __init__(self):
        from threading import RLock
        self.lock=RLock()
        self.players={}

    def list(self):
        with self.lock:
            now=time.monotonic()
            self.players={k:v for k,v in self.players.items() if now-v['seen']<90}
            return [{k:v for k,v in p.items() if k!='seen'} for p in self.players.values()]

    def report(self, report):
        with self.lock:
            self.list()
            if report.id not in self.players and len(self.players)>=16:
                raise ValueError('Maximal 16 aktive Browser-Player')
            self.players[report.id]={**report.model_dump(),'seen':time.monotonic(),
                                    'size_source':'browser-estimate'}


def inspect_output(config, registry, existing_device=None):
    output=config.output.model_copy(deep=True)
    if output.kind=='browser':
        player=next((p for p in registry.list() if p['id']==output.player_id),None)
        if player and output.auto_size:
            output.width,output.height=player['width'],player['height']
        return {'ok':True,'output':output.model_dump(),'size_source':'browser-estimate' if player and output.auto_size else 'manual',
                'message':'Browsergröße gemeldet (Näherung; Zoom/Skalierung prüfen).' if player else 'Manuelle Größe; kein ausgewählter Player online.'}
    if config.device!=existing_device and not allowed_device(config.device):
        raise ValueError('Gerätepfad nicht freigegeben')
    device=config.device
    if device=='auto':
        candidates=serial_displays()
        if len(candidates)!=1:
            return {'ok':False,'output':output.model_dump(),'size_source':'adapter-profile',
                    'message':'Kein eindeutiges Display gefunden. Gerät auswählen oder manuell eintragen.'}
        device=candidates[0]['device']
    ok=accessible(device)
    return {'ok':ok,'device':device,'output':output.model_dump(),'size_source':'adapter-profile',
            'message':('Gerät vorhanden; 960 × 376 laut AOOSTAR-Profil. Protokollbestätigung erfolgt beim Verbinden.' if ok
                       else 'Gerät fehlt oder ist nicht les-/schreibbar. Docker-Gerätefreigabe und Gruppe prüfen.')}
