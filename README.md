# rigol-dg900-mcp

An MCP server that lets an AI assistant drive a **RIGOL DG800 Pro / DG900 Pro**
function / arbitrary waveform generator over **LAN (raw SCPI on TCP 5555)**.

> ### This is a signal source, not an oscilloscope
>
> The DG800/DG900 family **generates** waveforms. It cannot measure a signal, capture it,
> or display it. If you are looking for a way to look at a waveform, this is the wrong
> instrument and the wrong repository — you want a scope (Rigol's DS/MSO lines).
>
> The one measuring feature it does have is a **frequency counter** on a separate input
> (`dg_counter`), and that only reports frequency / period / duty of a *periodic* signal.
> It will not tell you anything useful about, say, serial data.
>
> The `DG` prefix is easy to mistake for a scope model. It is not one.

```
*IDN?  ->  RIGOL TECHNOLOGIES,DG902 Pro,DG9P281200133,...
```

## Why LAN and not USB

The DG900 Pro exposes both USB (USB-TMC) and LAN. On Windows the USB path needs a
USB-TMC driver bound to the device — without one it sits at `CM_PROB_FAILED_INSTALL`
and neither libusb nor PyVISA can see it. Binding WinUSB means Zadig, admin rights and
a system change.

LAN needs none of that: it is a plain TCP socket carrying SCPI lines. No driver, no
admin, no vendor runtime. That is the only transport this server implements.

To find the address: on the instrument, **Utility → I/O → LAN**.

## Tools

| Tool | What it does |
|---|---|
| `dg_set_host(host, port)` | Register the instrument's IP. Verifies `*IDN?` and stores it. |
| `dg_status` | Model, per-channel waveform, output state, output load. Read only. |
| `dg_set_load(ch, ohms)` | Output impedance. `"INF"` for high-Z. **Read the gotcha below.** |
| `dg_apply(ch, shape, freq, vpp, offset, phase)` | Set the waveform. **Does not enable the output.** |
| `dg_logic_pulse(ch, freq, high_v, duty)` | Safe helper: 0 V → `high_v` square wave, forces high-Z first. |
| `dg_output_on(ch)` | **Actually emits a signal.** |
| `dg_output_off(ch)` | Turns the output off. `ch=0` for both. |
| `dg_counter(enable, seconds)` | Built-in frequency counter. |
| `dg_query(command)` | Arbitrary SCPI **query** (must end in `?`). Read only. |

### Safety design

- `dg_apply` never turns the output on. You set values first, then energise — in that order.
- Anything above **10 Vpp** is rejected before it reaches the instrument.
- Above **5 Vpp** you must pass `expect_vpp` matching the value, so a leftover setting
  from earlier work cannot be emitted by accident.
- `dg_output_on` re-reads the *instrument's* current setting, not the conversation's, and
  refuses if it exceeds 5 Vpp without confirmation.
- `dg_query` refuses anything that is not a query.
- The socket is opened and closed per call, so a long call cannot block "turn the output off".

This does **not** replace a physical means of disconnecting the instrument.

## The gotcha that will destroy something

**Output impedance defaults to 50 Ω, and the instrument compensates for it.**

The generator sets its internal source so that the *configured load* sees the amplitude you
asked for. Ask for 3.3 Vpp with the load set to 50 Ω, then connect a high-impedance input —
a microcontroller pin, a scope probe, a logic input — and **the pin actually sees 6.6 Vpp**.

That is how you put 6.6 V into a 3.3 V pin.

Always set the load to high impedance before driving logic:

```
dg_set_load(1, "INF")
```

`dg_status` and `dg_apply` both warn when the load is still 50 Ω, and print what the real
amplitude would be. `dg_logic_pulse` forces high-Z before it sets anything, which is why it
exists.

## Requirements

- Python 3.10+
- `mcp` (the official Python SDK; `FastMCP` ships inside it)

No PyVISA, no libusb, no vendor runtime. Only the standard library plus `mcp`.

```
pip install mcp
```

## Install

```
claude mcp add --scope user dg900 -- python /path/to/server.py
```

Then restart your client so the tools appear.

Set the address once:

```
dg_set_host("192.168.1.50")
```

It is stored in `state.json` next to the server. `DG_HOST` / `DG_PORT` environment
variables take precedence if set.

## SCPI used

From the official RIGOL programming guide
([DG800 Pro/DG900 Pro Programming Guide](https://download.rigol.com/en/Manual/Waveform%20Generator/DG900%20Pro/DG800ProDG900Pro_ProgrammingGuide_EN.pdf)):

| Command | Meaning |
|---|---|
| `*IDN?` | Identify |
| `[:SOURce[<n>]]:APPLy:{SINusoid\|SQUare\|RAMP\|PULSe\|NOISe\|DC} <freq>,<amp>,<offset>,<phase>` | Set waveform |
| `[:SOURce[<n>]]:APPLy?` | Query waveform |
| `:OUTPut[<n>][:STATe] <state>` | Output on/off |
| `:OUTPut[<n>]:LOAD {<ohms>\|INFinity}` | Output impedance |
| `[:SOURce[<n>]]:FUNCtion:SQUare:DCYCle <percent>` | Square duty cycle |
| `:COUNter[:STATe] <bool>` | Frequency counter on/off |
| `:COUNter:MEASure:{FREQuency\|PERiod\|DUTYcycle}?` | Counter readings |

## Status

Written against the official programming guide. **The LAN transport and the tool logic have
not yet been exercised against the instrument** — the unit this was written for was connected
by USB only. Verified behaviour will be recorded here once it has been run on hardware.

---

# 日本語

**RIGOL DG800 Pro / DG900 Pro**(任意波形発生器)を **LAN 経由(SCPI over TCP、5555番)** で
操作するための MCP サーバーです。

> ### これは信号を「出す」機械です。オシロスコープではありません
>
> DG800/DG900 系は**波形を作って出す**機械です。信号を測ることも、取り込むことも、
> 画面に出すこともできません。**波形を見たいのなら、機種もこのリポジトリも違います**
> (見るための機械は Rigol なら DS / MSO 系)。
>
> 唯一の測る機能は、別の端子に付いている**周波数計**(`dg_counter`)だけです。
> しかもこれは**繰り返しのある信号**の周波数・周期・デューティしか出しません。
> 通信のデータのような、繰り返しでない信号を測っても意味のある値は出ません。
>
> **`DG` という型名はオシロの型番と取り違えやすい**ので、念のため書いておきます。

## なぜ USB ではなく LAN か

この機種は USB と LAN の両方を持っています。ただし **Windows で USB を使うには
USB-TMC のドライバを機器に割り当てる作業が要ります**。割り当てないと機器は
`CM_PROB_FAILED_INSTALL` のまま止まり、libusb からも PyVISA からも見えません。
割り当てには Zadig のような道具と管理者権限、つまり環境を変える作業が要ります。

LAN なら何も要りません。**ただの TCP の口に SCPI の文字列を流すだけ**です。
ドライバも管理者権限もメーカー製の常駐ソフトも不要。この実装は LAN だけを使います。

アドレスの調べ方: 機器の画面で **Utility → I/O → LAN**。

## 道具

| 道具 | 内容 |
|---|---|
| `dg_set_host(host, port)` | 接続先の IP を登録する。`*IDN?` で相手を確かめてから保存する |
| `dg_status` | 機種・各チャンネルの波形・出力の入切・負荷。読むだけ |
| `dg_set_load(ch, ohms)` | 出力インピーダンス。`"INF"` で高インピーダンス。**下の落とし穴を読むこと** |
| `dg_apply(ch, shape, freq, vpp, offset, phase)` | 波形を決める。**出力は入れない** |
| `dg_logic_pulse(ch, freq, high_v, duty)` | 0V〜指定電圧の方形波。**先に高インピーダンスへ強制する**安全版 |
| `dg_output_on(ch)` | **実際に信号が出る** |
| `dg_output_off(ch)` | 出力を切る。`ch=0` で両方 |
| `dg_counter(enable, seconds)` | 内蔵の周波数計で測る |
| `dg_query(command)` | 任意の SCPI の**問い合わせ**(末尾が `?` のものだけ)。読むだけ |

## 安全のきまり

- `dg_apply` は出力を入れない。**値を決めてから入れる、という順序**を守れる
- **10Vpp を超える指示は、機器に送る前に断る**
- **5Vpp を超えるときは `expect_vpp` に同じ値を渡さないと実行しない。**
  前の作業の設定が残っていて、意図しない振幅が出る事故を防ぐ
- `dg_output_on` は会話の値ではなく**機器に入っている設定を読み直して**判断する
- `dg_query` は問い合わせ以外を受け付けない
- 接続は呼び出しごとに開閉する。長く握って「出力を切る」が待たされる事態を作らない

**これは機器を物理的に切り離す手段の代わりにはなりません。**

## 何かを壊す落とし穴

**出力インピーダンスの初期値は 50Ω で、機器はそれを見込んだ電圧を出します。**

機器は「**設定した負荷につないだときに**指示どおりの振幅になる」ように出力します。
負荷が 50Ω のまま 3.3Vpp を指示して、**入力インピーダンスの高い相手**
(マイコンの足、計測器の入口、論理回路の入力)につなぐと、
**相手には 6.6Vpp が届きます**。

3.3V の足に 6.6V を入れる、というのはこうして起きます。

論理回路を叩く前に、必ず高インピーダンスにしてください。

```
dg_set_load(1, "INF")
```

`dg_status` と `dg_apply` は、負荷が 50Ω のままなら**実際に出る振幅**を添えて警告します。
`dg_logic_pulse` が存在するのは、この事故を構造的に防ぐためです
(設定の前に高インピーダンスへ強制する)。

## 必要なもの

- Python 3.10 以上
- `mcp`(公式の Python SDK。`FastMCP` はこの中に入っている)

PyVISA も libusb もメーカーの常駐ソフトも要りません。標準ライブラリと `mcp` だけです。

## 使えるようにする

```
claude mcp add --scope user dg900 -- python /path/to/server.py
```

登録したら、道具が現れるように利用側を起動し直します。アドレスは一度登録すれば残ります。

```
dg_set_host("192.168.1.50")
```

`state.json` に保存されます。環境変数 `DG_HOST` / `DG_PORT` があればそちらが優先されます。

## いまの状態

**公式のプログラミングガイドに沿って書きましたが、実機での動作確認はまだです。**
書いた時点で手元の個体は USB でしか繋がっておらず、LAN の口を使えませんでした。
実機で確かめたことは、確かめ次第ここに書き足します。

## ライセンス

MIT
