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
                                    'size_source':'player-viewport'}


def inspect_output(config, registry, existing_device=None):
    output=config.output.model_copy(deep=True)
    if output.kind=='broker':
        from .broker_client import selected
        try:
            device=selected(config.device)
            from .adapters import Capabilities
            from .outputs import validate_output
            capabilities=Capabilities.from_dict(device['capabilities'])
            if output.auto_size:
                modes=[m for m in capabilities.modes if not output.mode_id or m.id==output.mode_id]
                if len(modes)==1:
                    mode=modes[0]
                    output.width,output.height=mode.width,mode.height
                    output.mode_id,output.pixel_format=mode.id,mode.pixel_format
                output.adapter_id=capabilities.adapter_id
            validate_output(output,capabilities)
            return {'ok':True,'device':device['device'],'output':output.model_dump(),
                    'capabilities':capabilities.to_dict(),'size_source':capabilities.size_source,
                    'message':'Protokoll bestätigt; Größe laut Adapterprofil, Sichtprüfung ausstehend.'}
        except (ValueError,OSError) as exc:
            return {'ok':False,'output':output.model_dump(),'size_source':'adapter-profile',
                    'message':'Broker nicht bereit oder Display nicht eindeutig bestätigt.'}
        except Exception:
            return {'ok':False,'output':output.model_dump(),'size_source':'adapter-profile',
                    'message':'Broker-Verbindung fehlgeschlagen.'}
    if output.kind=='browser':
        player=next((p for p in registry.list() if p['id']==output.player_id),None)
        if player and output.auto_size:
            output.width,output.height=player['width'],player['height']
            output.mode_id=''
        from .adapters import ADAPTERS
        source='player-viewport' if player and output.auto_size else 'manual'
        capabilities=ADAPTERS.get('browser').get_capabilities(output.player_id,width=output.width,height=output.height,size_source=source)
        return {'ok':True,'output':output.model_dump(),'capabilities':capabilities.to_dict(),'size_source':source,
                'message':'Player-Renderfläche gemeldet; native Panelauflösung nicht verifiziert.' if player else 'Manuelle Größe; kein ausgewählter Player online.'}
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
    from .adapters import ADAPTERS
    return {'ok':ok,'device':device,'output':output.model_dump(),'size_source':'adapter-profile',
            'capabilities':ADAPTERS.get('aoostar').get_capabilities(device).to_dict(),
            'message':('Gerät vorhanden; 960 × 376 laut AOOSTAR-Profil. Protokollbestätigung erfolgt beim Verbinden.' if ok
                       else 'Gerät fehlt oder ist nicht les-/schreibbar. Docker-Gerätefreigabe und Gruppe prüfen.')}
