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
where you are; tap it or drag on it to jump.

**The shortcut row** (FM27's own keys): **Continue**, Portal, Squad, Tactics, News, **Save** (Ctrl+S), and **App**.
You can change the shortcuts in `data\remote_shortcuts.json`. Only single keys are allowed, plus Ctrl+S.

**The tool bar** (swipe it for more): **Touch/Mouse** mode, **Keys** (the phone keyboard; the bars hide while it's up),
**Right** (the next tap is a right-click), **Drag** (for moving players on the tactics pitch), **Scroll** (one finger
turns the mouse wheel), **Esc**, **Video**, **Fit**, **Full** (full screen on Android), **Analyst** and **Alerts**.

**Video** steps through **Off → Low → Medium → High**: still pictures, then smooth video at 5, 10 or 16 Mbit/s. Medium
suits most home Wi-Fi.

**App** opens the analyst's data over the picture:
- **Next match:** suggested changes, who to rest, fitness alerts;
- **Squad:** condition, sharpness and form for every player, sortable; tap a player for more;
- **Fixtures:** the next ten matches and the last ten results.

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
- **The picture is black or stale:** FM27 is minimised. Restore its window on the PC.
