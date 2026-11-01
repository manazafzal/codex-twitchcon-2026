# Your first NOUS round

1. Download the ZIP and extract it. Double-click **setup.bat**. Setup explains each step and opens the welcome screen. A paused AI download still leaves the recording available.
2. Click the big **Try the demo** button. You see pretend chat and a clear **RECORDING** label whenever the local AI isn't ready. A complete round plays in less than thirty seconds, without Twitch login or runtime downloads.
3. The headline tells you what chat is trying to make the AI think about. During a secret round it says **???**. When guessing opens it says **Guess what the AI is thinking!** A visible timer counts down.
4. Read the short **How to play** strip. In a real Twitch chat, **!join** chooses a team and the bot welcomes you with one command to try next. Back an idea with **!push word**, guess with **!guess word**, or check your score with **!rank**. Ordinary team words and starter emotes count a little too.
5. Watch the build-up, then the word and winner in large text. The next round follows. The **Nerd panel** is optional, starts closed and cannot show a secret before reveal.

Choose **Connect my Twitch** when you want your own viewers to play. Twitch requires a free Public app code; the wizard links to registration and explains its fields. Say yes on Twitch, enter your channel name, and wait for the connection tick. Preparing the real AI the first time can take several minutes. The recording remains available while waiting. Failed steps explain what to fix and offer a retry. No config files to edit.

Use the private controls to start a round, or press **R** there. Broadcasters/moderators may also type **!round** and use **!immune**. Normal viewers cannot change modes. Add the public **/overlay/** address to OBS at 1920 × 1080; keep the private welcome/control address to yourself.

[Welcome screen](screenshots/welcome.png) · [Recorded reveal](screenshots/recorded-demo.png) · [Other measured scenes](perf.md).

These screenshots were captured from the actual local browser flow. The shipped recordings use actual test-backend calls and scripted pretend chat, not trained-model evidence. Native Windows setup, live Twitch login and OBS composition still need checks on a streamer's PC.
