#!/usr/bin/env python3
"""
Publicador automatico de posts no Instagram.

Le a fila em `fila.json`, encontra os posts cujo horario ja chegou
e ainda nao foram publicados, e publica cada um via Instagram API.

Variaveis de ambiente necessarias:
  IG_USER_ID        -> ID numerico da conta do Instagram
  IG_ACCESS_TOKEN   -> token de acesso (guardado como secret no GitHub)

Opcionais:
  IG_API_VERSION    -> default v23.0
  GITHUB_REPOSITORY -> preenchido automaticamente pelo GitHub Actions
  GITHUB_REF_NAME   -> branch atual (default: main)
  DRY_RUN           -> "1" para simular sem publicar de verdade
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

RAIZ = Path(__file__).resolve().parent
FILA = RAIZ / "fila.json"

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
BASE = f"https://graph.instagram.com/{API_VERSION}"

IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip() == "1"

# Fuso de Brasilia (UTC-3)
FUSO_BR = timezone(timedelta(hours=-3))

# Quantas vezes checar se o container de midia terminou de processar.
# Video demora muito mais que foto: a Meta precisa transcodificar.
MAX_TENTATIVAS_FOTO = 30      # ~2,5 min
MAX_TENTATIVAS_VIDEO = 90     # ~15 min
INTERVALO_STATUS = 5          # segundos

# Extensoes reconhecidas como video (publicadas como Reels)
EXTENSOES_VIDEO = (".mp4", ".mov")


def limpar_segredos(texto: str) -> str:
    """
    Remove o token de qualquer texto antes de exibir ou gravar em arquivo.

    Importante: o fila.json vai para um repositorio publico, e mensagens de
    erro da biblioteca de rede costumam incluir a URL inteira (com o token).
    """
    texto = str(texto)
    if IG_TOKEN:
        texto = texto.replace(IG_TOKEN, "***TOKEN***")
    # Rede de seguranca: mata qualquer access_token=... que sobre
    texto = re.sub(r"(access_token=)[^&\s'\"]+", r"\1***TOKEN***", texto)
    return texto


def log(msg: str) -> None:
    agora = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{agora}] {limpar_segredos(msg)}", flush=True)


def erro_fatal(msg: str) -> None:
    log(f"ERRO: {msg}")
    sys.exit(1)


def carregar_fila() -> list:
    if not FILA.exists():
        erro_fatal(f"arquivo {FILA.name} nao encontrado")
    try:
        dados = json.loads(FILA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        erro_fatal(f"{FILA.name} nao e um JSON valido: {e}")
    if not isinstance(dados, list):
        erro_fatal(f"{FILA.name} deve conter uma lista de posts")
    return dados


def salvar_fila(fila: list) -> None:
    FILA.write_text(
        json.dumps(fila, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def url_publica_da_imagem(caminho_relativo: str) -> str:
    """
    Monta a URL publica da imagem.

    Se o post ja traz uma URL completa (http...), usa ela direto.
    Caso contrario, monta a URL raw do proprio repositorio no GitHub.
    """
    if caminho_relativo.startswith(("http://", "https://")):
        return caminho_relativo

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        erro_fatal(
            "GITHUB_REPOSITORY nao definida. Rodando fora do GitHub Actions? "
            "Nesse caso use uma URL completa no campo 'imagem'."
        )

    branch = os.environ.get("GITHUB_REF_NAME", "main")
    caminho = quote(caminho_relativo.lstrip("/"))
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{caminho}"


def chamar_api(metodo: str, endpoint: str, params: dict) -> dict:
    params = {**params, "access_token": IG_TOKEN}
    url = f"{BASE}/{endpoint}"
    try:
        resp = requests.request(metodo, url, params=params, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"falha de rede ao chamar {endpoint}: {e}") from e

    try:
        corpo = resp.json()
    except ValueError:
        corpo = {"raw": resp.text[:500]}

    if resp.status_code >= 400:
        detalhe = corpo.get("error", corpo)
        raise RuntimeError(f"API respondeu {resp.status_code} em {endpoint}: {detalhe}")

    return corpo


def eh_video(post: dict, caminho: str) -> bool:
    """
    Decide se o post e video (Reels) ou foto.

    Prioridade: campo 'tipo' explicito na fila; senao, a extensao do arquivo.
    """
    tipo = str(post.get("tipo", "")).strip().lower()
    if tipo in ("reels", "reel", "video", "video"):
        return True
    if tipo in ("foto", "imagem", "image", "photo"):
        return False
    return caminho.lower().split("?")[0].endswith(EXTENSOES_VIDEO)


def criar_container(midia_url: str, legenda: str, post: dict, video: bool) -> str:
    if video:
        log("  criando container de Reels...")
        params = {
            "media_type": "REELS",
            "video_url": midia_url,
            "caption": legenda,
        }
        # Opcionais, so entram se o post pedir
        if post.get("capa"):
            params["cover_url"] = url_publica_da_imagem(post["capa"])
        if post.get("thumb_offset") is not None:
            params["thumb_offset"] = post["thumb_offset"]
        # Por padrao o Reels tambem aparece no feed
        params["share_to_feed"] = "true" if post.get("no_feed", True) else "false"
    else:
        log("  criando container de foto...")
        params = {"image_url": midia_url, "caption": legenda}

    resp = chamar_api("POST", f"{IG_USER_ID}/media", params)
    container_id = resp.get("id")
    if not container_id:
        raise RuntimeError(f"resposta sem id do container: {resp}")
    log(f"  container criado: {container_id}")
    return container_id


def esperar_container_pronto(container_id: str, video: bool) -> None:
    """
    A Meta processa a midia de forma assincrona. Esperamos ficar FINISHED.

    Video leva bem mais tempo que foto porque precisa ser transcodificado.
    """
    maximo = MAX_TENTATIVAS_VIDEO if video else MAX_TENTATIVAS_FOTO
    if video:
        log(f"  aguardando a Meta processar o video (ate ~{maximo * INTERVALO_STATUS // 60} min)...")

    for tentativa in range(1, maximo + 1):
        resp = chamar_api("GET", container_id, {"fields": "status_code,status"})
        status = resp.get("status_code")

        if status == "FINISHED":
            log("  midia processada com sucesso")
            return
        if status == "ERROR":
            raise RuntimeError(f"processamento da midia falhou: {resp.get('status')}")

        # Video demora: nao poluir o log com uma linha a cada 5s
        if not video or tentativa % 6 == 0 or tentativa <= 2:
            log(f"  status={status} (tentativa {tentativa}/{maximo})")
        time.sleep(INTERVALO_STATUS)

    raise RuntimeError("tempo esgotado esperando o processamento da midia")


def publicar_container(container_id: str) -> str:
    log("  publicando...")
    resp = chamar_api(
        "POST",
        f"{IG_USER_ID}/media_publish",
        {"creation_id": container_id},
    )
    post_id = resp.get("id")
    if not post_id:
        raise RuntimeError(f"resposta sem id do post: {resp}")
    return post_id


def esta_na_hora(post: dict, agora: datetime) -> bool:
    quando = post.get("publicar_em")
    if not quando:
        # Sem horario definido = publica na proxima execucao
        return True
    try:
        alvo = datetime.fromisoformat(quando)
    except ValueError:
        log(f"  AVISO: 'publicar_em' invalido ({quando}), ignorando este post")
        return False
    if alvo.tzinfo is None:
        alvo = alvo.replace(tzinfo=FUSO_BR)
    return alvo <= agora


def main() -> None:
    if not IG_USER_ID:
        erro_fatal("IG_USER_ID nao definida")
    if not IG_TOKEN:
        erro_fatal("IG_ACCESS_TOKEN nao definida")

    fila = carregar_fila()
    agora = datetime.now(FUSO_BR)

    pendentes = [
        (i, p)
        for i, p in enumerate(fila)
        if not p.get("publicado") and esta_na_hora(p, agora)
    ]

    if not pendentes:
        log("Nenhum post na hora de publicar. Nada a fazer.")
        return

    log(f"{len(pendentes)} post(s) para publicar agora.")

    houve_mudanca = False
    falhas = 0

    for indice, post in pendentes:
        identificador = post.get("id") or f"indice-{indice}"
        log(f"Post '{identificador}':")

        # 'imagem' e o nome historico do campo; 'video' e 'midia' tambem valem
        midia = post.get("imagem") or post.get("video") or post.get("midia")
        legenda = post.get("legenda", "")

        if not midia:
            log("  ERRO: nenhum arquivo indicado (use 'imagem' ou 'video'). Pulando.")
            falhas += 1
            continue

        try:
            video = eh_video(post, midia)
            midia_url = url_publica_da_imagem(midia)
            log(f"  {'video (Reels)' if video else 'foto'}: {midia_url}")

            if DRY_RUN:
                log("  DRY_RUN ativo - nada foi publicado de verdade")
                continue

            container_id = criar_container(midia_url, legenda, post, video)
            esperar_container_pronto(container_id, video)
            post_id = publicar_container(container_id)

            post["publicado"] = True
            post["publicado_em"] = agora.isoformat()
            post["post_id"] = post_id
            houve_mudanca = True

            log(f"  PUBLICADO com sucesso. ID do post: {post_id}")

        except Exception as e:
            log(f"  FALHOU: {e}")
            post["ultimo_erro"] = limpar_segredos(e)[:500]
            post["ultima_tentativa"] = agora.isoformat()
            houve_mudanca = True
            falhas += 1

    if houve_mudanca:
        salvar_fila(fila)
        log("fila.json atualizado.")

    if falhas:
        erro_fatal(f"{falhas} post(s) falharam. Veja os detalhes acima.")

    log("Concluido.")


if __name__ == "__main__":
    main()
