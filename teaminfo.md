# Touch-Free Computer Interaction

*Working title; final project name is undecided.*

## Project idea

Build a touch-free way to interact with a laptop when a person's hands are occupied or they are a short distance from the computer. The laptop camera tracks hand movement and gestures, then uses them to control a small set of computer actions.

This project idea was motivated by the need for a way to control my laptop from a distance when I am washing plates, doing dishes or just not within reach of the keyboard. I often want to pause media or move through an app or change volume. It may also be useful to people who have difficulty using a trackpad, but that would need to be discussed.

## Intended users

- **Primary for the hackathon demo:** people whose hands are occupied and want to interact with their laptop without touching it.
- **Potential future users:** people who find a trackpad difficult to use. 

## MVP direction

The MVP should demonstrate that a person can use hand tracking to control a computer from a distance. The current core is:

1. An intentional gesture activates control.
2. The tracked fingertip moves the on-screen cursor.
3. A deliberate gesture selects or clicks.
4. The interface makes it obvious when gestures are controlling the computer. (maybe like a screen edge glow)

App launching is optional and is not required to prove the core idea. Opening and closing apps, switching apps, and changing volume or brightness are future possibilities, not MVP commitments.

## Interaction states under consideration

- **Off:** computer control is not available; the earlier preference was for no persistent app indicator in this state.
- **Armed:** the app runs in the background and continuously looks for an activation gesture. A notification or menu-bar indicator should tell the user it is running. (it will probsbly mostly going to be in this state)
- **Active:** gestures control the computer, with a prominent visual cue. An edge glow or overlay was suggested; the final treatment is undecided.

The transition from active back to armed or off, and the immediate way to stop control, still need to be decided.

## Gestures discussed so far as well as ideas

- What gestures do we use to ACTIVATE the program? we could use unorthodox ones such as a one-hand heart or an infinity sign (like gojo's... :) )
- Finger-tip movement for cursor movement.
- A pinch-like gesture for clicking or selection.
- Optional gestures for scrolling or switching apps.

Potential issue: The activation gesture must be distinct from movement and click gestures. In particular, the heart pose uses the thumb and index finger, which may conflict with a pinch click, especially if we are trying to switch off the program. We don't want to accidentally click instead.
We should compare gestures in actual camera tests and gather user feedback by asking people what gestures they prefer to use

## Platform and technical constraints

- **Demo target:** a MacBook, using its built-in webcam.
- **Distance goal:** work reliably at up to about 10 feet. This is a core part of the intended hands-busy use case and must be tested at that distance.
- **Computer vision:** detect hand landmarks or poses from the camera and map them to cursor movement and intentional actions. MediaPipe Hand Landmarker is one candidate.
- **System control:** full operating-system control requires permissions and platform-specific integration. On macOS, camera use and Accessibility control require user permission. Windows has a separate UI Automation framework.
- **Web versus desktop:** a browser-based prototype can demonstrate camera tracking and gestures within a page, but browser code alone does not provide general control over other apps and the system cursor. A local desktop component is the likely direction for OS-wide interaction; the exact approach is undecided.
- **Team collaboration:** Windows teammates can work on platform-independent gesture logic, interface work, and a simulated desktop. Mac-specific system control must be verified on a Mac.

## Safety, privacy, and usability

- Preventing unintended cursor actions is a priority, especially unintended clicks.
- Users need to understand when the app is watching for the activation gesture and when gestures can control the computer.
- Camera processing and whether frames are stored or transmitted need an explicit privacy decision. The local-first direction is preferred, but implementation is not yet settled.
- Cursor jitter, false activation, missed gestures, lighting, camera framing, and fatigue from holding a hand up are risks to evaluate.
- Set a measurable reliability standard for the 10-foot demo, including what level of missed gestures and accidental actions is acceptable.

## Potential HackCamp fit

- **Best Design:** if the interaction states, feedback, and gesture experience are clear and polished.
- **Community Impact:** if the submission explains the intended hands-busy use case and the potential accessibility value honestly.
- **Most Accessible Design:** potentially relevant only if the team is in the Beginner Stream, opts in, submits a Figma link, and describes its accessibility considerations. (unfortunately only 50% of the team are beginners so maybe not :) ).

No sponsor technology or prize track has been selected. Computer vision is central to the idea.

## Open decisions

- Final project name.
- Activation gesture and how it avoids colliding with cursor and click gestures.
- Click/selection gesture.
- How the user pauses or turns off control, including an immediate stop action.
- What persistent indicator communicates the armed state and what prominent cue communicates active control.
- Which controls are in the demo beyond cursor movement and selection.
- Whether the demo controls the real Mac desktop or a simulated environment.
- Computer-vision library and local app approach.
- Privacy behavior for camera frames.
- Reliability thresholds and the test conditions for the 10-foot goal.

## References

- [MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker)
- [Apple: Control access to the camera on Mac](https://support.apple.com/en-ie/guide/mac-help/mchlf6d108da/27/mac/27)
- [Apple: Allow accessibility apps to access your Mac](https://support.apple.com/en-az/guide/mac-help/mh43185/mac)
- [Microsoft: UI Automation overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview)


Similar projects for refereince:
How to use gestures to control mouse - https://github.com/jayant1211/gesture-controlled-mouse (we need to credit them if we use their project)

languages to use: Python 
libraries = PyAutoGUI

MediaPipe for hand landmarks; Google provides a Python hand-tracking guide. (MediaPipe Python guide)
PyAutoGUI for basic cursor movement and clicking. It supports macOS and Windows, which helps. (PyAutoGUI docs)
PySide6 if you need a desktop window for the status and controls. It’s Qt’s official Python binding and has VS Code guidance. (PySide6 quick start)
