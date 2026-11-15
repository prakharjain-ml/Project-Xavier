"""
analyze_gui_recording.py  -  Check for an SSVEP peak in a recording saved by the OpenBCI GUI.

RECORDING PROTOCOL (one continuous data stream in the GUI):
    1. Start Data Stream. Look at the screen with NO flicker for REST seconds (default 20).
    2. Then stare at the flicker box for FLICKER seconds (default 20).
    3. Stop Data Stream.

    python analyze_gui_recording.py <path to OpenBCI-RAW-....txt> 12
    python analyze_gui_recording.py <file> 12 --rest 20 --flicker 20 --skip 5

    --skip  seconds to ignore at the very start (settling, clicking buttons). Default 5.

The GUI usually saves recordings in Documents/OpenBCI_GUI/Recordings/.
Needs bci_check.py and record_and_plot.py in the same folder.
"""

import argparse
import csv
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import welch
import bci_check as bc
from record_and_plot import snr_at


def load_gui_file(path):
    """Read an OpenBCI GUI raw file: header lines start with '%', then a CSV with column names."""
    fs = None
    rows, header = [], None
    with open(path) as f:
        for line in f:
            if line.startswith("%"):
                if "Sample Rate" in line:
                    fs = float(line.split("=")[1].strip().split()[0])
                continue
            if header is None:
                header = [h.strip() for h in line.split(",")]
                continue
            rows.append(line)
    data = list(csv.reader(rows))
    cols = {name: i for i, name in enumerate(header)}
    exg = [c for c in header if c.startswith("EXG Channel")]
    if fs is None or not exg:
        raise SystemExit(f"Couldn't find the sample rate or EXG columns. Columns found: {header}")
    o1 = np.array([float(r[cols[exg[bc.O1_INDEX]]]) for r in data])
    o2 = np.array([float(r[cols[exg[bc.O2_INDEX]]]) for r in data])
    return fs, o1, o2


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("target_hz", type=float)
    p.add_argument("--rest", type=float, default=20)
    p.add_argument("--flicker", type=float, default=20)
    p.add_argument("--skip", type=float, default=5)
    a = p.parse_args()

    fs, o1, o2 = load_gui_file(a.file)
    total = len(o1) / fs
    print(f"Loaded {total:.1f} s of data at {fs:.0f} Hz")
    s0 = int(a.skip * fs)
    s1 = int((a.skip + a.rest) * fs)
    s2 = int((a.skip + a.rest + a.flicker) * fs)
    if s2 > len(o1):
        raise SystemExit(f"Recording is only {total:.1f} s long; need {a.skip + a.rest + a.flicker:.0f} s. Adjust --rest/--flicker/--skip.")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    f0, f2 = a.target_hz, 2 * a.target_hz
    print(f"\n{'Channel':<8}{'Segment':<9}{'SNR @ ' + str(f0):<14}{'SNR @ ' + str(f2)}")
    for ax, name, sig in zip(axes, ["O1", "O2"], [o1, o2]):
        for seg, (lo, hi), color in [("rest", (s0, s1), "gray"), ("flicker", (s1, s2), "tab:red")]:
            x = bc.clean(sig[lo:hi], fs)
            freqs, psd = welch(x, fs=fs, nperseg=int(fs * 4))
            keep = (freqs >= 3) & (freqs <= 40)
            ax.semilogy(freqs[keep], psd[keep], color=color, label=seg)
            print(f"{name:<8}{seg:<9}{snr_at(freqs, psd, f0):<14.2f}{snr_at(freqs, psd, f2):.2f}")
        ax.axvline(f0, color="tab:blue", linestyle="--", alpha=0.6)
        ax.axvline(f2, color="tab:blue", linestyle=":", alpha=0.6)
        ax.set_title(f"{name}: red peak on the dashed line = SSVEP at {f0} Hz")
        ax.set_xlabel("Frequency (Hz)")
        ax.legend()
    axes[0].set_ylabel("Power (log scale)")
    plt.tight_layout()
    out = a.file.rsplit(".", 1)[0] + f"_ssvep_{f0}Hz.png"
    plt.savefig(out, dpi=120)
    print(f"\nPlot saved to {out}")
    print("SNR ~1 = nothing. SNR above ~2 during FLICKER (and ~1 during REST) = SSVEP detected.")
    plt.show()


if __name__ == "__main__":
    main()