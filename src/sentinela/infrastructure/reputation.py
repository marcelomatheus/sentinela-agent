"""Passive URL inspection. Never fetches the target itself."""
import re
import ipaddress
from urllib.parse import urlsplit
import httpx
from sentinela.domain.model import Fact

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+",re.I)

class UrlReputation:
    def __init__(self, api_key: str = "", client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=8,follow_redirects=False)

    def inspect(self,text: str) -> frozenset[Fact]:
        urls=list(dict.fromkeys(u.rstrip(".,);!?") for u in URL_PATTERN.findall(text)))[:10]
        facts: set[Fact]=set()
        if not urls:
            return frozenset()
        facts.add(Fact.LINK)
        candidates=[]
        for url in urls:
            try:
                p=urlsplit(url)
                host=p.hostname
                if not host:
                    continue
                if p.username or p.password or "xn--" in host:
                    facts.add(Fact.SUSPICIOUS_URL)
                try:
                    ipaddress.ip_address(host)
                    facts.add(Fact.SUSPICIOUS_URL)
                except ValueError:
                    pass
                # Do not submit query strings, fragments, credentials or private hosts.
                if "." in host and not p.username and not p.password:
                    try:
                        ipaddress.ip_address(host)
                        continue
                    except ValueError:
                        pass
                    if not host.endswith((".local",".internal",".localhost")):
                        candidates.append(f"{p.scheme}://{host}/")
            except ValueError:
                continue
        if self.api_key and candidates:
            try:
                response=self.client.post("https://safebrowsing.googleapis.com/v4/threatMatches:find",
                    params={"key":self.api_key},json={"client":{"clientId":"sentinela","clientVersion":"0.1"},
                    "threatInfo":{"threatTypes":["MALWARE","SOCIAL_ENGINEERING","UNWANTED_SOFTWARE"],
                    "platformTypes":["ANY_PLATFORM"],"threatEntryTypes":["URL"],
                    "threatEntries":[{"url":u} for u in candidates]}})
                response.raise_for_status()
                if response.json().get("matches"):
                    facts.add(Fact.MALICIOUS_URL)
            except (httpx.HTTPError,ValueError):
                pass
        return frozenset(facts)
