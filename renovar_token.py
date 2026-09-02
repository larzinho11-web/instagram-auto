#!/usr/bin/env python3
"""
Renova o token de longa duracao do Instagram e atualiza o secret no GitHub.

O token de longa duracao vale 60 dias. Este script renova por mais 60 dias
e grava o novo valor de volta no secret IG_ACCESS_TOKEN do repositorio,
para que a automacao nunca pare sozinha.

Variaveis de ambiente necessarias:
  IG_ACCESS_TOKEN   -> token atual
  GH_PAT            -> Personal Access Token do GitHub com permissao
                       de escrita em "Secrets" do repositorio
  GITHUB_REPOSITORY -> preenchido automaticamente pelo GitHub Actions

Requer: requests, pynacl
"""

import os
import sys
from base64 import b64encode
from datetime import datetime, timezone, timedelta

import requests
from nacl import encoding, public

FUSO_BR = timezone(timedelta(hours=-3))

IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
GH_PAT = os.environ.get("GH_PAT", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()

NOME_DO_SECRET = "IG_ACCESS_TOKEN"


def log(msg: str) -> None:
    agora = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)


def erro_fatal(msg: str) -> None:
    log(f"ERRO: {msg}")
    sys.exit(1)


def renovar_token(token_atual: str) -> str:
    log("Renovando token junto a Meta...")
    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token_atual},
        timeout=60,
    )
    dados = resp.json()

    if resp.status_code >= 400:
        erro_fatal(f"a Meta recusou a renovacao: {dados.get('error', dados)}")

    novo = dados.get("access_token")
    if not novo:
        erro_fatal(f"resposta sem access_token: {dados}")

    dias = int(dados.get("expires_in", 0)) // 86400
    log(f"Token renovado. Nova validade: ~{dias} dias.")
    return novo


def cabecalhos_github() -> dict:
    return {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def buscar_chave_publica() -> tuple:
    url = f"https://api.github.com/repos/{REPO}/actions/secrets/public-key"
    resp = requests.get(url, headers=cabecalhos_github(), timeout=30)
    if resp.status_code >= 400:
        erro_fatal(f"nao consegui ler a chave publica do repo: {resp.text[:300]}")
    dados = resp.json()
    return dados["key"], dados["key_id"]


def criptografar(chave_publica_b64: str, valor: str) -> str:
    chave = public.PublicKey(chave_publica_b64.encode("utf-8"), encoding.Base64Encoder())
    caixa = public.SealedBox(chave)
    return b64encode(caixa.encrypt(valor.encode("utf-8"))).decode("utf-8")


def gravar_secret(novo_token: str) -> None:
    log(f"Gravando novo valor no secret {NOME_DO_SECRET}...")
    chave_b64, key_id = buscar_chave_publica()
    cifrado = criptografar(chave_b64, novo_token)

    url = f"https://api.github.com/repos/{REPO}/actions/secrets/{NOME_DO_SECRET}"
    resp = requests.put(
        url,
        headers=cabecalhos_github(),
        json={"encrypted_value": cifrado, "key_id": key_id},
        timeout=30,
    )
    if resp.status_code >= 400:
        erro_fatal(f"falha ao gravar o secret: {resp.text[:300]}")

    log("Secret atualizado com sucesso.")


def main() -> None:
    if not IG_TOKEN:
        erro_fatal("IG_ACCESS_TOKEN nao definida")
    if not GH_PAT:
        erro_fatal("GH_PAT nao definida (necessaria para atualizar o secret)")
    if not REPO:
        erro_fatal("GITHUB_REPOSITORY nao definida")

    novo = renovar_token(IG_TOKEN)
    gravar_secret(novo)
    log("Concluido.")


if __name__ == "__main__":
    main()
