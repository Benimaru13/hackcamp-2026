# AirTrack for macOS — tester guide

Thanks for trying AirTrack. It uses your Mac's webcam to track your hand and
control the pointer from across the room. This build is a small usability test,
not a finished product.

**Before you start:** this build is for **Apple Silicon Macs** (M1, M2, M3, M4…).
It will not open on an Intel Mac. This build was made and checked on Apple
Silicon only.

---

## 1. Install (about a minute)

1. Download `AirTrack-0.1.0-macos-arm64.zip` and double-click it to unzip.
2. Drag **AirTrack** into your **Applications** folder (running it from
   Applications makes the permission steps behave predictably).
3. macOS will warn that the app is from an unidentified developer. That is
   expected for this test build.

## 2. First launch

1. In Applications, **right-click AirTrack → Open**, then click **Open** in the
   dialog. (Double-clicking first only offers "Move to Bin".)
   If macOS still refuses: **System Settings → Privacy & Security**, scroll down,
   click **Open Anyway**, then launch again.
2. **Camera prompt:** click **Allow**. If you dismissed it, or the camera window
   is black, go to **System Settings → Privacy & Security → Camera** and switch
   on AirTrack, then relaunch.
3. **Accessibility:** AirTrack opens the **Privacy & Security → Accessibility**
   pane (it cannot add itself). Click **+**, choose
   **Applications → AirTrack**, and switch it on. **Quit and relaunch AirTrack**
   after granting it. Without this the camera and gestures work but the pointer
   never moves.
4. AirTrack asks you to stand about 3 m back and raise an open palm, then hold
   still and point for 3.5 seconds. Both steps finish on their own. Click
   **CONFIRM** once the "Calibrated" card appears.

If nothing opens at all, open **Terminal** and run this, then send us the output:

```bash
/Applications/AirTrack.app/Contents/MacOS/AirTrack --self-check
```

## 3. Using it

Stand roughly 2–3 m back, in a normally lit room, facing a lamp rather than a
window. Keep your whole hand in the camera's view.

| Do this | What happens |
| --- | --- |
| Open palm, held up ~½ second | Takes control (amber halo → green halo) |
| Point with your index finger | Moves the pointer |
| Point, then hold still ~2 seconds | One click where the pointer stopped |
| Fist, held ~⅓ second | Releases control (green halo → amber) |
| Two fingers up/down, held | Scrolls up/down |
| Two fingers pointing left/right, held ~½ second | Previous / next desktop space |
| `Esc` or `q` (in the AirTrack window) | Quits, control released |
| `space` (in the AirTrack window) | Pauses / resumes tracking |

**To stop at any moment:** make a fist, press `Esc`/`q`, press `Ctrl-C` in the
terminal if you launched it there, or slam the pointer into a screen corner
(PyAutoGUI's emergency stop). Nothing keeps controlling the Mac after the app
quits.

The coloured border around your whole screen is the state cue: amber = watching
but not controlling, green = gestures are controlling the pointer.

## 4. Troubleshooting

| Symptom | Try |
| --- | --- |
| "AirTrack is damaged" / cannot be opened | Right-click → Open; then System Settings → Privacy & Security → Open Anyway |
| Camera window is black | Camera permission off for AirTrack — enable it and relaunch |
| Hand is detected, pointer never moves | Accessibility permission off — enable AirTrack, then relaunch |
| Hand not found | Stand closer (2–3 m), face a light, keep the hand inside the preview |
| Pointer jitters | Hold the hand a little steadier, or let us know in the feedback form |
| App quits unexpectedly | Run the `--self-check` command above; the app also writes `~/Library/Application Support/AirTrack/airtrack-error.log` |

Nothing is recorded: frames are processed in memory and discarded, and the app
makes no network requests at all in this build (the hand model is included).

---

## 5. Feedback checklist

Please answer these in a few sentences each — short is fine. Send them back by
whichever channel you received the build, with your **Mac model and macOS
version** (Apple menu → About This Mac).

**Setup**
- How long did it take from unzip to the first successful gesture?
- Which step was confusing or felt unnecessary? Did either permission step
  catch you out?
- Did the app open on the first try, or did Gatekeeper/camera/Accessibility
  block it? What did you have to do?

**Accidental actions**
- Did the pointer move, click or scroll when you did not mean it? Roughly how
  often, and what were you doing at the time?
- Did the app take control (green border) without you intending to arm it?

**Gesture control**
- Could you reliably arm with the open palm? If not, at what distance?
- How was the pointer's speed and smoothness? Too fast, too slow, shaky?
- Did the 2-second hold-to-click work where you aimed? Did it ever double-click?
- Did scroll and desktop switching work? Did they fire when you did not want
  them to?

**Stopping control**
- Did the fist reliably release control?
- Did you ever feel you could not stop it quickly enough?
- Did the green/amber border make the current state obvious from where you
  stood?

**Anything else**
- What would you change first? What did you expect to be able to do that you
  could not? Any other notes, including lighting, distance, and whether you were
  wearing glasses.
