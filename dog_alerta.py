#!/usr/bin/env python3
"""DOG Alerta - monitor gratuito da rune DOG•GO•TO•THE•MOON (ID 840000:3). NAO e Dogecoin.
Usa somente a biblioteca padrao do Python. Sem chaves. Sai com codigo 1 quando ha alerta.
Gatilhos: (a) volume 24h, (b) transferencias entre carteiras grandes, (c) movimento de preco,
(d) sinal de entrada / invalidacao, (e) on-chain leve opcional (espo.sh),
(f) carteiras convictas e dormentes (saldo via ordinals.com)."""
import json, os, re, sys, time, urllib.request

VOL_LIMITE_USD = 1_500_000      # gatilho (a): volume 24h acima disto
DOG_LIMITE = 50_000_000         # gatilho (b): transferencia >= isto (em DOG)
DIVISIBILIDADE = 5              # DOG tem 5 casas decimais
RUNE_ID = (840000, 3)
JANELA_HORAS = 24               # so olha txs das ultimas ~24h (ou novas desde o ultimo state)
REALERTA_VOL_HORAS = 24         # repete alerta de volume no maximo 1x a cada 24h
PAUSA = 1.5                     # segundos entre chamadas (gentil com os limites)
# (c) movimento de preco
MOV_24H_PCT = 10.0              # alerta se |variacao 24h| >= 10%
MOV_DESDE_ALERTA_PCT = 15.0     # alerta se o preco andou >= 15% desde o ultimo preco alertado
# (d) sinal de entrada (substitui a rotina "Sinal de entrada DOG")
SUPORTES = [("suporte_1", 0.00090, 0.00092), ("suporte_2", 0.00083, 0.00085), ("suporte_3", 0.00069, 0.00071)]
RESISTENCIAS = [0.00101, 0.00106, 0.00110, 0.00120]
ROMPIMENTO = 0.00101            # fechamento diario Kraken acima disto + volume > VOL_LIMITE_USD
INVALIDACAO = 0.00088           # fechamento diario Kraken abaixo disto
BTC_MIN_24H = -2.0              # entrada em suporte so se BTC 24h >= -2%
REARMA_MARGEM = 0.01            # zona so rearma depois que o preco sai 1% para fora dela
REALERTA_ZONA_HORAS = 24
# (e) on-chain leve (opcional; desligue com ONCHAIN=0)
TOP10_MUDANCA_PP = 1.0          # alerta se a fatia do top 10 mudar >= 1 ponto percentual
CG = ("https://api.coingecko.com/api/v3/simple/price?ids=dog-go-to-the-moon-rune,bitcoin"
      "&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true")
KRAKEN = "https://api.kraken.com/0/public/Ticker?pair=DOGUSD"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC?pair=DOGUSD&interval={}"
ESPO = "https://espo.sh/rune/840000:3"
MEMPOOL = "https://mempool.space/api/address/{}/txs"
ORD = "https://ordinals.com/r/utxo/{}:{}"
AQUI = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(AQUI, "state.json")


def get(url, headers=None, tentativas=4):
    h = {"User-Agent": "dog-alerta/1.0", "Accept": "application/json"}
    h.update(headers or {})
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print(f"  aviso: falha em {url[:70]} ({e}); tentativa {i + 1}/{tentativas}")
            if i + 1 < tentativas:
                time.sleep(PAUSA * 2 * (i + 1))
    return None


def post_json(url, dados):
    req = urllib.request.Request(url, data=json.dumps(dados).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "dog-alerta/1.0"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print(f"  aviso: notificacao falhou ({e})")


def notificar(texto):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        post_json(f"https://api.telegram.org/bot{tok}/sendMessage", {"chat_id": chat, "text": texto})
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook:
        post_json(hook, {"content": texto[:1900]})


# ---------------- dados de mercado ----------------
class Alertas(list):
    """Lista de alertas que IMPRIME cada motivo no momento em que e registrado (nunca ha alerta silencioso)."""
    def append(self, motivo):
        print("  " + "!" * 3 + " DOG ALERTA: " + motivo)
        super().append(motivo)


def gh_escape(t):
    return t.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def publicar_github(alertas, erros):
    """Escreve motivos no resumo do job, anotacoes ::error e GITHUB_OUTPUT (so dentro do Actions)."""
    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            if alertas:
                f.write("## !!! DOG ALERTA\n\n" + "".join(f"- {a}\n" for a in alertas) + "\n")
            else:
                f.write("## DOG: nenhum alerta. Tudo calmo.\n\n")
            if erros:
                f.write("### Avisos (nao sao alertas)\n\n" + "".join(f"- {e}\n" for e in erros) + "\n")
    for a in alertas:
        print(f"::error title=DOG ALERTA::{gh_escape(a)}")
    for e in erros:
        print(f"::warning title=DOG erro de checagem::{gh_escape(e)}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"alertas={len(alertas)}\n")


def kraken_ohlc(intervalo):
    d = get(KRAKEN_OHLC.format(intervalo))
    try:
        return [c for k, c in d["result"].items() if k != "last"][0]
    except Exception:
        return None


def mercado():
    """Preco, volume e variacao 24h do DOG (CoinGecko; fallback Kraken) + BTC 24h (CoinGecko)."""
    m = {"preco": None, "vol": None, "chg24": None, "btc24": None, "fonte": None}
    d = get(CG)
    try:
        v, b = d["dog-go-to-the-moon-rune"], d.get("bitcoin", {})
        m.update(preco=float(v["usd"]), vol=float(v["usd_24h_vol"]), chg24=float(v["usd_24h_change"]),
                 fonte="CoinGecko")
        m["btc24"] = float(b["usd_24h_change"]) if "usd_24h_change" in b else None
        return m
    except Exception:
        print("  CoinGecko indisponivel; usando Kraken (so uma corretora, volume menor)")
    d = get(KRAKEN)
    try:
        t = list(d["result"].values())[0]
        m.update(preco=float(t["c"][0]), vol=float(t["v"][1]) * float(t["p"][1]), fonte="Kraken DOGUSD")
        h = kraken_ohlc(60)  # variacao 24h = ultimo vs fechamento de 24 velas de 1h atras
        if h and len(h) > 25:
            m["chg24"] = (m["preco"] / float(h[-25][4]) - 1) * 100
    except Exception:
        pass
    return m


def checar_volume(m, state, alertas):
    vol, preco, fonte = m["vol"], m["preco"], m["fonte"]
    if vol is None:
        print("  ERRO: nao foi possivel obter o volume (CoinGecko e Kraken falharam)")
        return
    print(f"  Volume 24h: US$ {vol:,.0f} | preco US$ {preco:.6f} | fonte {fonte} | limite US$ {VOL_LIMITE_USD:,}")
    sv = state.setdefault("vol", {"above": False, "last_alert": 0})
    if vol > VOL_LIMITE_USD:
        if not sv["above"] or time.time() - sv["last_alert"] > REALERTA_VOL_HORAS * 3600:
            alertas.append(f"VOLUME 24h do DOG = US$ {vol:,.0f} (> US$ {VOL_LIMITE_USD:,}) fonte {fonte}")
            sv["last_alert"] = int(time.time())
        else:
            print("  (acima do limite, mas ja alertado nas ultimas 24h)")
    sv["above"] = vol > VOL_LIMITE_USD


# ---------------- gatilho (c): movimento de preco ----------------
def checar_preco(m, state, alertas):
    p, chg = m["preco"], m["chg24"]
    if p is None:
        print("  sem preco, pulando")
        return
    sp = state.setdefault("preco", {})
    ref = sp.get("ultimo_preco_alertado") or p
    desde = (p / ref - 1) * 100
    print(f"  Preco US$ {p:.8f} | 24h {chg if chg is None else round(chg, 2)}% | "
          f"desde ultimo alerta (US$ {ref:.8f}) {desde:+.2f}%")
    agora, msgs = int(time.time()), []
    if chg is not None and abs(chg) >= MOV_24H_PCT:
        lado = "sobe" if chg > 0 else "cai"
        if agora - sp.get(f"alerta_24h_{lado}", 0) > 24 * 3600:
            msgs.append(f"DOG {lado} {chg:+.1f}% em 24h (limite ±{MOV_24H_PCT:.0f}%)")
            sp[f"alerta_24h_{lado}"] = agora
        else:
            print("  (movimento 24h ja alertado nas ultimas 24h)")
    if abs(desde) >= MOV_DESDE_ALERTA_PCT:
        msgs.append(f"DOG andou {desde:+.1f}% desde o ultimo preco alertado US$ {ref:.8f} "
                    f"(limite {MOV_DESDE_ALERTA_PCT:.0f}%)")
    for t in msgs:
        alertas.append(f"PRECO: {t}. Agora US$ {p:.8f} ({m['fonte']})")
    if msgs or not sp.get("ultimo_preco_alertado"):
        sp["ultimo_preco_alertado"], sp["ultimo_alerta_em"] = p, agora


# ---------------- gatilho (d): sinal de entrada / invalidacao ----------------
def alvos(p):
    return ", ".join(f"{r:.5f}" for r in RESISTENCIAS if r > p) or "acima de todas as resistencias"


def checar_entrada(m, state, alertas):
    p, btc = m["preco"], m["btc24"]
    se = state.setdefault("entrada", {})
    zonas = se.setdefault("zonas", {})
    agora = int(time.time())
    if p is not None:
        print(f"  Preco US$ {p:.8f} | BTC 24h {btc if btc is None else round(btc, 2)}% (minimo {BTC_MIN_24H}%)")
        for nome, lo, hi in SUPORTES:
            z = zonas.setdefault(nome, {"armada": True, "ultimo_alerta": 0})
            dentro = lo <= p <= hi
            if not dentro and (p < lo * (1 - REARMA_MARGEM) or p > hi * (1 + REARMA_MARGEM)):
                z["armada"] = True  # saiu da zona com folga -> pode alertar de novo na volta
            if not dentro:
                continue
            faixa = f"{lo:.5f}-{hi:.5f}"
            if not z["armada"] or agora - z["ultimo_alerta"] < REALERTA_ZONA_HORAS * 3600:
                print(f"  dentro da zona {faixa}, mas ja sinalizada (espera sair da zona e 24h)")
            elif btc is None:
                print(f"  dentro da zona {faixa}, mas sem BTC 24h (CoinGecko) -> sem sinal")
            elif btc < BTC_MIN_24H:
                print(f"  dentro da zona {faixa}, mas BTC 24h {btc:.2f}% < {BTC_MIN_24H}% -> sem sinal")
            else:
                alertas.append(f"ENTRADA DOG: preco US$ {p:.8f} na zona de suporte {faixa} e BTC 24h "
                               f"{btc:+.2f}%. Alvos: {alvos(p)}. Invalida com fechamento diario < {INVALIDACAO:.5f}")
                z.update(armada=False, ultimo_alerta=agora)
    else:
        print("  sem preco atual, so checando fechamento diario")

    velas = kraken_ohlc(1440)
    if not velas or len(velas) < 2:
        print("  ERRO: Kraken OHLC diario indisponivel")
        return
    v = velas[-2]  # ultima vela FECHADA (a ultima da lista ainda esta aberta)
    t, fech = int(v[0]), float(v[4])
    dia = time.strftime("%Y-%m-%d", time.gmtime(t))
    print(f"  Kraken DOGUSD fechamento diario {dia} (UTC): US$ {fech:.6f}")
    vol = m["vol"]
    if fech > ROMPIMENTO and se.get("rompimento_vela") != t:
        if vol is not None and vol > VOL_LIMITE_USD:
            alertas.append(f"ENTRADA DOG (rompimento): fechamento diario Kraken {dia} US$ {fech:.6f} > "
                           f"{ROMPIMENTO:.5f} com volume 24h US$ {vol:,.0f}. Proximos alvos: {alvos(fech)}")
            se["rompimento_vela"] = t
        else:
            print(f"  fechou acima de {ROMPIMENTO:.5f}, mas volume 24h abaixo de US$ {VOL_LIMITE_USD:,}")
    abaixo = fech < INVALIDACAO
    if abaixo and not se.get("invalidado"):
        alertas.append(f"INVALIDACAO DOG: fechamento diario Kraken {dia} US$ {fech:.6f} < {INVALIDACAO:.5f}")
        se["invalidacao_vela"] = t
    se["invalidado"] = abaixo  # so alerta de novo depois de um fechamento >= INVALIDACAO


# ---------------- gatilho (e): on-chain leve (espo.sh, opcional) ----------------
def checar_onchain(state, alertas):
    if os.environ.get("ONCHAIN", "1") == "0":
        print("  desligado (ONCHAIN=0)")
        return
    try:
        req = urllib.request.Request(ESPO, headers={"User-Agent": "dog-alerta/1.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        holders = int(re.search(r'Holders</span>\s*<div class="alkane-stat-line">\s*'
                                r'<span class="alkane-stat-value">([\d,]+)<', html).group(1).replace(",", ""))
        pcts = [float(x) for x in re.findall(r'alk-holding-pct mono">([\d.]+)%<', html)][:10]
        if len(pcts) < 10:
            raise ValueError("tabela de holders incompleta")
    except Exception as e:
        print(f"  espo.sh indisponivel ou layout mudou ({str(e)[:80]}); pulando (nao e erro)")
        return
    top10 = round(sum(pcts), 2)
    so = state.setdefault("onchain", {})
    ref = so.get("top10_ref")
    print(f"  Holders: {holders:,} | top 10: {top10:.2f}% do supply"
          + (f" | referencia {ref:.2f}%" if ref else ""))
    if ref is not None and abs(top10 - ref) >= TOP10_MUDANCA_PP:
        alertas.append(f"ON-CHAIN: fatia do top 10 foi de {ref:.2f}% para {top10:.2f}% "
                       f"(holders {holders:,}) fonte espo.sh")
        ref = None
    if ref is None:
        so["top10_ref"] = top10
    so["holders"], so["top10_pct"] = holders, top10


# ---------------- gatilho (b): runestone ----------------
def leb128(b):
    out, v, s = [], 0, 0
    for c in b:
        v |= (c & 127) << s
        s += 7
        if not c & 128:
            out.append(v)
            v, s = 0, 0
    return out


def runestone(tx):
    """Retorna (edicts, pointer) do OP_RETURN 'OP_13' ou (None, None) se nao houver."""
    for o in tx["vout"]:
        h = o.get("scriptpubkey", "")
        if not h.startswith("6a5d"):
            continue
        b, p = bytes.fromhex(h)[2:], b""
        while b:
            n = b[0]
            if 1 <= n <= 75:
                p += b[1:1 + n]; b = b[1 + n:]
            elif n == 76:
                p += b[2:2 + b[1]]; b = b[2 + b[1]:]
            elif n == 77:
                L = int.from_bytes(b[1:3], "little"); p += b[3:3 + L]; b = b[3 + L:]
            else:
                b = b[1:]
        ints, edicts, ptr, k = leb128(p), [], None, 0
        while k < len(ints):
            if ints[k] == 0:  # corpo: edicts em grupos de 4 (delta bloco, delta tx, valor, saida)
                blk = txi = 0
                r = ints[k + 1:]
                for j in range(0, len(r) - 3, 4):
                    blk += r[j]
                    txi = r[j + 1] if r[j] else txi + r[j + 1]
                    edicts.append(((blk, txi), r[j + 2], r[j + 3]))
                break
            if ints[k] == 22 and k + 1 < len(ints):
                ptr = ints[k + 1]
            k += 2
        return edicts, ptr
    return None, None


def dog_por_saida(tx):
    """DOG (unidades brutas) indicado pelos edicts para cada saida, e a saida 'padrao' que recebe o resto."""
    edicts, ptr = runestone(tx)
    vout = tx["vout"]
    validas = [i for i, o in enumerate(vout) if not o.get("scriptpubkey", "").startswith("6a")]
    amt, incerto = {}, set()
    for rid, valor, saida in edicts or []:  # sem runestone: tudo vai para a 1a saida valida
        if rid != RUNE_ID:
            continue
        alvos = validas if saida == len(vout) else [saida]
        for s in alvos:
            if valor == 0:
                incerto.add(s)
            amt[s] = amt.get(s, 0) + valor
    padrao = ptr if ptr is not None and ptr < len(vout) else (validas[0] if validas else None)
    if padrao is not None:
        incerto.add(padrao)  # o saldo nao alocado vai para ca; so o ordinals.com sabe o total
    return amt, incerto


def dog_ordinals(txid, vout):
    d = get(ORD.format(txid, vout), tentativas=2)
    time.sleep(PAUSA)
    if not d or "runes" not in d:
        return None
    for nome, r in d["runes"].items():
        if nome.replace("•", "") == "DOGGOTOTHEMOON":
            return int(r["amount"])
    return 0


def checar_wallets(wallets, state, alertas):
    lista = {w["address"]: w.get("label", w["address"][:10]) for w in wallets}
    limite_bruto = DOG_LIMITE * 10 ** DIVISIBILIDADE
    agora = time.time()
    vistos = state.setdefault("seen", {})
    ja_alertado = set(state.setdefault("alerted", []))
    todas_saidas = os.environ.get("CHECK_ALL_OUTPUTS", "0") == "1"
    for a, nome in lista.items():
        txs = get(MEMPOOL.format(a))
        time.sleep(PAUSA)
        if txs is None:
            print(f"  {nome}: sem resposta do mempool.space, pulando")
            continue
        seen = vistos.setdefault(a, [])
        novos = 0
        for tx in txs:
            st = tx.get("status", {})
            confirmada = st.get("confirmed", False)
            if tx["txid"] in seen or (confirmada and st.get("block_time", 0) < agora - JANELA_HORAS * 3600):
                continue
            novos += 1
            if confirmada:  # nao-confirmadas sao rechecadas ate confirmar
                seen.append(tx["txid"])
            if not any(v.get("prevout", {}).get("scriptpubkey_address") == a for v in tx.get("vin", [])):
                continue  # so interessa saida (envio) desta carteira
            amt, incerto = dog_por_saida(tx)
            for i, o in enumerate(tx["vout"]):
                dest = o.get("scriptpubkey_address")
                if not dest or dest == a:
                    continue  # troco para si mesma
                para_lista = dest in lista
                if not para_lista and not todas_saidas:
                    continue
                valor, fonte = amt.get(i, 0), "runestone"
                if (para_lista or i in incerto) and confirmada:
                    v2 = dog_ordinals(tx["txid"], i)
                    if v2 is not None:
                        valor, fonte = v2, "ordinals.com"
                chave = f"{tx['txid']}:{i}"
                if valor >= limite_bruto and chave not in ja_alertado:
                    dog = valor / 10 ** DIVISIBILIDADE
                    alvo = lista.get(dest, "carteira fora da lista")
                    alertas.append(f"TRANSFERENCIA {dog:,.0f} DOG de {nome} -> {alvo} ({dest}) "
                                   f"[{fonte}, {'confirmada' if confirmada else 'mempool'}] "
                                   f"https://mempool.space/tx/{tx['txid']}")
                    ja_alertado.add(chave)
        del seen[:-100]
        print(f"  {nome}: {len(txs)} txs lidas, {novos} novas")
    state["alerted"] = sorted(ja_alertado)[-500:]


# ---------------- gatilho (f): carteiras convictas e dormentes ----------------
ORD_ADDR = "https://ordinals.com/address/{}"
CONV_PCT = 5.0                  # alerta se o saldo mudar >= 5% ...
CONV_DOG = 5_000_000            # ... ou >= 5 milhoes de DOG (vs ultimo valor alertado)
GRUPO_MIN = 3                   # >= 3 convictas aumentando em 24h -> ACUMULACAO EM GRUPO


def saldo_dog(addr):
    """Saldo DOG do endereco lendo a pagina HTML do ordinals.com (a API JSON esta desligada)."""
    try:
        req = urllib.request.Request(ORD_ADDR.format(addr), headers={"User-Agent": "dog-alerta/1.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  aviso: ordinals.com falhou ({str(e)[:60]})")
        return None
    if "rune balances" not in html and "outputs" not in html:
        return None  # bloqueio/pagina inesperada
    mt = re.search(r"DOG\u2022GO\u2022TO\u2022THE\u2022MOON</a>:\s*([\d.]+)", html)
    return float(mt.group(1)) if mt else 0.0


def destino_saida(addr, corretoras):
    """Olha as txs recentes (1 chamada ao mempool.space) e diz se algum envio foi para corretora/top1."""
    txs = get(MEMPOOL.format(addr), tentativas=2) or []
    for tx in txs[:10]:
        if not any(v.get("prevout", {}).get("scriptpubkey_address") == addr for v in tx.get("vin", [])):
            continue
        for o in tx["vout"]:
            d = o.get("scriptpubkey_address")
            if d in corretoras:
                return tx["txid"], corretoras[d]
        return tx["txid"], None
    return None, None


def checar_convictas(cfg, state, alertas):
    corretoras = cfg.get("corretoras", {})
    sw = state.setdefault("convictas", {})
    agora = int(time.time())
    for w in cfg.get("convictas", []) + cfg.get("dormentes", []):
        a, nome = w["address"], w["label"]
        dorm = nome.startswith("dormente")
        saldo = saldo_dog(a)
        time.sleep(PAUSA)
        if dorm:
            info = get(f"https://mempool.space/api/address/{a}", tentativas=2) or {}
            ntx = (info.get("chain_stats", {}).get("tx_count", 0) + info.get("mempool_stats", {}).get("tx_count", 0)) if info else None
            stx = sw.setdefault(a, {})
            if ntx is not None:
                if stx.get("ntx") is not None and ntx > stx["ntx"]:
                    alertas.append(f"DESPERTOU: {nome} fez {ntx - stx['ntx']} transacao(oes) nova(s) "
                                   f"depois de muito tempo parada https://mempool.space/address/{a}")
                stx["ntx"] = ntx
        if saldo is None:
            print(f"  {nome}: sem resposta, pulando")
            continue
        st = sw.setdefault(a, {})
        if st.get("ref") is None:
            st["ref"] = w.get("dog_base") if w.get("dog_base") is not None else saldo
        ref = st["ref"]
        dif = saldo - ref
        pct = dif / ref * 100 if ref else (100.0 if dif else 0.0)
        print(f"  {nome}: {saldo:,.2f} DOG | referencia {ref:,.2f} | {dif:+,.2f} ({pct:+.2f}%)")
        st["ultimo"], st["checado_em"] = saldo, agora
        mexeu = abs(dif) >= 1 if dorm else (abs(pct) >= CONV_PCT or abs(dif) >= CONV_DOG)
        if not mexeu:
            continue
        link = f"https://mempool.space/address/{a}"
        if dif > 0:
            tipo = "COMPRA (aumentou)"
            st["aumento_em"] = agora
            extra = ""
        else:
            tipo = "VENDA/SAIDA (diminuiu)"
            txid, dest = destino_saida(a, corretoras)
            if txid:
                link = f"https://mempool.space/tx/{txid}"
            extra = f" - provavel envio para corretora (pressao de venda) [{dest}]" if dest else ""
        cab = "DESPERTOU (dormente mexeu em DOG)" if dorm else "CARTEIRA CONVICTA"
        alertas.append(f"{cab}: {nome} {tipo} {dif:+,.0f} DOG ({pct:+.1f}%), de {ref:,.0f} para "
                       f"{saldo:,.0f} DOG{extra} {link}")
        st["ref"] = saldo
    conv = {w["address"] for w in cfg.get("convictas", [])}
    subiram = [a for a in conv if agora - sw.get(a, {}).get("aumento_em", 0) <= 24 * 3600]
    ult = state.get("grupo_alerta_em", 0)
    if len(subiram) >= GRUPO_MIN and agora - ult > 24 * 3600:
        alertas.append(f"ACUMULACAO EM GRUPO: {len(subiram)} carteiras convictas aumentaram DOG nas ultimas 24h")
        state["grupo_alerta_em"] = agora


def main():
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    antes = json.dumps(state, sort_keys=True)
    alertas, erros = Alertas(), []
    m = {"preco": None, "vol": None, "chg24": None, "btc24": None, "fonte": None}
    cfg = {}

    def etapa(titulo, fn):
        print(titulo)
        try:
            fn()
        except Exception as e:  # erro de checagem NAO e alerta: so aviso
            msg = f"{titulo.strip('= ')}: {type(e).__name__}: {e}"
            print(f"  ERRO (nao e alerta): {msg}")
            erros.append(msg)

    etapa("== (a) Volume 24h ==", lambda: (m.update(mercado()), checar_volume(m, state, alertas)))
    etapa("== (b) Transferencias entre carteiras grandes ==",
          lambda: (cfg.update(json.load(open(os.path.join(AQUI, "wallets.json")))),
                   checar_wallets(cfg["wallets"], state, alertas)))
    etapa("== (c) Movimento de preco ==", lambda: checar_preco(m, state, alertas))
    etapa("== (d) Sinal de entrada / invalidacao ==", lambda: checar_entrada(m, state, alertas))
    etapa("== (e) On-chain leve (espo.sh, opcional) ==", lambda: checar_onchain(state, alertas))
    etapa("== (f) Carteiras convictas e dormentes ==", lambda: checar_convictas(cfg, state, alertas))

    if json.dumps(state, sort_keys=True) != antes:
        with open(STATE, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)

    publicar_github(alertas, erros)
    if alertas:
        texto = "DOG ALERTA (rune 840000:3)\n" + "\n".join(f"- {a}" for a in alertas)
        print("\n" + "!" * 60 + "\n!!! " + texto + "\n" + "!" * 60)
        notificar("\U0001F415 " + texto)
        sys.exit(1)  # 1 = houve alerta (motivos impressos acima)
    print("\nNenhum alerta. Tudo calmo." + (f" ({len(erros)} erro(s) de checagem, ver avisos)" if erros else ""))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    main()
