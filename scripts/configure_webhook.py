"""Configure explicitamente o webhook de uma instância existente (substitui o anterior)."""
import argparse
import os
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='confirma substituição do webhook existente')
    parser.add_argument('--route', choices=['webhook/set', 'event/webhook/set'], default='webhook/set')
    args = parser.parse_args()
    if not args.apply:
        parser.error('use --apply para confirmar a alteração da configuração da instância')
    load_dotenv()
    base = os.environ['EVOLUTION_API_URL'].rstrip('/')
    instance = quote(os.environ['EVOLUTION_INSTANCE'], safe='')
    target = os.environ['PUBLIC_WEBHOOK_URL']
    if urlsplit(target).scheme != 'https':
        parser.error('PUBLIC_WEBHOOK_URL deve usar HTTPS')
    secret = os.environ['WEBHOOK_API_KEY']
    if len(secret) < 24:
        parser.error('WEBHOOK_API_KEY deve ter pelo menos 24 caracteres')
    body = {'webhook': {'enabled': True, 'url': target, 'webhookByEvents': False,
                        'webhookBase64': False, 'headers': {'apikey': secret},
                        'events': ['MESSAGES_UPSERT', 'PRESENCE_UPDATE']}}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(f'{base}/{args.route}/{instance}', json=body,
                                   headers={'apikey': os.environ['EVOLUTION_API_KEY']})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(f'Falha na configuração: {type(exc).__name__}; confira versão/rota e permissões.') from None
    print('Configuração aceita. Verifique o header e faça um teste real de mensagem na instância.')


if __name__ == '__main__':
    main()
