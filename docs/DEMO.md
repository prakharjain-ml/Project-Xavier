# 2-minute demo script (draft, fill in Sunday)

| Time | Who | What |
| --- | --- | --- |
| 0:00-0:15 | Prakhar | Problem in one sentence: people who can't use a joystick lose independence. |
| 0:15-0:30 | Prakhar | How: look at a flickering arrow; your visual cortex echoes its frequency; we read it. |
| 0:30-1:25 | Wearer + Prakhar | Live Mode 1: forward after dwell, turn in place, look away to stop (< 1 s), obstacle placed in front stops forward motion, close eyes for latched E-STOP + operator re-arm, then spotter presses hardware kill switch. Point at the dwell bar. |
| 1:25-1:40 | Prakhar | Safety recap: STOP by default, 200 ms ESP32 watchdog, local ultrasonic cutoff, battery kill switch, photosensitivity screening. |
| 1:40-2:00 | Prakhar | What we learned + what's next (Mode 2 if it works, calibration-free, clinical partners). |

## Judge interruptions to rehearse
- "What happens if the signal drops?" -> stale data means STOP within 0.5 s; show it.
- "How accurate is it?" -> the real number from Phase 3, with window length.
- "Couldn't eye tracking do this?" -> honest answer: yes for some users; SSVEP needs no camera calibration,
  works in more lighting, and is a step toward richer BCI control.
- "What did you personally build?" -> each person names their folder.
