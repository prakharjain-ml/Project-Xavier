# Jaw-clench confirmation: step by step

Goal: the rider looks at a box (gaze, yellow) and **clenches their jaw to confirm** (green). The clench is a
**muscle signal (EMG)** picked up by the EEG headset, not a brain signal; say so honestly in the pitch. It is
much stronger than EEG, so it works even when the brain signal is weak. Code: `bci/jaw.py` (detector),
`bci/jaw_live.py` (live test). Practice mode already passes without a board: 4 fake clenches -> 4 CONFIRMs.

## Step 1. Connect the board so it does not drop out
**Most reliable: the USB dongle, not the Wi-Fi shield.** Wi-Fi shields are known to drop sessions.
1. Board off. Remove the Wi-Fi shield. Plug the **USB dongle** into the laptop (through the hub is fine).
2. Board switch to **PC**, then on. Dongle switch to **GPIO 6** (the side away from the USB plug), if it has one.
3. Find the port: `ls /dev/cu.usbserial-*` (the OpenBCI dongle looks like `/dev/cu.usbserial-DM0xxxxx`).
4. The dongle runs at 250 Hz. The jaw detector works at 250 Hz (tested).

**If you must use the Wi-Fi shield** (it streams at 1000 Hz):
- A **blinking blue light usually means it is not connected yet** (still waiting / searching). Solid means it is.
- **Battery first:** the shield draws a lot of power; a weak battery causes exactly "works, then stops". Use a
  fully charged battery or a USB power bank.
- **Stop the laptop hopping networks:** System Settings -> Wi-Fi -> turn **Auto-Join off** for the venue network
  (and any hotspot) while testing, so macOS does not leave `OpenBCI-xxxx` mid-session.
- Keep the board **within 1-2 m of the laptop**, nothing metal in between.
- In the OpenBCI GUI, lower the sample rate to **250 or 500 Hz** (less data to drop).
- Allow Python through the firewall if macOS asks ("accept incoming connections" -> Allow).

## Step 2. Electrodes (the board must not be "RAILED")
Our last recording was pinned at +-187,500 uV on every channel: that is an amplifier overload, almost always
the **ear clips**. Any channel sees jaw EMG, so O1/O2 are fine.
1. **Reference** clip on the left earlobe -> **bottom SRB pin**. **Ground** clip on the right earlobe -> **bottom BIAS pin**.
2. Wipe earlobes with alcohol, a little gel, clip firmly. One wire per pin.
3. O1 -> N1P, O2 -> N2P. Part the hair, enough gel, press each electrode down.

## Step 3. Check the signal in the OpenBCI GUI (2 min)
1. Hardware Settings -> **Load default settings**; channels 1-2: SRB2 **On**, BIAS **Include**; channels 3-8 **off**.
2. Time Series: channels 1-2 wiggle a little, **no red "RAILED"**.
3. **Clench your jaw**: channels 1-2 must show a big burst of fast wiggles. Relax: it disappears.
4. If there is no burst, fix Step 2 first. Then **quit the GUI (Cmd+Q)**; only one program can use the board.

## Step 4. Run the live jaw test (3 min)
```bash
cd "/Users/prakharjain/HP Auto WheelChair" && source ~/venvs/hp26/bin/activate
python -m bci.jaw_live --dongle /dev/cu.usbserial-DM0xxxxx    # or: --wifi
```
1. **Relax 10 s**: jaw loose, teeth apart, do not talk.
2. **3 clenches** when it says CLENCH (hold ~1 s each).
3. If it prints `CALIBRATION FAILED: clench only 1.4x relaxed`, contact is too poor: back to Step 2.
4. **Live (60 s)**: clench, and it prints `CONFIRM #n`.

**Pass criteria (write the numbers in PROGRESS.md):**
| Test | Do | Must see |
| --- | --- | --- |
| Hits | 10 clenches, ~1 s each, 3 s apart | 9-10 CONFIRMs |
| No false confirms | 30 s talking, blinking, looking around | 0 CONFIRMs |
| Hold | hold one clench 5 s | exactly 1 CONFIRM |

## Step 5. Plug it into object selection (next code step)
`vision/object_select.py` already turns the looked-at box yellow; today a 1.5 s gaze dwell confirms it. Next:
a confirmation source that is **the jaw clench when the board is connected, and SPACE on the keyboard as a
stand-in until then** (so the whole flow can be rehearsed today). The 1.5 s dwell stays as the fallback.

## Troubleshooting
| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Stream stops after a while (Wi-Fi) | weak battery / laptop left the network | charge battery; Auto-Join off; or use the dongle |
| Every channel RAILED, all channels identical | reference/ground ear clip | Step 2; try swapping the clip cable |
| `CALIBRATION FAILED` | poor contact, or not clenching hard enough | more gel; clench harder; re-run |
| CONFIRM while talking | threshold too low for this rider | re-calibrate with firmer clenches |
| `unable to prepare streaming session` | GUI still open / wrong network / wrong port | Cmd+Q the GUI; check Wi-Fi network or `ls /dev/cu.usbserial-*` |
