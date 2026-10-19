#!/usr/bin/env python3
"""DOG Alerta - monitor gratuito da rune DOG•GO•TO•THE•MOON (ID 840000:3).
Usa somente a biblioteca padrao do Python. Sem chaves pagas. Sai com codigo 1 quando ha alerta."""
import json, os, sys, time, urllib.request

VOL_LIMITE_USD = 1_500_000      # gatilho (a): volume 24h acima disto
DOG_LIMITE = 50_000_000         # gatilho (b): transferencia >= isto (em DOG)
DIVISIBILIDADE = 5              # DOG tem 5 casas decimais
RUNE_ID = (840000, 3)
JANELA_HORAS = 24               # so olha txs das ultimas ~24h (ou novas desde o ultimo state)
REALERTA_VOL_HORAS = 24         # repete alerta de volume no maximo 1x a cada 24h
PAUSA = 1.5                     # segundos entre chamadas (gentil com os limites)
CG = "https://api.coingecko.com/api/v3/simple/price?ids=dog-go-to-the-moon-rune&vs_currencies=usd&include_24hr_vol=true"
KRAKEN = "https://api.kraken.com/0/public/Ticker?pair=DOGUSD"
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


# ---------------- gatilho (a): volume ----------------
def volume_24h():
    d = get(CG)
    try:
        v = d["dog-go-to-the-moon-rune"]
        return float(v["usd_24h_vol"]), float(v["usd"]), "CoinGecko"
    except Exception:
        print("  CoinGecko indisponivel; usando Kraken (so uma corretora, volume menor)")
    d = get(KRAKEN)
    try:
        t = list(d["result"].values())[0]
        return float(t["v"][1]) * float(t["p"][1]), float(t["c"][0]), "Kraken DOGUSD"
    except Exception:
        return None, None, None


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


def main():
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    antes = json.dumps(state, sort_keys=True)
    alertas = []

    print("== (a) Volume 24h ==")
    vol, preco, fonte = volume_24h()
    if vol is None:
        print("  ERRO: nao foi possivel obter o volume (CoinGecko e Kraken falharam)")
    else:
        print(f"  Volume 24h: US$ {vol:,.0f} | preco US$ {preco:.6f} | fonte {fonte} | limite US$ {VOL_LIMITE_USD:,}")
        sv = state.setdefault("vol", {"above": False, "last_alert": 0})
        if vol > VOL_LIMITE_USD:
            if not sv["above"] or time.time() - sv["last_alert"] > REALERTA_VOL_HORAS * 3600:
                alertas.append(f"VOLUME 24h do DOG = US$ {vol:,.0f} (> US$ {VOL_LIMITE_USD:,}) fonte {fonte}")
                sv["last_alert"] = int(time.time())
            else:
                print("  (acima do limite, mas ja alertado nas ultimas 24h)")
        sv["above"] = vol > VOL_LIMITE_USD

    print("== (b) Transferencias entre carteiras grandes ==")
    wallets = json.load(open(os.path.join(AQUI, "wallets.json")))["wallets"]
    checar_wallets(wallets, state, alertas)

    if json.dumps(state, sort_keys=True) != antes:
        with open(STATE, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)

    if alertas:
        texto = "🐕 DOG ALERTA (rune 840000:3)\n" + "\n".join(alertas)
        print("\n" + "!" * 60 + "\n" + texto + "\n" + "!" * 60)
        notificar(texto)
        sys.exit(1)  # falha de proposito -> GitHub manda e-mail
    print("\nNenhum alerta. Tudo calmo.")


if __name__ == "__main__":
    main()
