# -*- coding: utf-8 -*-
"""RIGOL DG800 Pro / DG900 Pro(任意波形発生器)を操作する MCP サーバー。

つなぎ方は **LAN(SCPI over TCP、5555番)**。Windows でも追加のドライバが要らない。
USB でも繋がるが、USB-TMC のドライバを当てる作業(Zadig など)が別途要る。

出所: RIGOL 公式 DG800 Pro/DG900 Pro Programming Guide
https://download.rigol.com/en/Manual/Waveform%20Generator/DG900%20Pro/DG800ProDG900Pro_ProgrammingGuide_EN.pdf
"""
import json
import os
import re
import socket
import threading

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rigol-dg900")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")

DEFAULT_PORT = 5555
TIMEOUT = 3.0
MODEL_TAG = "DG"                 # *IDN? にこれが入っていなければ相手が違う
MAX_VPP = 10.0                   # 高インピーダンス時の上限(公式仕様)
CONFIRM_ABOVE_VPP = 5.0          # これを超える指示は確認値を要求する

_lock = threading.Lock()


# ---------------------------------------------------------------- 接続先

def _load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def _host():
    h = os.environ.get("DG_HOST") or _load_state().get("host")
    if not h:
        raise RuntimeError(
            "接続先が決まっていない。\n"
            "  機器の画面で Utility → I/O → LAN を開き、IPアドレスを読む。\n"
            "  その値を dg_set_host で登録するか、環境変数 DG_HOST に入れる。")
    return h


def _port():
    return int(os.environ.get("DG_PORT") or _load_state().get("port") or DEFAULT_PORT)


# ---------------------------------------------------------------- 通信

class Dg:
    """**1回のやりとりごとに**繋いで閉じる。

    ⚠ 道具の呼び出し全体で接続を握ってはいけない。MCP の呼び出しは直列に
      処理されるので、長く握ると「出力を切る」が待たされて緊急停止に使えなくなる。
      (OWON SPE6103 の MCP で実測した失敗を踏まえている)
    """

    def __init__(self, host=None, port=None):
        self.host = host or _host()
        self.port = port or _port()

    def _txn(self, fn):
        with _lock:
            s = socket.create_connection((self.host, self.port), timeout=TIMEOUT)
            try:
                s.settimeout(TIMEOUT)
                return fn(s)
            finally:
                try:
                    s.close()
                except Exception:
                    pass

    @staticmethod
    def _readline(s):
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf.decode("utf-8", "replace").strip()

    def q(self, cmd):
        """問い合わせて1行返す。"""
        def go(s):
            s.sendall((cmd + "\n").encode())
            return self._readline(s)
        return self._txn(go)

    def w(self, cmd):
        """投げるだけ(返事の無い命令)。"""
        def go(s):
            s.sendall((cmd + "\n").encode())
            return ""
        return self._txn(go)

    def idn(self):
        v = self.q("*IDN?")
        if MODEL_TAG not in v.upper():
            raise RuntimeError(
                "相手が DG シリーズではない。名乗り: %r\n"
                "  ⚠ IPアドレスだけで決めてはいけない。必ず *IDN? を確かめること。" % v)
        return v


def _ch(n):
    n = int(n)
    if n not in (1, 2):
        raise ValueError("チャンネルは 1 か 2")
    return n


# ---------------------------------------------------------------- 道具

@mcp.tool()
def dg_set_host(host: str, port: int = DEFAULT_PORT) -> str:
    """接続先の IP アドレスを登録する(読むだけ・信号は出ない)。

    機器の画面で Utility → I/O → LAN を開くと IP アドレスが出る。
    登録すると同じフォルダの state.json に残るので、次回から指定は要らない。

    Args:
        host: 機器の IP アドレス(例 192.168.1.50)
        port: SCPI の待ち受け番号。既定 5555
    """
    d = Dg(host, port)
    name = d.idn()
    st = _load_state()
    st["host"] = host
    st["port"] = int(port)
    _save_state(st)
    return "登録した\n接続先: %s:%d\n名乗り: %s" % (host, port, name)


@mcp.tool()
def dg_status() -> str:
    """いまの様子をまとめて返す(読むだけ・機器の状態は変えない)。

    機種名、各チャンネルの波形と設定値、出力の入切、出力インピーダンスを返す。
    """
    d = Dg()
    out = ["機種      : %s" % d.idn(),
           "接続先    : %s:%d" % (d.host, d.port)]
    for n in (1, 2):
        try:
            apply_ = d.q(":SOURce%d:APPLy?" % n)
            state = d.q(":OUTPut%d:STATe?" % n)
            load = d.q(":OUTPut%d:LOAD?" % n)
            out.append("CH%d 波形  : %s" % (n, apply_))
            out.append("CH%d 出力  : %s" % (n, "ON  ← 信号が出ている" if state.strip() in ("ON", "1") else "OFF"))
            out.append("CH%d 負荷  : %s %s" % (
                n, load,
                "(50Ω設定。高インピーダンスの相手につなぐと**実際の振幅は2倍**になる)"
                if load.strip().replace(".0", "") == "50" else ""))
        except Exception as e:
            out.append("CH%d      : 読めない (%s)" % (n, e))
    return "\n".join(out)


@mcp.tool()
def dg_set_load(ch: int, ohms: str = "INF") -> str:
    """出力インピーダンス(相手の負荷)を設定する。信号の入切は変えない。

    ⚠ **ここが一番の落とし穴。** 機器は「設定した負荷につないだときに指示どおりの
      振幅になる」ように出力する。既定の 50Ω のまま、入力インピーダンスの高い相手
      (マイコンの足など)につなぐと、**実際に出る振幅は指示の2倍**になる。
      3.3V のつもりが 6.6V になって相手を壊す。
      マイコンや計測器につなぐときは必ず "INF"(高インピーダンス)にすること。

    Args:
        ch: チャンネル 1 か 2
        ohms: "INF"(高インピーダンス) または 1〜10000 の数値(Ω)
    """
    n = _ch(ch)
    v = str(ohms).strip().upper()
    if v in ("INF", "INFINITY", "HIGHZ", "HIZ"):
        arg = "INFinity"
    else:
        f = float(v)
        if not (1.0 <= f <= 10000.0):
            raise ValueError("負荷は 1〜10000 Ω か INF")
        arg = "%g" % f
    d = Dg()
    d.idn()
    d.w(":OUTPut%d:LOAD %s" % (n, arg))
    return "CH%d の負荷を %s にした\n読み戻し: %s" % (n, arg, d.q(":OUTPut%d:LOAD?" % n))


@mcp.tool()
def dg_apply(ch: int, shape: str, freq_hz: float, amplitude_vpp: float,
             offset_v: float = 0.0, phase_deg: float = 0.0,
             expect_vpp: float = None) -> str:
    """波形と設定値を決める。**出力の入切は変えない**(このままでは信号は出ない)。

    値を決めてから dg_output_on で出す、という順序を守れる作りにしてある。

    ⚠ 実際に相手に届く電圧は、出力インピーダンスの設定(dg_set_load)で変わる。
      50Ω 設定のまま高インピーダンスの相手につなぐと**2倍**になる。

    Args:
        ch: チャンネル 1 か 2
        shape: SIN / SQU / RAMP / PULS / NOIS / DC のどれか
        freq_hz: 周波数(Hz)
        amplitude_vpp: 振幅(Vpp)。0〜10
        offset_v: 直流の下駄(V)
        phase_deg: 位相(度)
        expect_vpp: 5Vpp を超える指示のときは、ここに同じ値を渡さないと実行しない
    """
    n = _ch(ch)
    m = {"SIN": "SINusoid", "SQU": "SQUare", "RAMP": "RAMP",
         "PULS": "PULSe", "NOIS": "NOISe", "DC": "DC"}
    key = str(shape).strip().upper()[:4]
    if key not in m:
        raise ValueError("shape は SIN / SQU / RAMP / PULS / NOIS / DC のどれか")
    a = float(amplitude_vpp)
    if not (0.0 <= a <= MAX_VPP):
        raise ValueError("振幅は 0〜%g Vpp" % MAX_VPP)
    if a > CONFIRM_ABOVE_VPP:
        if expect_vpp is None or abs(float(expect_vpp) - a) > 1e-9:
            raise ValueError(
                "%g Vpp は大きい。壊す恐れがあるので、expect_vpp に同じ値を渡すこと" % a)
    d = Dg()
    d.idn()
    d.w(":SOURce%d:APPLy:%s %g,%g,%g,%g" % (n, m[key], float(freq_hz), a,
                                            float(offset_v), float(phase_deg)))
    load = d.q(":OUTPut%d:LOAD?" % n)
    warn = ""
    if load.strip().replace(".0", "") == "50":
        warn = ("\n⚠ 負荷が 50Ω のまま。高インピーダンスの相手につなぐと"
                "**実際は %g Vpp** が出る。dg_set_load(ch, \"INF\") を先に呼ぶこと" % (a * 2))
    return ("設定した(出力はまだ入れていない)\nCH%d: %s\n負荷: %s%s"
            % (n, d.q(":SOURce%d:APPLy?" % n), load, warn))


@mcp.tool()
def dg_logic_pulse(ch: int, freq_hz: float, high_v: float = 3.3,
                   duty_percent: float = 50.0) -> str:
    """マイコンの足に入れても安全な、0V〜指定電圧 の方形波を作る(出力はまだ入れない)。

    負荷を自動で高インピーダンスにしてから設定するので、
    「50Ω のまま倍の電圧が出る」事故が起きない。

    Args:
        ch: チャンネル 1 か 2
        freq_hz: 周波数(Hz)
        high_v: 高いときの電圧(V)。既定 3.3。5V を超える指示は断る
        duty_percent: 高い時間の割合(%)
    """
    n = _ch(ch)
    hv = float(high_v)
    if not (0.1 <= hv <= 5.0):
        raise ValueError("high_v は 0.1〜5.0 V。それ以上は dg_apply を使うこと")
    d = Dg()
    d.idn()
    d.w(":OUTPut%d:LOAD INFinity" % n)          # 先に高インピーダンスへ
    d.w(":SOURce%d:APPLy:SQUare %g,%g,%g,0" % (n, float(freq_hz), hv, hv / 2.0))
    d.w(":SOURce%d:FUNCtion:SQUare:DCYCle %g" % (n, float(duty_percent)))
    return ("設定した(出力はまだ入れていない)\n"
            "CH%d: 0V 〜 %.2fV の方形波 %g Hz、デューティ %g%%\n"
            "負荷: %s\n読み戻し: %s"
            % (n, hv, float(freq_hz), float(duty_percent),
               d.q(":OUTPut%d:LOAD?" % n), d.q(":SOURce%d:APPLy?" % n)))


@mcp.tool()
def dg_output_on(ch: int, expect_vpp: float = None) -> str:
    """【実際に信号が出る】指定したチャンネルの出力を入れる。

    繋ぎ先・振幅・負荷の設定を必ず先に確かめてから使うこと。
    迷ったら実行せず、利用者に確認を取ること。

    ⚠ 出てくるのは「いま機器に入っている設定」であって、この会話で決めた値とは限らない。
      前の作業の値が残っていることがある。**振幅が %g Vpp を超えているときは、
      expect_vpp に「出るはずの振幅」を渡さないと実行しない。**

    Args:
        ch: チャンネル 1 か 2
        expect_vpp: 出るはずだと思っている振幅(Vpp)。食い違えば実行しない
    """ % CONFIRM_ABOVE_VPP
    n = _ch(ch)
    d = Dg()
    d.idn()
    cur = d.q(":SOURce%d:APPLy?" % n)
    load = d.q(":OUTPut%d:LOAD?" % n)
    amp = None
    m = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cur)
    if len(m) >= 2:
        try:
            amp = float(m[1])
        except Exception:
            amp = None
    if amp is not None and amp > CONFIRM_ABOVE_VPP:
        if expect_vpp is None or abs(float(expect_vpp) - amp) > 1e-6:
            raise ValueError(
                "いまの設定は %g Vpp。%g Vpp を超えるので、expect_vpp に同じ値を渡すこと。\n"
                "  現在の設定: %s" % (amp, CONFIRM_ABOVE_VPP, cur))
    d.w(":OUTPut%d:STATe ON" % n)
    warn = ""
    if load.strip().replace(".0", "") == "50" and amp:
        warn = "\n⚠ 負荷 50Ω。高インピーダンスの相手なら実際は約 %g Vpp が出ている" % (amp * 2)
    return ("CH%d の出力を入れた\n設定: %s\n負荷: %s\n出力: %s%s"
            % (n, cur, load, d.q(":OUTPut%d:STATe?" % n), warn))


@mcp.tool()
def dg_output_off(ch: int = 0) -> str:
    """出力を切る(安全側の操作)。設定値は消えない。

    Args:
        ch: 1 か 2。0 なら両方切る
    """
    d = Dg()
    d.idn()
    targets = (1, 2) if int(ch) == 0 else (_ch(ch),)
    out = []
    for n in targets:
        d.w(":OUTPut%d:STATe OFF" % n)
        out.append("CH%d: %s" % (n, d.q(":OUTPut%d:STATe?" % n)))
    return "出力を切った\n" + "\n".join(out)


@mcp.tool()
def dg_counter(enable: bool = True, seconds: float = 0.0) -> str:
    """内蔵の周波数計で、外から入れた信号の周波数を測る(信号は出さない)。

    ⚠ 周波数計の入口は出力とは別の端子。取り違えないこと。
    ⚠ 周期的でない信号(通信データなど)の周波数を測っても意味のある値は出ない。

    Args:
        enable: True で周波数計を動かす。False で止める
        seconds: 0 より大きいと、その秒数だけ待ってから読む
    """
    import time
    d = Dg()
    d.idn()
    if not enable:
        d.w(":COUNter:STATe OFF")
        return "周波数計を止めた"
    d.w(":COUNter:STATe ON")
    if seconds and seconds > 0:
        time.sleep(min(float(seconds), 10.0))
    vals = {}
    for name, cmd in (("周波数", ":COUNter:MEASure:FREQuency?"),
                      ("周期", ":COUNter:MEASure:PERiod?"),
                      ("デューティ", ":COUNter:MEASure:DUTYcycle?")):
        try:
            vals[name] = d.q(cmd)
        except Exception as e:
            vals[name] = "読めない (%s)" % e
    return "周波数計\n" + "\n".join("  %s: %s" % (k, v) for k, v in vals.items())


@mcp.tool()
def dg_query(command: str) -> str:
    """任意の SCPI の**問い合わせ**を投げる(読むだけ)。

    末尾が `?` の命令だけを受け付ける。機器の状態を変える命令は実行しない。
    公式のプログラミングガイドに載っていない項目を確かめたいときの逃げ道。

    Args:
        command: 例 ":SOURce1:FREQuency?"
    """
    c = str(command).strip()
    if not c.endswith("?"):
        raise ValueError("問い合わせ(末尾が ? )だけを受け付ける。"
                         "状態を変える命令はこの道具では実行しない")
    d = Dg()
    d.idn()
    return "%s\n→ %s" % (c, d.q(c))


if __name__ == "__main__":
    mcp.run()
