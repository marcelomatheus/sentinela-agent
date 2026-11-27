"""Valida o Compose renderizado antes de usar a rede Traefik compartilhada."""
import json
import re
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
services = config["services"]
web = services["web"]
bff = services["bff"]
api = services["api"]
db = services["db"]
worker = services["worker"]
web_worker = services["web_worker"]


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SystemExit(f"ERRO compose.production: {reason}")


def nets(service: dict) -> set[str]:
    return set(service.get("networks", {}))


require(not web.get("ports") and not bff.get("ports"), "frontend/BFF nao podem publicar portas no host")
require(nets(web) == {"proxy"}, "frontend so pode participar da rede do Traefik")
require(nets(bff) == {"default", "proxy"}, "BFF precisa da rede privada e da rede proxy")
require("proxy" not in nets(api) | nets(db) | nets(worker) | nets(web_worker),
        "API, banco e workers nao podem estar expostos na rede Traefik")
require("whatsapp_internal" in nets(api) and "whatsapp_internal" in nets(worker),
        "preservar integracao Evolution na rede existente")
require("whatsapp_internal" not in nets(db), "PostgreSQL nao deve compartilhar rede com Evolution")
require(not db.get("ports"), "PostgreSQL nao pode publicar portas")
require(all(port.get("host_ip") == "127.0.0.1" for port in api.get("ports", [])),
        "porta legada da API deve continuar restrita ao loopback")
require(bff["environment"]["PORT"] == "19573", "BFF precisa escutar na porta 19573")
require(bff["environment"]["BFF_ALLOW_HTTP"] == "false", "cookies precisam de HTTPS publico")
require(bff["environment"]["BFF_PUBLIC_URL"].startswith("https://"), "BFF deve ter URL HTTPS")
require(web["expose"] == ["18561"] and bff["expose"] == ["19573"],
        "portas internas diferentes 18561/19573 obrigatorias")
require(config["networks"]["proxy"]["external"] is True, "rede do Traefik deve ser externa")
require("pgdata" in config["volumes"] and "web_media" in config["volumes"],
        "overlay deve reutilizar volumes persistentes existentes")
for name, port in (("sentinela-web", "18561"), ("sentinela-bff", "19573")):
    service = web if name.endswith("web") else bff
    labels = service["labels"]
    require(labels.get("traefik.enable") == "true", f"{name} sem Traefik")
    require(labels.get(f"traefik.http.services.{name}.loadbalancer.server.port") == port,
            f"{name} com porta incorreta")
    require(labels.get("traefik.docker.network") == config["networks"]["proxy"]["name"],
            f"{name} na rede errada")
    rule = labels.get(f"traefik.http.routers.{name}.rule", "")
    require("Host(" in rule, f"{name} sem regra Host")
    require(labels.get(f"traefik.http.routers.{name}.entrypoints") is not None,
            f"{name} sem entrypoint")
require("PathPrefix(`/api/`)" in bff["labels"]["traefik.http.routers.sentinela-bff.rule"],
        "BFF precisa roteamento /api")
require("PathPrefix(`/auth/`)" in bff["labels"]["traefik.http.routers.sentinela-bff.rule"],
        "BFF precisa roteamento /auth")
require(int(bff["labels"]["traefik.http.routers.sentinela-bff.priority"]) >
        int(web["labels"]["traefik.http.routers.sentinela-web.priority"]),
        "rotas de API devem ter prioridade sobre SPA")
require(not re.search(r"example\.(com|invalid)$", bff["environment"]["BFF_PUBLIC_URL"])
        or "CI" in sys.argv[2:], "substitua o dominio de exemplo antes do deploy")
print("OK: producao Traefik isolada; React 18561, BFF 19573, volumes originais preservados.")
