"""Remote play: see and control FM27 from the phone.

A separate process from the analyst (`python -m remote`). It streams the FM27 window and sends the phone's taps,
drags, scrolls and typing as ordinary mouse and keyboard input. It never reads or writes game memory and never
injects anything into FM27. See docs/remote-play/PLAN.md.
"""
