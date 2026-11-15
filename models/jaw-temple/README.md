# Jaw–temple EMG clench detector

The demo uses a Cyton WiFi board at 1000 Hz with CH1 on the jaw and CH2 on the temple. The standalone detector prints a clench state, model score and jaw-minus-temple amplitude every half second. Its first prediction needs 1.5 seconds of samples.

## Run the demo

From this folder, install the dependencies while connected to the internet. The demo was tested with Python 3.15 and the versions in `requirements.txt`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Join the OpenBCI WiFi network, disconnect any other acquisition session, and start the detector. Press Ctrl+C to stop.

```sh
.venv/bin/python jaw_temple.py
```

The default shield address is `192.168.4.1` and the local port is `6789`. Use `--ip` and `--port` for other settings.

## Rebuild the model offline

```sh
.venv/bin/python jaw_temple.py --train data/clench_emg_samples.csv.gz \
    --calibration data/jaw_temple_calibration.tsv.gz --model rebuilt.joblib
```

The November 14 training export contains 100 labeled half-second windows. Label 1 denotes clench and label 0 denotes rest or baseline. The script fits a balanced logistic regression on 78 windows, holding out four whole trials. The companion features CSV records the original window metadata and per-channel features. Rebuilding uses the raw sample columns in the samples CSV.

The November 15 calibration file contains jaw and temple voltages in µV and elapsed seconds from the first timestamp. The operator alternated 10 seconds of rest with 10 seconds of clench, starting at rest. The script calibrates the decision boundary using only the first pair, trimming a second at each cue. It also accepts the original tab-delimited Cyton WiFi BrainFlow export.

## Reading the output

For each 500-sample window, the detector subtracts the temple channel from the jaw channel and measures RMS amplitude from 80–200 Hz, excluding frequencies within 5 Hz of 120 and 180 Hz. The displayed amplitude is for the latest window. Classification uses the median of the latest three amplitudes. The bundled model crosses its decision boundary at about 10.5 µV RMS.

On the two later rest/clench pairs from the same calibration session, replay detected 21 of 38 clench windows and 36 of 40 rest windows. The periods were assigned from the operator's schedule. New sessions and electrode placements can change the amplitude.
