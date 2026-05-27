import re
import json
import codecs
import base64
import xbmc
import requests

def log(msg):
    xbmc.log(f"[VOE Resolver] {msg}", xbmc.LOGINFO)

_DOMAINS = {
    "voe.sx", "voe-unblock.com", "voe-unblock.net", "voeunblock.com", "un-block-voe.net",
    "voeunbl0ck.com", "voeunblck.com", "voeunblk.com", "voe-un-block.com",
    "voeun-block.net", "v-o-e-unblock.com", "smoki.cc", "ogladaj.me",
    "jonathansociallike.com", "edwardarriveoften.com", "nathanfromsubject.com",
    "audaciousdefaulthouse.com", "launchreliantcleaverriver.com", "kennethofficialitem.com",
    "reputationsheriffkennethsand.com", "fittingcentermondaysunday.com", "lukecomparetwo.com",
    "housecardsummerbutton.com", "fraudclatterflyingcar.com", "wolfdyslectic.com",
    "bigclatterhomesguideservice.com", "uptodatefinishconferenceroom.com", "jayservicestuff.com",
    "realfinanceblogcenter.com", "tinycat-voe-fashion.com", "35volitantplimsoles5.com",
    "20demidistance9elongations.com", "telyn610zoanthropy.com", "toxitabellaeatrebates306.com",
    "greaseball6eventual20.com", "745mingiestblissfully.com", "19turanosephantasia.com",
    "30sensualizeexpression.com", "321naturelikefurfuroid.com", "449unceremoniousnasoseptal.com",
    "guidon40hyporadius9.com", "cyamidpulverulence530.com", "boonlessbestselling244.com",
    "antecoxalbobbing1010.com", "matriculant401merited.com", "scatch176duplicities.com",
    "availedsmallest.com", "counterclockwisejacky.com", "simpulumlamerop.com", "paulkitchendark.com",
    "metagnathtuggers.com", "gamoneinterrupted.com", "chromotypic.com", "crownmakermacaronicism.com",
    "generatesnitrosate.com", "yodelswartlike.com", "figeterpiazine.com", "strawberriesporail.com",
    "valeronevijao.com", "timberwoodanotia.com", "apinchcaseation.com", "nectareousoverelate.com",
    "nonesnanking.com", "kathleenmemberhistory.com", "stevenimaginelittle.com", "jamiesamewalk.com",
    "bradleyviewdoctor.com", "sandrataxeight.com", "graceaddresscommunity.com", "shannonpersonalcost.com",
    "cindyeyefinal.com", "michaelapplysome.com", "sethniceletter.com", "brucevotewithin.com",
    "rebeccaneverbase.com", "loriwithinfamily.com", "roberteachfinal.com", "erikcoldperson.com",
    "jasminetesttry.com", "heatherdiscussionwhen.com", "robertplacespace.com", "alleneconomicmatter.com",
    "josephseveralconcern.com", "donaldlineelse.com", "lisatrialidea.com", "toddpartneranimal.com",
    "jamessoundcost.com", "brittneystandardwestern.com", "sandratableother.com", "robertordercharacter.com",
    "maxfinishseveral.com", "chuckle-tube.com", "kristiesoundsimply.com", "adrianmissionminute.com",
    "richardsignfish.com", "jennifercertaindevelopment.com", "diananatureforeign.com", "goofy-banana.com",
    "mariatheserepublican.com", "johnalwayssame.com", "kellywhatcould.com", "jilliandescribecompany.com",
    "lukesitturn.com", "mikaylaarealike.com", "christopheruntilpoint.com", "walterprettytheir.com",
    "crystaltreatmenteast.com", "lauradaydo.com", "lancewhosedifficult.com",
    "dianaavoidthey.com", "jefferycontrolmodel.com", "marissasharecareer.com",
    "charlestoughrace.com", "ianrequireadult.com", "timmaybealready.com"
}
_DOMAINS.update([f"voeunblock{x}.com" for x in range(1, 11)])

_STRIP_PATTERNS = ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]

def _safe_b64(s):
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", errors="ignore")

def _deobfuscate(raw_json):
    try:
        data = json.loads(raw_json)
        if not data or not isinstance(data, list) or not data[0]:
            return None
        s = codecs.encode(data[0], "rot_13")
        for p in _STRIP_PATTERNS:
            s = s.replace(p, "")
        s = _safe_b64(s)
        s = "".join(chr(ord(c) - 3) for c in s)
        s = s[::-1]
        s = _safe_b64(s)
        return json.loads(s) if s.startswith("{") else s
    except Exception as e:
        log(f"Eroare deobfuscare: {e}")
        return None

def resolve_voe(url):
    """
    Primește un URL de VOE și returnează link-ul direct de streaming (.m3u8 / .mp4).
    Dacă eșuează, returnează None.
    """
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headers = {"User-Agent": UA, "Referer": "https://voe.sx/"}
    
    try:
        r = requests.get(url, headers=headers, timeout=15, verify=False)
        html = r.text

        m = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)', html, re.I)
        if m:
            r = requests.get(m.group(1), headers=headers, timeout=15, verify=False)
            html = r.text

        for script in re.findall(r'<script type="application/json">(.*?)</script>', html, re.S):
            result = _deobfuscate(script.strip())
            if result and isinstance(result, dict):
                stream_url = result.get("direct_access_url") or result.get("source")
                if stream_url:
                    stream_url = re.sub(r"([?&])d=1(&|$)", r"\2", stream_url).rstrip("?&")
                    log(f"Sursă extrasă cu succes: {stream_url[:60]}...")
                    return stream_url

    except Exception as e:
        log(f"Eroare la rezolvare: {e}")
        
    return None

