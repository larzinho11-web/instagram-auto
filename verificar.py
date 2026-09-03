#!/usr/bin/env python3
"""
Verifica se a conexao com o Instagram esta funcionando.

NAO publica nada. Apenas le os dados da conta para confirmar que o
token e o ID estao corretos e validos.

Variaveis de ambiente:
  IG_USER_ID
  IG_ACCESS_TOKEN
"""

import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
BASE = f"https://graph.instagram.com/{API_VERSION}"

IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()

FUSO_BR = timezone(timedelta(hours=-3))


def limpar_segredos(texto: str) -> str:
    texto = str(texto)
    if IG_TOKEN:
        texto = texto.replace(IG_TOKEN, "***TOKEN***")
    return re.sub(r"(access_token=)[^&\s'\"]+", r"\1***TOKEN***", texto)


def log(msg: str) -> None:
    agora = datetime.now(FUSO_BR).strftime("%H:%M:%S")
    print(f"[{agora}] {limpar_segredos(msg)}", flush=True)


def main() -> None:
    print("=" * 55)
    print("  VERIFICACAO DA CONEXAO COM O INSTAGRAM")
    print("=" * 55)

    problemas = []

    # 1. Os secrets existem?
    log("1/3  Conferindo os secrets...")
    if not IG_USER_ID:
        problemas.append("IG_USER_ID nao esta configurado nos secrets")
    else:
        log(f"     IG_USER_ID presente: {IG_USER_ID}")

    if not IG_TOKEN:
        problemas.append("IG_ACCESS_TOKEN nao esta configurado nos secrets")
    else:
        log(f"     IG_ACCESS_TOKEN presente ({len(IG_TOKEN)} caracteres)")
        if not IG_TOKEN.startswith("IGAA"):
            log("     AVISO: o token normalmente comeca com 'IGAA'. Confira se colou o valor certo.")

    if problemas:
        for p in problemas:
            log(f"     ERRO: {p}")
        sys.exit(1)

    # 2. O token funciona e aponta para a conta certa?
    log("2/3  Consultando a conta na API do Instagram...")
    try:
        resp = requests.get(
            f"{BASE}/{IG_USER_ID}",
            params={
                "fields": "id,username,account_type,media_count",
                "access_token": IG_TOKEN,
            },
            timeout=60,
        )
        dados = resp.json()
    except Exception as e:
        log(f"     ERRO de rede: {e}")
        sys.exit(1)

    if resp.status_code >= 400:
        erro = dados.get("error", dados)
        log(f"     ERRO: a API recusou a consulta -> {erro}")
        codigo = (erro or {}).get("code") if isinstance(erro, dict) else None
        if codigo == 190:
            log("")
            log("     Isso quase sempre significa token vencido ou revogado.")
            log("     Gere um novo no painel da Meta e atualize o secret IG_ACCESS_TOKEN.")
        sys.exit(1)

    log(f"     Conta: @{dados.get('username')}")
    log(f"     Tipo: {dados.get('account_type')}")
    log(f"     Publicacoes existentes: {dados.get('media_count')}")

    # 3. Quanto resta da cota diaria de publicacao?
    log("3/3  Consultando o limite diario de publicacao...")
    try:
        resp2 = requests.get(
            f"{BASE}/{IG_USER_ID}/content_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": IG_TOKEN},
            timeout=60,
        )
        d2 = resp2.json()
        if resp2.status_code < 400 and d2.get("data"):
            item = d2["data"][0]
            usado = item.get("quota_usage", 0)
            total = (item.get("config") or {}).get("quota_total", 25)
            log(f"     Publicacoes usadas nas ultimas 24h: {usado} de {total}")
        else:
            log("     (nao foi possivel ler a cota - isso nao impede a publicacao)")
    except Exception:
        log("     (nao foi possivel ler a cota - isso nao impede a publicacao)")

    print()
    print("=" * 55)
    print("  TUDO CERTO. A automacao esta pronta para publicar.")
    print("=" * 55)


if __name__ == "__main__":
    main()
