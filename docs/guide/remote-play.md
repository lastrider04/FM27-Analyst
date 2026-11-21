# Remote play

[← Phone app](phone.md) · [Guide index](../../README.md#guide)

Remote play lets you **play FM27 from your phone**. The phone shows a live picture of the game and turns your taps into
mouse clicks and key presses on the PC. You can read the inbox, pick the team, change tactics, press Continue and
watch matches from the sofa. When FM27 stops processing and needs you, the phone chimes, buzzes, and can show a
notification even with the page closed.

It only sends input, the way you would at the PC. It never writes to game memory and never injects anything into FM27.

- [What you need](#what-you-need)
- [Turning it on](#turning-it-on)
- [Pairing a phone](#pairing-a-phone)
- [On the phone](#on-the-phone)
- [Phone notifications (Tailscale HTTPS)](#phone-notifications-tailscale-https)
- [Security](#security)
- [Problems](#problems)

## What you need
- **Windows 10 or 11**, with FM27 running on the PC. Windowed or borderless works best, and the window can be behind
  other windows but not minimised.
- **A few extra packages.** They're kept out of the main install because they're large (video encoding). Install
  them once, in the app's folder:

  ```
  .venv\Scripts\python -m pip install -r remote\requirements.txt
  ```

- **For smooth video:** a graphics card with a hardware H.264 encoder (NVIDIA NVENC or Intel Quick Sync). Without
  one it uses the CPU, or falls back to still pictures.
- **The phone on your home Wi-Fi**, or **[Tailscale](phone-tailscale.md)** to play from anywhere. Tailscale is also
  what makes phone notifications work.

## Turning it on
Open the **Remote** tab on the PC.
- **Start** runs remote play now. **Start with the analyst** runs it every time the analyst starts.
- Once it's running, the tab lists the addresses to open on the phone: your home Wi-Fi address, your Tailscale
  address, and the **https://….ts.net** address when Tailscale HTTPS is set up.
- The first time, Windows may ask whether to allow Python on your networks. Allow it on **Private networks**. That's
  all remote play needs on a home network (see [Windows Firewall](firewall.md)).

Remote play runs as its own background program (port 8777), so a problem in it can't take the analyst down. Its log
is `data\remote.log`.

## Pairing a phone
**Phones already set up with the [phone app](phone.md)** don't need to pair. On the PC, open **Settings › Phone** and,
next to the phone, turn on **Remote play on home Wi-Fi**, **Remote play over Tailscale**, or both. On the phone, the
phone app's **Remote** tab then has **On home Wi-Fi** and **Over Tailscale** buttons that open remote play, already
paired. Turning a switch off cuts that phone off on that network within seconds, and so does revoking the phone.

**Any other phone:** on the PC, **Remote tab › Show pairing code**. Scan the QR code with the phone's camera. That
opens remote play with the code filled in. Name the phone and tap **Pair**. Or open the address shown and type the
code. A phone paired this way can use every network remote play is on.

- A code works **once**, for **10 minutes**.
- Each address pairs separately (the Wi-Fi address, the https address), and so does an iPhone's Home Screen app.
- **Paired phones** in the Remote tab lists every phone and whether its notifications are on. **Unpair** cuts a phone
  off within seconds.
- Either way, remote play only answers on your home Wi-Fi or Tailscale, never from the internet.

## On the phone
**The picture.** Tap to click. Pinch to zoom, drag with two fingers to pan, and double-tap to zoom in or back to the
whole screen. Press and hold for a magnifier, slide to aim, and lift to click there. The minimap in the corner shows
where you are; tap it or drag on it to jump. Your zoom stays put when you open the analyst, switch apps or turn the
phone. **Fill** makes FM27 fill the screen (top to bottom on an upright phone; pan sideways with two fingers or the
minimap), and the button then reads **Fit**, which (like a double-tap) goes back to the whole of FM27.

**Back and Forward.** Draw a full circle with one finger: anticlockwise goes **Back**, clockwise goes **Forward**,
like the side buttons on a mouse. A label flashes to show which one was sent. It works in Mouse mode too, but not
while Drag or Scroll is on.

**The shortcut row** (FM27's own keys): **Continue**, Portal, Squad, Tactics, News, **Save** (Ctrl+S), and **App**.
To change them, open the analyst's **Remote tab › Shortcut row**: rename, reorder, remove or add buttons (up to 8), each with a key and an icon. Keys can be a letter, a number, F1-F12, space, enter, escape, tab, an arrow, or Ctrl+S; nothing else, so a button can never send something like Alt+F4. **Back to the defaults** undoes your changes. Phones pick up the new row the next time remote play opens.

**The tool bar** (swipe it for more): **Touch/Mouse** mode, **Keys** (the phone keyboard; the bars hide while it's up),
**Right** (the next tap is a right-click), **Drag** (for moving players on the tactics pitch), **Scroll** (one finger
turns the mouse wheel: drag up or down, or left and right for wide tables; it starts slow, gets faster the further you
drag, and keeps going while you hold at the edge of the screen), **Esc**, **Video**, **Fit / Fill**, **Full** (full screen on Android), **Analyst** and **Alerts**.
It's folded away to give FM27 more room: tap **Tools** (« at the end of the shortcut row) to open it, and tap it again
(it now reads **Hide**) to close it. It folds again by itself after 10 seconds untouched, unless Right, Drag or Scroll
is on. **Hold Tools** to pin both bars on screen: it reads **Pinned**, nothing folds away (even with a controller), and
the phone remembers it. Tap **Pinned** to fold them again.

**Game controller.** Connect a controller to the phone or tablet (Bluetooth or USB: Xbox, PlayStation, Switch Pro
and most others) and press any of its buttons. Both bars fold away so FM27 fills the screen, and a small **«** tab sits on the right
edge. It fades after a few seconds; tap it to bring back just the tool bar (with **Pad**, below, and a **Hide** button
to fold it, since the shortcut row is away), hold it to pin both bars, or drag it up or down if it's in the way. The bars come back when the controller disconnects.
- **Left stick:** moves the cursor (Mouse mode turns on by itself). A light push is slow and precise; a full push
  crosses the screen in about a second. When you're zoomed in, the picture follows the cursor.
- **Right stick:** scrolls at the cursor, up and down or left and right. In the App panel it scrolls the panel.
- **Buttons**, to start with: **A** clicks (hold it and move the stick to drag), **B** is Back, **X** right-clicks,
  **Y** is Esc, **LB** and **RB** are Squad and Tactics, **LT** and **RT** zoom out and in, **Menu** is Continue,
  **View** opens the App panel, pressing the left stick fits the screen, and the **d-pad** sends the arrow keys (hold
  to repeat).

Tap **Pad** to change them: each button can do anything from the tool bar or your shortcut row, show or hide the
tool bar, or nothing. Press a
button on the controller and its row lights up. The cursor speed is there too. Your choices are kept on that phone,
so a phone and a tablet can be set up differently. While the App panel is open, **B** closes it and the other buttons
leave FM27 alone.

**Video** steps through **Off → Low → Medium → High**: still pictures, then smooth video at 5, 10 or 16 Mbit/s. Medium
suits most home Wi-Fi.

**App** opens the analyst's data over the picture:
- **Next match:** suggested changes, who to rest, fitness alerts;
- **Squad:** condition, sharpness and form for every player, sortable; tap a player for more;
- **Fixtures:** the next ten matches and the last ten results.

**💬 Ask the coach** (bottom right of the panel) opens the analyst's AI coach. It uses the provider you set in the
analyst (**Settings › AI coach**), and your conversations are saved there too. Tap a tab to go back to the lists.

**Update** captures FM27 straight away. Tap **App** again or ✕ to close it.

**Back to the analyst.** The **Analyst** button (in the tool bar, and at the top of the App panel) opens the phone app.
Its **Remote** tab has **Open remote play** to come back.

**Alerts.** While FM27 is busy (processing days, preparing a match), **Continue** pulses. When it stops and needs
you, the phone chimes and buzzes (iPhones can't buzz from a web page) and shows FM27's own button: "Continue",
"Go To Match" and so on. The bell turns this on or off for that phone.

## Phone notifications (Tailscale HTTPS)
Phone browsers only allow notifications from https pages, so remote play also serves itself over HTTPS on your
Tailscale address. It uses a free certificate from Tailscale and changes none of your Tailscale settings.

1. Set up [Tailscale](phone-tailscale.md) on the PC and the phone, signed in to the same account.
2. In the Tailscale admin console, open the **DNS** page and turn on **MagicDNS** and **HTTPS Certificates**.
3. Restart remote play (**Stop**, then **Start**). The Remote tab now shows **https://your-pc.your-tailnet.ts.net**.
4. Open that address on the phone and pair it.
5. Tap the bell (it has an amber dot until notifications are allowed) and allow notifications. A test notification
   arrives.

**iPhone:** in Safari, tap Share › **Add to Home Screen**, open remote play from the Home Screen, and pair and allow
notifications there. iPhones (iOS 16.4 or later) only allow web notifications from Home Screen apps.

A notification goes to every paired phone with notifications on that isn't looking at remote play. A phone with the
page open gets the in-page alert instead. Tapping the notification opens remote play.

## Security
- Only **paired phones** can connect, and only from **private addresses**: your home network or Tailscale. Remote
  play refuses anything from the internet, and it isn't meant to go behind a public reverse proxy.
- Every action must come from remote play's own page (the WebSocket and every change are checked), so another website
  can't drive your PC.
- Input only goes to the FM27 window. While a phone is connected, a banner on the PC says so. **Ctrl+Alt+End** on the PC
  pauses or resumes control at once.
- Kept in `data\` (never shared): paired phones (only a hash of each phone's token), the notification signing key, the
  phones' notification subscriptions, and the Tailscale certificate.

## Problems
- **"Needs a few extra packages"** in the Remote tab: run the pip command under [What you need](#what-you-need), then
  click **Start**.
- **The phone can't connect on Wi-Fi:** check the phone is on the same network and that Windows allowed Python on
  Private networks ([Windows Firewall](firewall.md)). Your home network must be set to *Private* in Windows.
- **No https address in the Remote tab:** Tailscale isn't running or connected, or HTTPS Certificates is off. The
  reason is in `data\remote.log`.
- **Video says "using pictures instead":** the phone's browser couldn't start video, or the network blocked it. Still
  pictures keep working. Try **Video › Low**.
- **No notifications:** use the https address, allow notifications for the site (iPhone: from the Home Screen app),
  and check the Remote tab shows "notifications on" for that phone.
- **No Pad button with a controller connected:** press a button on the controller; browsers only show a controller
  to a page after that. Check the phone itself sees it (Bluetooth settings). If it still doesn't appear, open remote
  play on the https (Tailscale) address: some browsers only allow controllers on secure pages.
- **The picture is black or stale:** FM27 is minimised. Restore its window on the PC.
