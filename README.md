# Publicador automático de Instagram

Publica posts no Instagram sozinho, em horários agendados, sem custo nenhum.
Roda no GitHub Actions (gratuito para repositórios públicos).

---

## Como funciona

Você joga a imagem na pasta `posts/` e adiciona uma linha no `fila.json`
dizendo a legenda e a hora de publicar. De hora em hora o GitHub acorda,
olha a fila, e publica o que já está na hora.

```
posts/foto.jpg  +  fila.json  →  GitHub Actions  →  Instagram
```

---

## Configuração inicial (uma vez só)

### 1. Criar o repositório

Crie um repositório **público** no GitHub e suba estes arquivos.

> Ele precisa ser público porque o Instagram exige que a imagem esteja
> numa URL acessível — o script usa a URL `raw.githubusercontent.com`
> do próprio repositório. Suas senhas e o token **não** ficam expostos:
> eles vão em "Secrets", que são criptografados mesmo em repo público.

### 2. Cadastrar os secrets

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Nome | Valor |
|---|---|
| `IG_USER_ID` | `17841401234293518` |
| `IG_ACCESS_TOKEN` | o token gerado no painel da Meta |

### 3. (Opcional, mas recomendado) Renovação automática do token

O token da Meta vence em 60 dias. Para ele se renovar sozinho:

1. Crie um Personal Access Token: **GitHub → Settings → Developer settings
   → Personal access tokens → Fine-grained tokens**
2. Dê acesso apenas a este repositório, com permissão
   **Secrets: Read and write**
3. Salve como um terceiro secret chamado `GH_PAT`

Sem isso, você precisa gerar um token novo no painel da Meta a cada 60 dias
e atualizar o secret `IG_ACCESS_TOKEN` na mão.

---

## Publicando um post

**1.** Coloque a imagem na pasta `posts/` (ex.: `posts/promo-setembro.jpg`)

**2.** Adicione o post no `fila.json`:

```json
[
  {
    "id": "promo-setembro",
    "imagem": "posts/promo-setembro.jpg",
    "legenda": "Texto da legenda aqui.\n\n#advocacia #direito",
    "publicar_em": "2026-09-15T09:00:00-03:00",
    "publicado": false
  }
]
```

**3.** Dê commit. Pronto — o robô publica no horário marcado.

### Campos

| Campo | Obrigatório | O que é |
|---|---|---|
| `id` | não | Nome para você identificar o post nos logs |
| `imagem` | **sim** | Caminho dentro do repo, ou uma URL completa `https://...` |
| `legenda` | não | Texto do post. Use `\n` para quebrar linha |
| `publicar_em` | não | Data/hora com fuso, ex: `2026-09-15T09:00:00-03:00`. Sem esse campo, publica na próxima execução |
| `publicado` | **sim** | Comece sempre com `false`. O robô muda para `true` sozinho |

Depois de publicar, o robô adiciona `publicado_em` e `post_id` no arquivo.
Se algo falhar, ele registra `ultimo_erro` para você ver o que houve.

---

## Requisitos da imagem (regras do Instagram)

- Formato **JPEG** (o mais seguro; PNG às vezes é recusado)
- Proporção entre **4:5** e **1.91:1** — o quadrado 1:1 sempre funciona
- Até 8 MB
- Largura recomendada: 1080 px

---

## Testando sem publicar

Na aba **Actions → Publicar no Instagram → Run workflow**, marque
**"Simular sem publicar de verdade"**. Ele roda tudo e mostra os logs,
mas não posta nada.

---

## Mudando a frequência

No arquivo `.github/workflows/publicar.yml`, a linha do cron controla
quando o robô acorda (sempre em UTC — Brasília é UTC−3):

```yaml
- cron: "0 * * * *"     # de hora em hora (padrão)
- cron: "0 12 * * *"    # todo dia às 09:00 de Brasília
- cron: "0 12 * * 1-5"  # dias úteis às 09:00 de Brasília
```

> O GitHub pode atrasar execuções agendadas em alguns minutos quando está
> com fila. Se o horário exato importa muito, deixe de hora em hora e
> controle o momento pelo campo `publicar_em`.

---

## Limitações

- **Só fotos.** Vídeos e Reels usam um fluxo diferente na API (upload
  assíncrono) — dá para adicionar depois.
- **Carrossel** também exige fluxo próprio, não está incluído.
- O Instagram limita **25 publicações por 24 horas** via API.
- A conta precisa continuar **profissional (Business/Creator)** e **pública**.

---

## Se der errado

Abra **Actions**, clique na execução que falhou e leia o log — o script
mostra exatamente em que passo parou.

| Erro | Causa comum |
|---|---|
| `OAuthException` / código 190 | Token venceu ou foi revogado. Gere outro no painel da Meta |
| `The image is not accessible` | Repositório privado, ou caminho da imagem errado no `fila.json` |
| `Aspect ratio not supported` | Imagem fora da proporção permitida |
| `Application request limit reached` | Passou do limite de 25 posts/dia |
