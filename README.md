# DOG Alerta (gratis)

Monitor simples da rune **DOG•GO•TO•THE•MOON** (ID `840000:3` no Bitcoin).
**Nao e Dogecoin.** Usa so Python padrao e APIs publicas gratis. Sem chaves pagas.

O script verifica 5 coisas a cada rodada:

| # | Gatilho | Quando alerta |
|---|---|---|
| a | Volume | Volume 24h > **US$ 1.500.000** (no maximo 1 e-mail a cada 24h) |
| b | Baleias | Carteira da lista envia **>= 50.000.000 DOG** para outra da lista |
| c | Preco | Variacao 24h de **±10%**, ou **15%** desde o ultimo preco alertado |
| d | Entrada | Sinal de **ENTRADA** ou **INVALIDACAO** (veja abaixo) |
| e | On-chain (opcional) | Fatia do top 10 muda **>= 1 ponto percentual** (espo.sh) |

Quando algum dispara, o script:

1. Imprime o alerta bem claro no log do Actions
2. Faz o job **falhar de proposito** (`exit 1`) — o GitHub manda e-mail para o dono do repo
3. Se voce configurou, tambem manda no Telegram ou Discord

## Sinal de entrada (substitui a rotina "Sinal de entrada DOG")

- **Suportes:** 0,00092–0,00090 → depois 0,00085–0,00083 → depois 0,00070 (o script usa 0,00069–0,00071)
- **Resistencias (alvos):** 0,00101 · 0,00106 · 0,00110 · 0,00120
- **ENTRADA (suporte):** preco dentro de uma zona de suporte **e** BTC 24h >= **-2%** (CoinGecko)
- **ENTRADA (rompimento):** vela **diaria fechada** da Kraken DOGUSD acima de **0,00101**
  **e** volume 24h > **US$ 1,5 milhao**
- **INVALIDACAO:** vela diaria fechada da Kraken DOGUSD abaixo de **0,00088**
  (usa a ultima vela FECHADA de `OHLC interval=1440`; a vela diaria fecha 00:00 UTC = 21:00 em Brasilia)

Para nao repetir:
- A mesma zona nao alerta de novo em menos de **24h**, e so volta a valer depois que o preco
  **sair da zona com folga de 1%** e voltar
- Rompimento alerta 1x por vela diaria; invalidacao alerta 1x e so de novo depois de um
  fechamento acima de 0,00088
- O `state.json` ja vem com o sinal de **13/10** (faixa 0,00090–0,00094) marcado como enviado,
  entao a zona 0,00090–0,00092 **nao** alerta agora; so depois que o preco sair e voltar

## Movimento de preco

- Alerta se a variacao 24h passar de **±10%** (1x a cada 24h para cada lado)
- Alerta se o preco andar **15%** (para cima ou para baixo) desde o **ultimo preco alertado**.
  Comeca em **US$ 0,00090873** (ultimo alerta da rotina antiga, 18/10). A cada alerta a referencia
  vira o preco novo

## On-chain leve (opcional)

Le `https://espo.sh/rune/840000:3` (pagina HTML publica, sem chave) e pega o numero de
**holders** e a soma do **top 10** em % do supply. So mostra no log e alerta se a fatia do
top 10 mudar 1 ponto percentual ou mais. **E leitura de pagina HTML**: se o site mudar o layout,
o script so imprime um aviso e segue (nao quebra). Para desligar, adicione no workflow
`ONCHAIN: "0"` nas variaveis de ambiente.

## 1. Criar conta e repositorio no GitHub

1. Acesse https://github.com e crie uma conta (gratis)
2. Clique em **New repository**
3. Nome sugerido: `dog-alerta`
4. Deixe **Public** (Actions gratis tem cota generosa) e **Create repository**

## 2. Subir os arquivos pelo site (sem Git)

No repo vazio, clique em **Add file → Upload files** e envie exatamente estes arquivos
(mantenha a pasta `.github/workflows/`):

```
dog_alerta.py
wallets.json
state.json
README.md
.github/workflows/dog-alerta.yml
```

No site: para criar a pasta, no nome do arquivo digite `.github/workflows/dog-alerta.yml`
e cole o conteudo. Clique em **Commit changes**.

## 3. Ligar o Actions

1. Aba **Actions** do repo → se pedir, clique em **I understand my workflows, go ahead and enable them**
2. Em **Settings → Actions → General**, marque **Allow all actions** e **Read and write permissions**
   (preciso de write para o workflow gravar o `state.json` e nao repetir o mesmo alerta)

## 4. Rodar na mao (teste)

1. Aba **Actions** → workflow **dog-alerta** → **Run workflow** → **Run workflow**
2. Abra o job e veja o log: volume, as 10 carteiras, preco, sinal de entrada e on-chain

A cada ~30 min o cron tambem dispara sozinho. **O cron do GitHub atrasa** com
frequencia (minutos a horas) — e normal.

## 5. Como o alerta chega

| Canal | Como |
|---|---|
| Log do Actions | Sempre |
| E-mail do GitHub | Automatico quando o job falha. Em github.com → Settings → Notifications → Actions, deixe ligado para o seu usuario |
| Telegram (opcional) | Secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` |
| Discord (opcional) | Secret `DISCORD_WEBHOOK_URL` |

O mesmo volume so gera um e-mail novo a cada 24h (enquanto continuar acima do limite).
Transferencias ja alertadas ficam no `state.json` e nao repetem.

## 6. Telegram (opcional)

1. No Telegram, fale com [@BotFather](https://t.me/BotFather) → `/newbot` → copie o token
2. Mande qualquer msg para o seu bot; descubra o chat_id em
   `https://api.telegram.org/botTOKEN/getUpdates` (campo `chat.id`)
3. No repo: **Settings → Secrets and variables → Actions → New repository secret**
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Para Discord: crie um webhook no canal e salve como `DISCORD_WEBHOOK_URL`.
**Nunca cole tokens no codigo nem no README.**

## 7. Intervalo e limites de taxa

- Cron recomendado: **a cada 30 minutos** (ja vem assim)
- Entre cada chamada HTTP o script espera ~1,5 s
- Sao ~10 carteiras + CoinGecko + Kraken + espo.sh ≈ 13–25 requests por rodada
- Free tiers: CoinGecko ~10–30/min, mempool.space e ordinals.com sao publicos
  (podem falhar de vez em quando; o script tenta de novo)

Se o job cair por rate limit, rode de novo depois ou aumente o intervalo no YAML
(`cron: "0 * * * *"` = 1x por hora).

## 8. Endpoints usados (todos gratis / sem chave)

| Uso | URL |
|---|---|
| Preco, volume, 24h do DOG e do BTC | `https://api.coingecko.com/api/v3/simple/price?ids=dog-go-to-the-moon-rune,bitcoin&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true` |
| Preco/volume (fallback) | `https://api.kraken.com/0/public/Ticker?pair=DOGUSD` |
| Velas diarias (entrada/invalidacao) | `https://api.kraken.com/0/public/OHLC?pair=DOGUSD&interval=1440` |
| Holders e top 10 (opcional) | `https://espo.sh/rune/840000:3` |
| Txs recentes | `https://mempool.space/api/address/{endereco}/txs` |
| Confirma DOG no UTXO | `https://ordinals.com/r/utxo/{txid}:{vout}` (header `Accept: application/json`) |

## 9. Limitacoes (importante)

- A lista de carteiras e **manual** (`wallets.json`). Quem nao esta nela nao e monitorado
- Transferencia via **carteira intermediaria** (A → X → B) pode passar despercebida
- So olha as ~50 txs mais recentes de cada endereco (API do mempool.space)
- Quantidade de DOG vem do runestone (`OP_RETURN`); se for ambiguo, confirma no ordinals.com
  (pode falhar / atrasar)
- Kraken cobre so a corretora — use CoinGecko como fonte principal
- Cron do GitHub **atrasa**; nao e um monitor em tempo real de milissegundos
- O sinal de entrada e uma regra fixa, **nao e recomendacao de investimento**
- Se o CoinGecko falhar, o BTC 24h fica sem dado e a entrada por suporte **nao** dispara
  (o rompimento e a invalidacao continuam, pois vem da Kraken)
- espo.sh e leitura de HTML: pode quebrar se o site mudar (o script so pula)

## 10. Atualizar as carteiras

Edite `wallets.json` no site do GitHub (botao lapis):

```json
{
  "nota": "Top holders. Edite a vontade.",
  "wallets": [
    {"address": "bc1p....", "label": "#1"},
    {"address": "bc1p....", "label": "minha-carteira"}
  ]
}
```

Salve (Commit). Na proxima execucao o script ja usa a lista nova.
O endereco `bc1p50n9sksy5gwe6fgrxxsqfcp6nds...hpp9k` ja esta incluido.

Extra: se quiser alertar tambem saidas grandes (>= 50M DOG) para **qualquer** destino
(nao so as da lista), no workflow adicione a variavel de ambiente `CHECK_ALL_OUTPUTS: "1"`.

## Mudar os limites

Todos os numeros ficam no topo do `dog_alerta.py` (ex.: `MOV_24H_PCT`, `SUPORTES`,
`RESISTENCIAS`, `ROMPIMENTO`, `INVALIDACAO`, `BTC_MIN_24H`). Edite e faca commit.

## Rodar no computador (opcional)

```bash
python3 dog_alerta.py
```

Nao precisa instalar nada. Codigo de saida `1` = houve alerta; `0` = tudo calmo.

---
Feito para uso pessoal. Nenhuma conta de usuario real foi usada na montagem deste repo.
